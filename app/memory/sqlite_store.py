"""SQLite memory store — Tier 3: persistent structured storage.

Uses aiosqlite for async database operations. Stores conversation messages
and extracted facts with ISO 8601 timestamps.

NEVER use :memory: database in tests with multiple connections — it doesn't
share data across connections. Use tmp_path file DB instead.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# DDL from scaffold v3.2
_MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL
);
"""
_MESSAGES_INDEX = "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);"

_FACTS_DDL = """
CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    fact            TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""
_FACTS_INDEX = "CREATE INDEX IF NOT EXISTS idx_facts_conv ON facts(conversation_id);"


class SQLiteStore:
    """Async SQLite store for messages and facts.

    Attributes:
        _db_path: Path to SQLite database file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_MESSAGES_DDL)
            await db.execute(_MESSAGES_INDEX)
            await db.execute(_FACTS_DDL)
            await db.execute(_FACTS_INDEX)
            await db.commit()
        logger.info("SQLite initialized at %s", self._db_path)

    async def save(
        self,
        conv_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Save a message to the messages table.

        Args:
            conv_id: Conversation identifier.
            role: Message role.
            content: Message content.
            metadata: Optional metadata dict (serialized to JSON).

        Returns:
            Inserted row ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT INTO messages (conversation_id, role, content, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conv_id, role, content, metadata_json, now),
            )
            await db.commit()
            row_id = cursor.lastrowid
            logger.debug("Saved message id=%s for conv=%s role=%s", row_id, conv_id, role)
            return row_id  # type: ignore[return-value]

    async def get_history(
        self,
        conv_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get conversation history.

        Args:
            conv_id: Conversation identifier.
            limit: Max messages to return.

        Returns:
            List of message dicts ordered by created_at.
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, conversation_id, role, content, metadata_json, created_at "
                "FROM messages WHERE conversation_id = ? "
                "ORDER BY created_at ASC LIMIT ?",
                (conv_id, limit),
            )
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # Deserialize metadata_json to match save() input contract
                try:
                    d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    d["metadata"] = {}
                results.append(d)
            return results

    async def keyword_search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Simple keyword search across messages.

        Uses LIKE for Layer 1. FTS5 can be added in Layer 2 if needed.

        Args:
            query: Search term.
            limit: Max results.

        Returns:
            List of matching message dicts.
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, conversation_id, role, content, metadata_json, created_at "
                "FROM messages WHERE content LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit),
            )
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                try:
                    d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    d["metadata"] = {}
                results.append(d)
            return results

    async def save_fact(self, conv_id: str, fact: str) -> int:
        """Save an extracted fact.

        Args:
            conv_id: Source conversation.
            fact: Fact text.

        Returns:
            Inserted row ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "INSERT INTO facts (conversation_id, fact, created_at) VALUES (?, ?, ?)",
                (conv_id, fact, now),
            )
            await db.commit()
            return cursor.lastrowid  # type: ignore[return-value]
