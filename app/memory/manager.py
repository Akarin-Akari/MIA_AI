"""Memory manager — orchestrates all three memory tiers.

Provides unified interface for the Agent to interact with memory:
- get_context(): Assembles system context + working messages for LLM
- after_turn(): Persists messages and extracts facts (fire-and-forget)

CRITICAL ORDERING:
- after_turn() persists the FINAL answer (post-verifier), NOT the initial draft
- Fact extraction uses asyncio.create_task (fire-and-forget, non-blocking)

Context Assembly Strategy (priority-based budget allocation):
- P0: System prompt — fixed cost, never trimmed
- P1: User profile — compact, rarely trimmed
- P2: RAG results — 60% of variable budget, trimmed by score
- P3: Known facts — 40% of variable budget, trimmed oldest-first
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.llm.base import CanonicalMessage, LLMClient
from app.memory.markdown_store import MarkdownMemory
from app.memory.retriever import Retriever
from app.memory.sqlite_store import SQLiteStore
from app.memory.working import WorkingMemory

logger = logging.getLogger(__name__)

# Safety buffer to prevent off-by-one overflow in context assembly
_BUDGET_SAFETY_BUFFER = 200


class MemoryManager:
    """Orchestrates Working + Markdown + SQLite + Retriever memory tiers.

    Attributes:
        working: Tier 1 in-memory conversation buffer.
        markdown: Tier 2 file-based profile and facts.
        sqlite: Tier 3 persistent message and fact storage.
        retriever: RAG retriever (FTS5 by default, NoOp fallback).
    """

    def __init__(
        self,
        working: WorkingMemory,
        markdown: MarkdownMemory,
        sqlite: SQLiteStore,
        retriever: Retriever,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.working = working
        self.markdown = markdown
        self.sqlite = sqlite
        self.retriever = retriever
        self._llm_client = llm_client  # For LLM-based fact extraction

    # ── Context Assembly (Priority-Based Budget) ─────────────────────

    async def get_context(
        self,
        conv_id: str,
        query: str = "",
        max_chars: int = 4000,
        top_k_facts: int = 5,
        history_limit: int = 10,
    ) -> tuple[str, list[CanonicalMessage]]:
        """Assemble context for LLM consumption with priority-based budget.

        Returns TWO things that MUST BOTH be used by AgentExecutor:
        1. system_ctx (str): Goes into system prompt — profile + facts + RAG
        2. working_msgs (list[CanonicalMessage]): Goes into messages sequence head

        Budget allocation strategy:
        - P0 (system prompt) + P1 (profile) = fixed cost, always included
        - P2 (RAG) gets 60% of remaining variable budget
        - P3 (facts) gets 40% of remaining variable budget
        - Facts are trimmed oldest-first; RAG results trimmed by score

        Args:
            conv_id: Conversation identifier.
            query: Current user query for RAG retrieval.
            max_chars: Total budget for system context string.
            top_k_facts: Number of recent facts to include.
            history_limit: Max working memory messages to return.

        Returns:
            Tuple of (system_context_string, working_messages_list).
        """
        # ── P0: System Prompt (fixed, never trimmed) ─────────────────
        system_prompt = ""
        system_prompt_path = Path(self.markdown._memory_dir).parent / "prompts" / "system.md"
        if system_prompt_path.exists():
            system_prompt = system_prompt_path.read_text(encoding="utf-8")

        # ── P1: Profile (compact, rarely needs trimming) ─────────────
        profile_section = self._build_profile_section(
            await self.markdown.get_profile()
        )

        # ── Budget calculation ───────────────────────────────────────
        fixed_cost = len(system_prompt) + len(profile_section)
        variable_budget = max(0, max_chars - fixed_cost - _BUDGET_SAFETY_BUFFER)

        # ── P2: RAG Results (60% of variable budget) ─────────────────
        rag_budget = int(variable_budget * 0.6)
        rag_section = ""
        if query:
            rag_section = await self._build_rag_section(query, rag_budget)

        # ── P3: Facts (40% of variable budget, newest kept first) ────
        facts_budget = int(variable_budget * 0.4)
        facts_section = await self._build_facts_section(top_k_facts, facts_budget)

        # ── Assemble ─────────────────────────────────────────────────
        sections = [s for s in [system_prompt, profile_section, rag_section, facts_section] if s]
        system_ctx = "\n\n".join(sections)

        # Working memory messages
        working_msgs = self.working.get_messages(conv_id)
        if len(working_msgs) > history_limit:
            working_msgs = working_msgs[-history_limit:]

        return system_ctx, working_msgs

    @staticmethod
    def _build_profile_section(profile: dict[str, Any]) -> str:
        """Build profile context string from profile dict."""
        if not profile:
            return ""
        lines = ["## User Profile"]
        for key, meta in profile.items():
            if isinstance(meta, dict) and "value" in meta:
                lines.append(f"- {key}: {meta['value']}")
            else:
                lines.append(f"- {key}: {meta}")
        return "\n".join(lines)

    async def _build_rag_section(self, query: str, budget: int) -> str:
        """Build RAG results section within budget, trimmed by score."""
        rag_results = await self.retriever.search(query, limit=3)
        if not rag_results:
            return ""

        header = "## Relevant Past Context"
        used = len(header)
        lines = [header]

        for r in rag_results:
            snippet = r.get("text", "")[:300]
            line = f"- {snippet}"
            if used + len(line) + 1 > budget:
                lines.append("- _(more results available)_")
                break
            lines.append(line)
            used += len(line) + 1

        return "\n".join(lines) if len(lines) > 1 else ""

    async def _build_facts_section(self, top_k: int, budget: int) -> str:
        """Build facts section within budget, trimming oldest first."""
        facts = await self.markdown.get_top_k_facts(k=top_k)
        if not facts or budget <= 0:
            return ""

        header = "## Known Facts"
        used = len(header)
        kept_lines: list[str] = []

        # facts are newest-last from get_top_k_facts, iterate newest-first
        for fact in reversed(facts):
            line = f"- {fact}"
            if used + len(line) + 1 > budget:
                break
            kept_lines.insert(0, line)  # preserve chronological order
            used += len(line) + 1

        if not kept_lines:
            return ""
        return header + "\n" + "\n".join(kept_lines)

    # ── Post-Turn Processing ─────────────────────────────────────────

    async def after_turn(
        self,
        conv_id: str,
        user_msg: str,
        agent_response: str,
    ) -> None:
        """Post-turn processing: persist messages, index for retrieval, extract facts.

        CRITICAL: This method receives the FINAL answer (post-verifier),
        NOT the initial draft. The caller (AgentExecutor) must pass
        `verifier.revised_answer or original_response`.

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

            # Index for retrieval (FTS5 or NoOp)
            try:
                doc_text = f"User: {user_msg}\nAssistant: {agent_response[:500]}"
                await self.retriever.add(conv_id, doc_text)
            except Exception as e:
                logger.warning("Retriever indexing failed (non-fatal): %s", e)

            # Fire-and-forget fact extraction (non-blocking)
            asyncio.create_task(self._extract_facts(conv_id, user_msg, agent_response))

        except Exception as e:
            # Total catch-all: after_turn runs in create_task from AgentExecutor.
            # Unhandled exceptions here become silent background failures.
            logger.error("after_turn failed for conv=%s: %s", conv_id, e, exc_info=True)

    # ── Fact Extraction ──────────────────────────────────────────────

    async def _extract_facts(
        self,
        conv_id: str,
        user_msg: str,
        agent_response: str,
    ) -> None:
        """Extract and persist facts from conversation turn.

        Primary: LLM-based extraction using prompts/memory_extract.md
        Fallback: Heuristic pattern matching (when LLM unavailable)

        This runs as a fire-and-forget task — errors are logged, not raised.
        """
        try:
            facts: list[str] = []

            # Primary: LLM-based extraction
            if self._llm_client:
                facts = await self._extract_facts_llm(user_msg, agent_response)

            # Fallback: heuristic extraction
            if not facts:
                facts = self._extract_facts_heuristic(user_msg)

            # Persist extracted facts
            for fact in facts:
                await self.markdown.append_fact(fact)
                await self.sqlite.save_fact(conv_id, fact)

            if facts:
                logger.info("Extracted %d fact(s) for conv=%s", len(facts), conv_id)
            else:
                logger.debug("No facts extracted for conv=%s", conv_id)

        except Exception as e:
            # Fire-and-forget: log but never crash
            logger.error("Fact extraction failed for conv=%s: %s", conv_id, e)

    async def _extract_facts_llm(
        self,
        user_msg: str,
        agent_response: str,
    ) -> list[str]:
        """Extract facts using LLM with prompts/memory_extract.md.

        Returns:
            List of fact strings, or empty list on failure.
        """
        prompt_path = Path(self.markdown._memory_dir).parent / "prompts" / "memory_extract.md"
        if not prompt_path.exists():
            logger.debug("memory_extract.md not found, skipping LLM extraction")
            return []

        try:
            system = prompt_path.read_text(encoding="utf-8")
            msgs = [CanonicalMessage(
                role="user",
                content=(
                    f"## Conversation Turn\n\n"
                    f"**User**: {user_msg}\n\n"
                    f"**Assistant**: {agent_response[:500]}"
                ),
            )]

            response = await self._llm_client.chat(messages=msgs, system=system)  # type: ignore[union-attr]

            facts = []
            if response.content:
                for line in response.content.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("- "):
                        fact = line[2:].strip()
                        if fact and 3 < len(fact) < 200:
                            facts.append(fact)
            return facts

        except Exception as e:
            logger.warning("LLM fact extraction failed, falling back to heuristic: %s", e)
            return []

    @staticmethod
    def _extract_facts_heuristic(user_msg: str) -> list[str]:
        """Heuristic fact extraction — fallback when LLM is unavailable.

        Detects patterns for: name, location, occupation, preferences.
        """
        facts: list[str] = []
        lower = user_msg.lower()

        # Name patterns
        for pattern in ["my name is ", "i'm ", "call me "]:
            if pattern in lower:
                idx = lower.index(pattern) + len(pattern)
                name = user_msg[idx:].split(".")[0].split(",")[0].strip()
                if name and len(name) < 50:
                    facts.append(f"User's name might be: {name}")
                    break

        # Location patterns
        for pattern in ["i live in ", "i'm from ", "i am from ", "i'm based in "]:
            if pattern in lower:
                idx = lower.index(pattern) + len(pattern)
                location = user_msg[idx:].split(".")[0].split(",")[0].strip()
                if location and len(location) < 100:
                    facts.append(f"User might live in: {location}")
                    break

        # Occupation patterns
        for pattern in ["i work as ", "i am a ", "my job is "]:
            if pattern in lower:
                idx = lower.index(pattern) + len(pattern)
                occupation = user_msg[idx:].split(".")[0].split(",")[0].strip()
                if occupation and len(occupation) < 100:
                    facts.append(f"User might work as: {occupation}")
                    break

        # Preference patterns
        for pattern in ["i prefer ", "i like ", "i love "]:
            if pattern in lower:
                idx = lower.index(pattern) + len(pattern)
                preference = user_msg[idx:].split(".")[0].split(",")[0].strip()
                if preference and len(preference) < 100:
                    facts.append(f"User preference: {preference}")
                    break

        return facts
