"""Markdown memory store — Tier 2: persistent file-based memory.

Manages:
- profile.json: Structured user profile with metadata schema
- learned_facts.md: Append-only natural-language facts
- conversations/{conv_id}/summary.md: Per-conversation summaries

Safety guarantees:
- asyncio.Lock as INSTANCE ATTRIBUTE (not local to methods)
- Atomic write: {path}.tmp → os.replace() for crash safety
- Single-user assumption (see README for multi-user warning)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)


class MarkdownMemory:
    """File-based persistent memory with lock protection and atomic writes.

    CRITICAL SAFETY:
    - self._lock is an INSTANCE attribute created in __init__
      (NOT per-request, NOT module-level — those patterns are broken)
    - All writes go through _atomic_write() which uses {path}.tmp + os.replace()
    - asyncio.Lock only protects single-process; multi-worker needs filelock

    Attributes:
        _memory_dir: Base directory for all memory files.
        _lock: asyncio.Lock instance for concurrent write protection.
    """

    def __init__(self, memory_dir: str) -> None:
        self._memory_dir = Path(memory_dir)
        # CRITICAL: Lock MUST be instance attribute — local Lock is useless
        self._lock = asyncio.Lock()
        self._memory_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _profile_path(self) -> Path:
        return self._memory_dir / "profile.json"

    @property
    def _facts_path(self) -> Path:
        return self._memory_dir / "learned_facts.md"

    # ── Atomic Write ─────────────────────────────────────────────────

    async def _atomic_write(self, path: Path, content: str) -> None:
        """Write content atomically using tmp + os.replace pattern.

        Process:
        1. Write to {path}.tmp
        2. os.replace({path}.tmp, {path}) — atomic on POSIX, near-atomic on Windows

        If step 1 fails: original file untouched.
        If step 2 fails: original file untouched, .tmp may remain.

        Args:
            path: Target file path.
            content: Content to write.
        """
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                await f.write(content)
            os.replace(str(tmp_path), str(path))
        except Exception:
            # Clean up tmp file on failure, original stays intact
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise

    # ── Profile Operations ───────────────────────────────────────────

    async def get_profile(self) -> dict[str, Any]:
        """Read profile.json.

        Returns:
            Profile dict with metadata schema values,
            or empty dict if file doesn't exist.
        """
        if not self._profile_path.exists():
            return {}
        try:
            async with aiofiles.open(self._profile_path, "r", encoding="utf-8") as f:
                content = await f.read()
            return json.loads(content)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to read profile: %s", e)
            return {}

    async def update_profile(self, key: str, value: dict[str, Any]) -> None:
        """Update a profile field with metadata schema.

        CRITICAL: value MUST be in metadata form:
        {
            "value": <actual_value>,
            "type": "number" | "date" | "enum" | "text",
            "tolerance"?: <number>,
            "values"?: [<enum_values>]
        }

        Flat KV storage (e.g., update_profile("age", 28)) is FORBIDDEN —
        Stage 2 verifier needs type info to function.

        Args:
            key: Profile field name.
            value: Metadata-schema value dict.
        """
        async with self._lock:
            profile = await self.get_profile()
            profile[key] = value
            await self._atomic_write(
                self._profile_path,
                json.dumps(profile, ensure_ascii=False, indent=2),
            )
            logger.info("Updated profile key: %s", key)

    # ── Facts Operations ─────────────────────────────────────────────

    async def append_fact(self, fact: str) -> None:
        """Append a fact to learned_facts.md.

        Args:
            fact: Natural-language fact string.
        """
        async with self._lock:
            # Read existing content
            existing = ""
            if self._facts_path.exists():
                async with aiofiles.open(self._facts_path, "r", encoding="utf-8") as f:
                    existing = await f.read()

            # Append new fact
            if existing and not existing.endswith("\n"):
                existing += "\n"
            new_content = existing + f"- {fact}\n"

            await self._atomic_write(self._facts_path, new_content)
            logger.debug("Appended fact: %s", fact[:50])

    async def get_top_k_facts(self, k: int = 5) -> list[str]:
        """Get the most recent k facts.

        Args:
            k: Number of facts to return.

        Returns:
            List of fact strings (most recent last).
        """
        if not self._facts_path.exists():
            return []
        try:
            async with aiofiles.open(self._facts_path, "r", encoding="utf-8") as f:
                content = await f.read()
            lines = [
                line.lstrip("- ").strip()
                for line in content.strip().split("\n")
                if line.strip() and line.strip().startswith("-")
            ]
            return lines[-k:]  # Most recent k facts
        except OSError as e:
            logger.error("Failed to read facts: %s", e)
            return []

    # ── Summary Operations ───────────────────────────────────────────

    async def save_summary(self, conv_id: str, summary: str) -> None:
        """Save a conversation summary (write-once).

        Args:
            conv_id: Conversation identifier.
            summary: Summary text.
        """
        conv_dir = self._memory_dir / "conversations" / conv_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        summary_path = conv_dir / "summary.md"

        async with self._lock:
            await self._atomic_write(summary_path, summary)
            logger.info("Saved summary for conv_id=%s", conv_id)
