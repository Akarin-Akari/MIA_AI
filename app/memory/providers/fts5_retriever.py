"""FTS5-based full-text retriever — Layer 2 RAG implementation.

Uses SQLite FTS5 virtual table for keyword-based full-text search
across indexed conversation turns. Zero external dependencies —
FTS5 is built into SQLite.

Satisfies the Retriever Protocol defined in memory/retriever.py.
"""

from __future__ import annotations

import logging
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_FTS5_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    doc_id UNINDEXED,
    content,
    tokenize='unicode61'
);
"""


class FTS5Retriever:
    """Full-text search retriever backed by SQLite FTS5.

    Uses the same db_path as SQLiteStore — shares one database file.
    FTS5 provides BM25 ranking out of the box via the rank column.

    CRITICAL: initialize() must be called before any add/search operations.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        """Create FTS5 virtual table if it doesn't exist."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_FTS5_DDL)
            await db.commit()
        logger.info("FTS5 retriever initialized at %s", self._db_path)

    async def add(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Index a document for full-text search.

        Args:
            doc_id: Document identifier (e.g., conversation_id).
            text: Full text content to index.
            metadata: Ignored in FTS5 implementation.
        """
        if not text or not text.strip():
            return
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO docs_fts (doc_id, content) VALUES (?, ?)",
                (doc_id, text),
            )
            await db.commit()

    async def search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search indexed documents using FTS5 MATCH + BM25 ranking.

        Args:
            query: Natural language search query.
            limit: Maximum number of results.

        Returns:
            List of result dicts: {"doc_id", "text", "score"}.
            Empty list if query is empty or no matches found.
        """
        if not query or not query.strip():
            return []

        safe_query = self._escape_fts5(query)
        if not safe_query:
            return []

        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT doc_id, content, rank "
                    "FROM docs_fts WHERE docs_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (safe_query, limit),
                )
                rows = await cursor.fetchall()
                return [
                    {
                        "doc_id": row["doc_id"],
                        "text": row["content"],
                        "score": -row["rank"],  # FTS5 rank is negative (lower = better)
                    }
                    for row in rows
                ]
        except Exception as e:
            # FTS5 query syntax errors should not crash the agent
            logger.warning("FTS5 search failed (non-fatal): %s", e)
            return []

    @staticmethod
    def _escape_fts5(query: str) -> str:
        """Escape query for safe FTS5 MATCH syntax.

        Splits into words, quotes each term, joins with OR
        for broad matching. Limits to 10 terms to prevent abuse.
        """
        words = query.split()
        if not words:
            return ""
        # Quote each word to escape FTS5 special characters
        safe_terms = [f'"{w}"' for w in words[:10] if w.strip()]
        if not safe_terms:
            return ""
        return " OR ".join(safe_terms)
