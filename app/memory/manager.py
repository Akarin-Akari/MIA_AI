"""Memory manager — orchestrates all three memory tiers.

Provides unified interface for the Agent to interact with memory:
- get_context(): Assembles system context + working messages for LLM
- after_turn(): Persists messages and extracts facts (fire-and-forget)

CRITICAL ORDERING:
- after_turn() persists the FINAL answer (post-verifier), NOT the initial draft
- Fact extraction uses asyncio.create_task (fire-and-forget, non-blocking)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.llm.base import CanonicalMessage
from app.memory.markdown_store import MarkdownMemory
from app.memory.retriever import Retriever
from app.memory.sqlite_store import SQLiteStore
from app.memory.working import WorkingMemory

logger = logging.getLogger(__name__)


class MemoryManager:
    """Orchestrates Working + Markdown + SQLite + Retriever memory tiers.

    Attributes:
        working: Tier 1 in-memory conversation buffer.
        markdown: Tier 2 file-based profile and facts.
        sqlite: Tier 3 persistent message and fact storage.
        retriever: RAG retriever (NoOp by default).
    """

    def __init__(
        self,
        working: WorkingMemory,
        markdown: MarkdownMemory,
        sqlite: SQLiteStore,
        retriever: Retriever,
    ) -> None:
        self.working = working
        self.markdown = markdown
        self.sqlite = sqlite
        self.retriever = retriever

    async def get_context(
        self,
        conv_id: str,
        max_chars: int = 4000,
        top_k_facts: int = 5,
        history_limit: int = 10,
    ) -> tuple[str, list[CanonicalMessage]]:
        """Assemble context for LLM consumption.

        Returns TWO things that MUST BOTH be used by AgentExecutor:
        1. system_ctx (str): Goes into system prompt — profile + facts + RAG
        2. working_msgs (list[CanonicalMessage]): Goes into messages sequence head

        NEVER ignore working_msgs — that was v2's most damaging anti-pattern.

        Args:
            conv_id: Conversation identifier.
            max_chars: Budget for system context string.
            top_k_facts: Number of recent facts to include.
            history_limit: Max working memory messages to return.

        Returns:
            Tuple of (system_context_string, working_messages_list).
        """
        parts: list[str] = []

        # Load system prompt template (relative to memory_dir parent, NOT CWD)
        system_prompt_path = Path(self.markdown._memory_dir).parent / "prompts" / "system.md"
        if system_prompt_path.exists():
            parts.append(system_prompt_path.read_text(encoding="utf-8"))

        # Profile context
        profile = await self.markdown.get_profile()
        if profile:
            profile_lines = ["## User Profile"]
            for key, meta in profile.items():
                if isinstance(meta, dict) and "value" in meta:
                    profile_lines.append(f"- {key}: {meta['value']}")
                else:
                    profile_lines.append(f"- {key}: {meta}")
            parts.append("\n".join(profile_lines))

        # Recent facts
        facts = await self.markdown.get_top_k_facts(k=top_k_facts)
        if facts:
            facts_section = "## Known Facts\n" + "\n".join(f"- {f}" for f in facts)
            parts.append(facts_section)

        # RAG results — Layer 2 will call self.retriever.search() here
        # Layer 1 ships with NoOpRetriever (returns empty)

        # Assemble with budget
        system_ctx = "\n\n".join(parts)
        if len(system_ctx) > max_chars:
            system_ctx = system_ctx[:max_chars] + "\n...(truncated)"

        # Working memory messages
        working_msgs = self.working.get_messages(conv_id)
        if len(working_msgs) > history_limit:
            working_msgs = working_msgs[-history_limit:]

        return system_ctx, working_msgs

    async def after_turn(
        self,
        conv_id: str,
        user_msg: str,
        agent_response: str,
    ) -> None:
        """Post-turn processing: persist messages and extract facts.

        CRITICAL: This method receives the FINAL answer (post-verifier),
        NOT the initial draft. The caller (AgentExecutor) must pass
        `verifier.revised_answer or original_response`.

        Fact extraction is fire-and-forget (asyncio.create_task) to avoid
        blocking the response. TTFB is critical.

        This method has a total catch-all — SQLite/file errors MUST NOT
        propagate as unhandled background exceptions.

        Args:
            conv_id: Conversation identifier.
            user_msg: User's message text.
            agent_response: FINAL agent response (post-verification).
        """
        try:
            # Persist to working memory
            self.working.append(conv_id, CanonicalMessage(role="user", content=user_msg))
            self.working.append(conv_id, CanonicalMessage(role="assistant", content=agent_response))

            # Persist to SQLite
            await self.sqlite.save(conv_id, "user", user_msg)
            await self.sqlite.save(conv_id, "assistant", agent_response)

            # Fire-and-forget fact extraction (non-blocking)
            asyncio.create_task(self._extract_facts(conv_id, user_msg, agent_response))

        except Exception as e:
            # Total catch-all: after_turn runs in create_task from AgentExecutor.
            # Unhandled exceptions here become silent background failures.
            logger.error("after_turn failed for conv=%s: %s", conv_id, e, exc_info=True)

    async def _extract_facts(
        self,
        conv_id: str,
        user_msg: str,
        agent_response: str,
    ) -> None:
        """Extract and persist facts from conversation turn.

        This runs as a fire-and-forget task — errors are logged, not raised.

        In Layer 1, this is a simple heuristic extractor.
        Layer 2 replaces with LLM-based extraction using prompts/memory_extract.md.
        """
        try:
            # Simple heuristic: look for "my name is", "I'm", "I am", etc.
            # Full LLM-based extraction is added in Layer 2
            lower = user_msg.lower()

            # Extract name patterns
            for pattern in ["my name is ", "i'm ", "call me "]:
                if pattern in lower:
                    idx = lower.index(pattern) + len(pattern)
                    name = user_msg[idx:].split(".")[0].split(",")[0].strip()
                    if name and len(name) < 50:
                        await self.markdown.append_fact(f"User's name might be: {name}")
                        await self.sqlite.save_fact(conv_id, f"name_hint: {name}")
                        break

            logger.debug("Fact extraction complete for conv=%s", conv_id)

        except Exception as e:
            # Fire-and-forget: log but never crash
            logger.error("Fact extraction failed for conv=%s: %s", conv_id, e)
