"""Hybrid retriever: Vector + FTS5 + RRF fusion + optional Rerank.

Dual-engine architecture adapted from akari-mem-mcp:
- Write: sync to both FTS5 (keyword index) and ChromaDB (vector index)
- Search: parallel recall from both engines → RRF fusion → optional rerank

CRITICAL: All ChromaDB/embedding/rerank operations are synchronous internally.
This module wraps them with asyncio.to_thread() to prevent Event Loop blocking.
This is a P1 safety requirement identified during scaffold review.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite

from app.memory.providers.embeddings import ChromaEmbeddingAdapter, EmbeddingProvider
from app.memory.providers.reranker import NoReranker, Reranker

logger = logging.getLogger(__name__)

_FTS5_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    doc_id UNINDEXED,
    content,
    tokenize='unicode61'
);
"""


class HybridRetriever:
    """Hybrid vector + keyword retriever with RRF fusion and optional rerank.

    Implements the Retriever Protocol (add + search).

    Search pipeline:
        Stage 1a: ChromaDB vector search (semantic recall)
        Stage 1b: FTS5 keyword search (exact recall)
        Stage 2:  RRF fusion (merge & deduplicate)
        Stage 3:  Reranker re-scores (if enabled)

    All blocking I/O (embedding, ChromaDB, reranker) is offloaded
    to threads via asyncio.to_thread().

    Attributes:
        _db_path: SQLite database path (shared with SQLiteStore).
        _provider: Embedding provider for vector operations.
        _reranker: Reranker for Stage 3 (NoReranker = disabled).
        _collection: ChromaDB collection for vector storage.
    """

    def __init__(
        self,
        db_path: str,
        embedding_provider: EmbeddingProvider,
        reranker: Reranker | None = None,
        chroma_dir: str = "",
    ) -> None:
        self._db_path = db_path
        self._provider = embedding_provider
        self._reranker = reranker or NoReranker()
        self._chroma_dir = chroma_dir or (db_path.rsplit(".", 1)[0] + "_chroma")
        self._collection = None
        self._chroma_client = None

    async def initialize(self) -> None:
        """Initialize FTS5 table and ChromaDB collection.

        MUST be called before any add/search operations.
        ChromaDB init is offloaded to thread (blocking I/O).
        """
        # FTS5 table
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_FTS5_DDL)
            await db.commit()

        # ChromaDB collection (blocking — offload to thread)
        await asyncio.to_thread(self._init_chroma)

        rerank_info = f" | rerank={self._reranker.model_name}" if self._reranker.model_name != "none" else ""
        logger.info(
            "HybridRetriever ready: %s | embedding=%s (%dd)%s",
            self._db_path,
            self._provider.model_name,
            self._provider.dimension,
            rerank_info,
        )

    def _init_chroma(self) -> None:
        """Initialize ChromaDB — runs in thread."""
        import chromadb

        self._chroma_client = chromadb.PersistentClient(path=self._chroma_dir)
        adapter = ChromaEmbeddingAdapter(self._provider)

        self._collection = self._chroma_client.get_or_create_collection(
            name="miao_agent_docs",
            embedding_function=adapter,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB collection ready: %d documents", self._collection.count())

    # ── Write Operations ─────────────────────────────────────────────

    async def add(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Index a document in both FTS5 and ChromaDB.

        Args:
            doc_id: Document identifier.
            text: Full text content to index.
            metadata: Optional metadata for ChromaDB.
        """
        if not text or not text.strip():
            return

        # FTS5 (async native)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO docs_fts (doc_id, content) VALUES (?, ?)",
                (doc_id, text),
            )
            await db.commit()

        # ChromaDB (blocking — offload to thread)
        await asyncio.to_thread(self._chroma_add, doc_id, text, metadata)

    def _chroma_add(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        """Add to ChromaDB — runs in thread."""
        if self._collection is None:
            return
        # ChromaDB requires unique IDs; use hash to avoid collisions
        chroma_id = f"doc_{hash(doc_id + text) & 0xFFFFFFFF:08x}"
        self._collection.add(
            ids=[chroma_id],
            documents=[text],
            metadatas=[{"doc_id": doc_id, **(metadata or {})}],
        )

    # ── Search Operations ────────────────────────────────────────────

    async def search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Hybrid search: vector + keyword + RRF fusion + optional rerank.

        Args:
            query: Natural language search query.
            limit: Maximum number of results.

        Returns:
            List of result dicts: {"doc_id", "text", "score"}.
        """
        if not query or not query.strip():
            return []

        # Fetch more candidates for better fusion/rerank quality
        fetch_k = limit * 3 if self._reranker.model_name != "none" else limit * 2
        fetch_k = max(fetch_k, 10)

        # Stage 1a + 1b: parallel recall from both engines
        vector_task = asyncio.to_thread(self._vector_search, query, fetch_k)
        keyword_task = self._keyword_search(query, fetch_k)

        vector_results, keyword_results = await asyncio.gather(
            vector_task, keyword_task, return_exceptions=True,
        )

        # Graceful degradation: if either fails, use the other
        if isinstance(vector_results, Exception):
            logger.warning("Vector search failed (non-fatal): %s", vector_results)
            vector_results = []
        if isinstance(keyword_results, Exception):
            logger.warning("Keyword search failed (non-fatal): %s", keyword_results)
            keyword_results = []

        # Stage 2: RRF fusion
        merged = self._rrf_fusion(vector_results, keyword_results, k=60)

        # Stage 3: Rerank (if enabled, offload to thread)
        if self._reranker.model_name != "none" and merged:
            try:
                merged = await asyncio.to_thread(
                    self._reranker.rerank, query, merged, limit,
                )
                logger.debug("Reranked → %d results", len(merged))
            except Exception as e:
                logger.warning("Rerank failed (non-fatal): %s", e)

        return merged[:limit]

    def _vector_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """ChromaDB vector search — runs in thread."""
        if self._collection is None or self._collection.count() == 0:
            return []

        try:
            query_vec = self._provider.embed([query])[0]
            results = self._collection.query(
                query_embeddings=[query_vec],
                n_results=min(limit, self._collection.count()),
            )
        except Exception as e:
            logger.warning("ChromaDB query failed: %s", e)
            return []

        if not results["ids"] or not results["ids"][0]:
            return []

        vector_results = []
        for i, chroma_id in enumerate(results["ids"][0]):
            doc_text = results["documents"][0][i] if results["documents"] else ""
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else None

            vector_results.append({
                "doc_id": meta.get("doc_id", chroma_id),
                "text": doc_text,
                "score": round(1.0 - distance, 4) if distance is not None else 0.0,
                "_source": "vector",
            })

        return vector_results

    async def _keyword_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """FTS5 keyword search — async native."""
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
                        "score": -row["rank"],
                        "_source": "keyword",
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.warning("FTS5 search failed (non-fatal): %s", e)
            return []

    @staticmethod
    def _escape_fts5(query: str) -> str:
        """Escape query for safe FTS5 MATCH syntax."""
        words = query.split()
        if not words:
            return ""
        safe_terms = [f'"{w}"' for w in words[:10] if w.strip()]
        return " OR ".join(safe_terms) if safe_terms else ""

    @staticmethod
    def _rrf_fusion(
        vector_results: list[dict[str, Any]],
        keyword_results: list[dict[str, Any]],
        k: int = 60,
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion: merge two ranked lists.

        RRF score = sum(1 / (k + rank)) for each list the item appears in.
        Higher score = more relevant. Deduplicates by text content hash.
        """
        scores: dict[int, float] = {}
        docs: dict[int, dict[str, Any]] = {}

        def _text_hash(doc: dict[str, Any]) -> int:
            return hash(doc.get("text", ""))

        # Score vector results
        for rank, doc in enumerate(vector_results):
            key = _text_hash(doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            docs[key] = doc

        # Score keyword results
        for rank, doc in enumerate(keyword_results):
            key = _text_hash(doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in docs:
                docs[key] = doc

        # Sort by RRF score descending
        ranked_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        result = []
        for key in ranked_keys:
            d = docs[key].copy()
            d["score"] = round(scores[key], 6)
            d.pop("_source", None)
            result.append(d)

        return result
