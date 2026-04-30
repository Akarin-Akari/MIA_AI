"""Reranker abstraction for two-stage retrieval.

Adapted from akari-mem-mcp. Re-scores candidate documents with a
cross-encoder model for higher precision after initial retrieval.

Supports 3 modes:
1. LOCAL — cross-encoder model (e.g., BAAI/bge-reranker-v2-m3), lazy-load
2. API   — Jina/Cohere rerank API
3. NONE  — disabled, pass-through

All providers are synchronous internally — the HybridRetriever wraps
calls with asyncio.to_thread() to avoid Event Loop blocking.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Reranker(ABC):
    """Abstract base for rerankers."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Re-score and re-order documents by relevance to query.

        Args:
            query: The search query.
            documents: List of result dicts (must have 'text' key).
            top_k: Number of top results to return.

        Returns:
            Reranked list with 'rerank_score' added to each dict.
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...


class LocalReranker(Reranker):
    """Local cross-encoder reranker via sentence-transformers.

    Default model: BAAI/bge-reranker-v2-m3 (multilingual, SOTA).
    Lazy-loads on first call (~5s model loading).
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        cache_dir: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir or os.environ.get("HF_HOME", None)
        self._model = None

    def _load(self) -> None:
        if self._model is None:
            logger.info("Loading reranker model: %s ...", self._model_name)
            try:
                from sentence_transformers import CrossEncoder
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed. "
                    "Run: pip install sentence-transformers"
                )
            self._model = CrossEncoder(
                self._model_name, cache_folder=self._cache_dir
            )
            logger.info("Reranker model loaded.")

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        self._load()
        if not documents:
            return []

        # Build query-document pairs
        pairs = [(query, doc.get("text", "")) for doc in documents]

        # Score all pairs
        scores = self._model.predict(pairs)  # type: ignore[union-attr]

        # Attach scores and sort
        for i, doc in enumerate(documents):
            doc["rerank_score"] = float(scores[i])

        reranked = sorted(documents, key=lambda d: d["rerank_score"], reverse=True)
        return reranked[:top_k]

    @property
    def model_name(self) -> str:
        return self._model_name


class APIReranker(Reranker):
    """Online reranker via Jina/Cohere-compatible API.

    Jina:   https://api.jina.ai/v1/rerank
    Cohere: https://api.cohere.ai/v1/rerank
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model_name: str = "jina-reranker-v2-base-multilingual",
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        import urllib.request

        doc_texts = [doc.get("text", "") for doc in documents]

        payload = json.dumps({
            "model": self._model_name,
            "query": query,
            "documents": doc_texts,
            "top_n": top_k,
        }).encode("utf-8")

        req = urllib.request.Request(
            self._api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())

        # API returns: {"results": [{"index": 0, "relevance_score": 0.95}, ...]}
        reranked = []
        for item in result.get("results", []):
            idx = item["index"]
            doc = documents[idx].copy()
            doc["rerank_score"] = item.get("relevance_score", 0.0)
            reranked.append(doc)

        return reranked

    @property
    def model_name(self) -> str:
        return self._model_name


class NoReranker(Reranker):
    """Pass-through: no reranking, return as-is."""

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return documents[:top_k]

    @property
    def model_name(self) -> str:
        return "none"


def create_reranker(
    mode: str = "none",
    model: str = "",
    api_url: str = "",
    api_key: str = "",
    cache_dir: str = "",
) -> Reranker:
    """Factory: create reranker from config.

    Args:
        mode: "local", "api", or "none"
        model: Model name (auto-detected from mode if empty)
        api_url: Rerank API endpoint (required for api mode)
        api_key: API key (required for api mode)
        cache_dir: Model cache directory (local mode only)
    """
    if mode == "local":
        return LocalReranker(
            model_name=model or "BAAI/bge-reranker-v2-m3",
            cache_dir=cache_dir or None,
        )
    elif mode == "api":
        if not api_url:
            raise ValueError("rerank_api_url is required for api mode")
        return APIReranker(
            api_url=api_url,
            api_key=api_key,
            model_name=model or "jina-reranker-v2-base-multilingual",
        )
    else:
        return NoReranker()
