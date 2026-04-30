"""Embedding provider abstraction for vector search.

Adapted from akari-mem-mcp's proven dual-engine architecture.
Supports two modes:
1. LOCAL  — sentence-transformers (BGE-M3, etc.), best quality, lazy-load
2. API    — OpenAI-compatible embedding API, zero local resources

All providers are synchronous internally — the HybridRetriever wraps
calls with asyncio.to_thread() to avoid Event Loop blocking.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding vector dimension."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier string."""
        ...


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local embedding via sentence-transformers. Lazy-loads on first call.

    Default model: BAAI/bge-m3 (1024d, multilingual, SOTA quality).
    First call takes ~15s for model loading, subsequent calls are fast.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        cache_dir: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir or os.environ.get(
            "AKARI_MODEL_CACHE", "F:/models"
        )
        self._model = None
        self._dim: int | None = None

    def _load(self) -> None:
        if self._model is None:
            logger.info("Loading local embedding model: %s ...", self._model_name)
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed. "
                    "Run: pip install sentence-transformers"
                )
            self._model = SentenceTransformer(
                self._model_name, cache_folder=self._cache_dir
            )
            self._dim = self._model.get_sentence_embedding_dimension()
            logger.info("Embedding model loaded: dim=%d", self._dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        embeddings = self._model.encode(texts, normalize_embeddings=True)  # type: ignore[union-attr]
        return embeddings.tolist()

    @property
    def dimension(self) -> int:
        if self._dim is None:
            self._load()
        return self._dim  # type: ignore[return-value]

    @property
    def model_name(self) -> str:
        return self._model_name


class APIEmbeddingProvider(EmbeddingProvider):
    """Online embedding via OpenAI-compatible API.

    Works with: OpenAI, Azure OpenAI, Ollama, LiteLLM, vLLM, etc.
    Uses urllib directly to avoid extra dependencies.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model_name: str = "text-embedding-3-small",
        dimension: int = 1536,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        import urllib.request

        payload = json.dumps({
            "model": self._model_name,
            "input": texts,
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

        # OpenAI format: {"data": [{"embedding": [...], "index": 0}, ...]}
        sorted_data = sorted(result["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in sorted_data]

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name


class ChromaEmbeddingAdapter:
    """Adapter wrapping EmbeddingProvider into ChromaDB's EmbeddingFunction protocol.

    Supports both ChromaDB v0.x (__call__) and v1.x (embed_query/embed_documents).
    """

    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    def __call__(self, input: list[str]) -> list[list[float]]:
        return self.provider.embed(input)

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        """ChromaDB v1.x: embed documents for storage."""
        return self.provider.embed(documents)

    def embed_query(self, input: str) -> list[float]:
        """ChromaDB v1.x: embed a single query for search."""
        return self.provider.embed([input])[0]

    def name(self) -> str:
        """Required by ChromaDB to identify the embedding function."""
        return f"miao_{self.provider.model_name}"


def create_embedding_provider(
    mode: str = "local",
    model: str = "",
    api_url: str = "",
    api_key: str = "",
    dimension: int = 1536,
    cache_dir: str = "",
) -> EmbeddingProvider:
    """Factory: create embedding provider from config.

    Args:
        mode: "local" or "api"
        model: Model name (auto-detected from mode if empty)
        api_url: OpenAI-compatible endpoint (required for api mode)
        api_key: API key (required for api mode)
        dimension: Vector dimension (api mode only)
        cache_dir: Model cache directory (local mode only)
    """
    if mode == "local":
        return LocalEmbeddingProvider(
            model_name=model or "BAAI/bge-m3",
            cache_dir=cache_dir or None,
        )
    elif mode == "api":
        if not api_url:
            raise ValueError("embedding_api_url is required for api mode")
        return APIEmbeddingProvider(
            api_url=api_url,
            api_key=api_key,
            model_name=model or "text-embedding-3-small",
            dimension=dimension,
        )
    else:
        raise ValueError(f"Unknown embedding mode: {mode}. Use 'local' or 'api'.")
