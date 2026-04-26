"""Retriever interface with NoOp default.

Defines a Protocol for document retrieval (RAG). Concrete implementations
(OpenAI embeddings, Chroma, etc.) go in memory/providers/ during Layer 2.
"""

from __future__ import annotations

from typing import Any, Protocol


class Retriever(Protocol):
    """Protocol for document retrieval (RAG).

    Concrete implementations are added in Layer 2 under memory/providers/.
    """

    async def add(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        """Add a document to the retrieval index."""
        ...

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search for relevant documents.

        Returns:
            List of result dicts with at least {"text": str, "score": float}.
        """
        ...


class NoOpRetriever:
    """Default retriever that does nothing.

    Used in Layer 1 when RAG is not enabled. Satisfies the Retriever Protocol
    with no-op implementations.
    """

    async def add(self, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        """No-op: document not stored."""
        pass

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """No-op: always returns empty results."""
        return []
