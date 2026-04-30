"""Agent core — ReAct loop with failure detection.

AgentExecutor orchestrates:
1. LLM chat with tool specs
2. Tool execution via registry
3. RepeatedFailureDetector per conv_id
4. SelfVerifier (await-blocked in main chain)
5. MemoryManager.after_turn (fire-and-forget)

CRITICAL ORDERING:
- await verifier.verify() → get revised_answer → THEN create_task(after_turn)
- NEVER reverse this order
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import deque
from typing import Any

from app.agent.verifier import SelfVerifier
from app.llm.base import CanonicalMessage, LLMClient, LLMResponse
from app.memory.manager import MemoryManager
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class RepeatedFailureDetector:
    """Detects repeated identical tool calls per conversation.

    Tracks (tool_name, input_hash) per conv_id. When the same signature
    appears N consecutive times, should_intervene() returns True.

    CRITICAL: Must be per-conv_id — NEVER shared across conversations.
    This class uses dict[conv_id, list] for isolation.
    """

    def __init__(self, max_repeats: int = 3) -> None:
        self._max_repeats = max_repeats
        # Per conv_id tracking — bounded deque prevents memory leak
        self._history: dict[str, deque[str]] = {}

    @staticmethod
    def _signature(tool_name: str, tool_input: dict[str, Any]) -> str:
        """Create a fingerprint for a tool call."""
        raw = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def record(self, conv_id: str, tool_name: str, tool_input: dict[str, Any]) -> None:
        """Record a tool call for a conversation.

        Args:
            conv_id: Conversation identifier.
            tool_name: Name of the tool called.
            tool_input: Arguments passed to the tool.
        """
        sig = self._signature(tool_name, tool_input)
        if conv_id not in self._history:
            self._history[conv_id] = deque(maxlen=self._max_repeats)
        self._history[conv_id].append(sig)

    def should_intervene(self, conv_id: str) -> bool:
        """Check if the same tool call has been repeated too many times.

        Args:
            conv_id: Conversation identifier.

        Returns:
            True if last N calls have the same signature.
        """
        history = self._history.get(conv_id)
        if not history or len(history) < self._max_repeats:
            return False
        # deque is bounded to max_repeats — check if all entries are identical
        return len(set(history)) == 1

    def reset(self, conv_id: str) -> None:
        """Reset failure tracking for a conversation."""
        self._history.pop(conv_id, None)

    def get_intervention_message(self, conv_id: str) -> str:
        """Generate intervention message for the LLM."""
        return (
            f"[SYSTEM] You have called the same tool with the same input "
            f"{self._max_repeats} times consecutively. "
            f"Try a DIFFERENT approach or tool."
        )


class AgentExecutor:
    """Main agent execution engine with ReAct loop.

    Orchestrates LLM → Tool → Verify → Memory pipeline.

    CRITICAL ORDERING (main response chain):
    1. ReAct loop produces draft answer
    2. await verifier.verify() — BLOCKING (gets revised_answer)
    3. final_answer = revised_answer or draft
    4. asyncio.create_task(memory.after_turn()) — FIRE-AND-FORGET
    5. Return final_answer

    NEVER reverse steps 2 and 4.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        memory_manager: MemoryManager,
        verifier: SelfVerifier,
        max_iterations: int = 10,
    ) -> None:
        self._llm = llm_client
        self._tools = tool_registry
        self._memory = memory_manager
        self._verifier = verifier
        self._max_iterations = max_iterations
        # Per-conv_id failure detector — dict[conv_id, Detector] pattern
        self._detector = RepeatedFailureDetector()

    async def run(
        self,
        user_message: str,
        conversation_id: str,
    ) -> CanonicalMessage:
        """Execute a full agent turn with ReAct loop.

        Args:
            user_message: User's input message.
            conversation_id: Conversation identifier for isolation.

        Returns:
            Final CanonicalMessage with verified response.
        """
        try:
            return await self._run_inner(user_message, conversation_id)
        except Exception as e:
            # NEVER crash the agent — degrade gracefully
            logger.error("Agent run failed: %s", e, exc_info=True)
            error_response = f"I'm sorry, I encountered an error: {type(e).__name__}. Please try again."
            return CanonicalMessage(role="assistant", content=error_response)
        finally:
            # Always clean up per-turn tracking to prevent memory leak
            self._detector.reset(conversation_id)

    async def _run_inner(
        self,
        user_message: str,
        conversation_id: str,
    ) -> CanonicalMessage:
        """Inner ReAct loop implementation."""
        # Get context from memory (pass user query for RAG retrieval)
        system_ctx, working_msgs = await self._memory.get_context(
            conversation_id, query=user_message,
        )

        # Build initial messages
        messages: list[CanonicalMessage] = list(working_msgs)
        messages.append(CanonicalMessage(role="user", content=user_message))

        tool_results_collected: list[str] = []
        tool_specs = self._tools.specs()

        # Defensive guard — config validates this, but defense in depth
        effective_max = max(self._max_iterations, 1)
        draft_answer = ""

        # ── ReAct Loop ───────────────────────────────────────────────
        for iteration in range(effective_max):
            logger.info("ReAct iteration %d/%d for conv=%s", iteration + 1, self._max_iterations, conversation_id)

            # Call LLM
            response: LLMResponse = await self._llm.chat(
                messages=messages,
                tools=tool_specs if tool_specs else None,
                system=system_ctx,
            )

            if response.stop_reason == "end_turn" or not response.tool_calls:
                # LLM decided to respond — exit loop
                draft_answer = response.content or ""

                # Append assistant message to history
                messages.append(CanonicalMessage(
                    role="assistant",
                    content=draft_answer,
                    tool_calls=response.tool_calls or None,
                ))

                break
            else:
                # LLM wants to use tools
                # Add assistant message with tool_calls
                messages.append(CanonicalMessage(
                    role="assistant",
                    content=response.content or None,
                    tool_calls=response.tool_calls,
                ))

                # Execute each tool call and collect results
                for tc in response.tool_calls:
                    # Check for repeated failures
                    self._detector.record(conversation_id, tc.name, tc.input)
                    if self._detector.should_intervene(conversation_id):
                        intervention = self._detector.get_intervention_message(conversation_id)
                        messages.append(CanonicalMessage(
                            role="tool_result",
                            content=intervention,
                            tool_call_id=tc.id,
                        ))
                        self._detector.reset(conversation_id)
                        tool_results_collected.append(intervention)
                        continue

                    # Execute tool with retry (max 2 retries on failure)
                    MAX_TOOL_RETRIES = 2
                    result = ""
                    for attempt in range(MAX_TOOL_RETRIES + 1):
                        result = await self._tools.execute(tc.name, tc.input)
                        if not result.startswith("ERROR:"):
                            break
                        logger.warning(
                            "Tool '%s' failed (attempt %d/%d): %s",
                            tc.name, attempt + 1, MAX_TOOL_RETRIES + 1, result[:200],
                        )
                        if attempt < MAX_TOOL_RETRIES:
                            logger.info("Retrying tool '%s'...", tc.name)

                    tool_results_collected.append(result)

                    # Add tool_result matched by ID (NOT position)
                    messages.append(CanonicalMessage(
                        role="tool_result",
                        content=result,
                        tool_call_id=tc.id,
                    ))

        else:
            # Max iterations reached
            draft_answer = response.content or "I've reached my maximum number of steps. Let me provide what I have so far."

        # ── Verification (MUST await — blocking) ─────────────────────
        profile = await self._memory.markdown.get_profile()
        verification = await self._verifier.verify(
            question=user_message,
            answer=draft_answer,
            tool_results=tool_results_collected,
            profile=profile,
        )

        # Use revised answer if verifier provides one
        final_answer = verification.revised_answer or draft_answer
        if verification.revised_answer:
            logger.info("Verifier revised answer for conv=%s", conversation_id)

        # ── Memory Persistence (fire-and-forget) ─────────────────────
        asyncio.create_task(
            self._memory.after_turn(conversation_id, user_message, final_answer)
        )

        return CanonicalMessage(role="assistant", content=final_answer)
