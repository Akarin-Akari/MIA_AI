"""Mock search tool — simulated knowledge base search.

Provides a simulated knowledge base for searching topics.
In production, this would be replaced with a real web search API.

The tool supports fault injection via INJECT_FAILURE env var for
demonstrating error recovery during evaluation.
"""

from __future__ import annotations

import os
from typing import Any

from app.tools.base import BaseTool

# Simulated knowledge base with curated content
_KNOWLEDGE_BASE: dict[str, str] = {
    "llm prompt caching": (
        "## LLM Prompt Caching Best Practices (2024-2025)\n\n"
        "1. **Prefix Caching**: Cache common system prompts and few-shot examples. "
        "Anthropic's prompt caching reduces costs by up to 90% for repeated prefixes.\n"
        "2. **Semantic Caching**: Use embedding similarity to match semantically equivalent queries "
        "and return cached responses. Tools like GPTCache implement this pattern.\n"
        "3. **KV Cache Optimization**: Modern frameworks like vLLM use PagedAttention for "
        "efficient GPU memory management of KV caches.\n"
        "4. **Tiered Caching Strategy**: Use in-memory (Redis) for hot queries, disk for warm, "
        "and recompute for cold — similar to CPU cache hierarchy.\n"
        "5. **Cache Invalidation**: Set TTL based on content volatility. Static knowledge = long TTL, "
        "real-time data = short TTL or no cache.\n"
        "6. **Prompt Fingerprinting**: Hash normalized prompts (strip whitespace, lowercase) as cache keys "
        "to improve hit rates without exact match requirements."
    ),
    "agent engineering": (
        "## Agent Engineering Best Practices\n\n"
        "1. **ReAct Pattern**: Interleave Reasoning and Acting — let the LLM think before each tool call.\n"
        "2. **Tool Design**: Keep tools atomic, well-scoped, and with clear JSON Schema definitions.\n"
        "3. **Error Recovery**: Never hallucinate tool success — propagate errors back to the LLM.\n"
        "4. **Memory Architecture**: Use tiered memory (working + episodic + semantic) for context management.\n"
        "5. **Self-Verification**: Add deterministic post-tool checks before trusting results."
    ),
    "python async": (
        "## Python Async Best Practices\n\n"
        "1. Use `asyncio.to_thread()` for sync I/O operations to avoid blocking the event loop.\n"
        "2. Use `asyncio.Lock` for shared resource protection, but note it's single-process only.\n"
        "3. Prefer `asyncio.create_task()` for fire-and-forget background work.\n"
        "4. Use `aiofiles` for async file I/O and `aiosqlite` for async database access.\n"
        "5. Always handle `CancelledError` properly in long-running tasks."
    ),
    "rag retrieval augmented generation": (
        "## RAG (Retrieval-Augmented Generation)\n\n"
        "1. **Chunking Strategy**: Split documents into 256-512 token chunks with overlap.\n"
        "2. **Embedding Models**: Use models like text-embedding-3-small for cost-effective retrieval.\n"
        "3. **Hybrid Search**: Combine dense (vector) and sparse (BM25) retrieval for better recall.\n"
        "4. **Reranking**: Use cross-encoder rerankers to improve precision after initial retrieval.\n"
        "5. **Context Window Management**: Inject retrieved chunks into system prompt with clear delimiters."
    ),
}


class MockSearchTool(BaseTool):
    """Simulated knowledge base search tool.

    Searches a curated knowledge base for topics matching the query.
    Supports fault injection via constructor parameter for evaluation.
    """

    def __init__(self, inject_failure: bool = False) -> None:
        """Initialize MockSearchTool.

        Args:
            inject_failure: If True, tool will raise RuntimeError on execute.
        """
        self._inject_failure = inject_failure

    @property
    def name(self) -> str:
        return "mock_search"

    @property
    def description(self) -> str:
        return (
            "Search a knowledge base for information on a topic. "
            "Returns relevant articles and best practices. "
            "Use this when the user asks about technical topics, best practices, or research."
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — describe the topic you want to find information about",
                },
            },
            "required": ["query"],
        }

    def execute(self, query: str = "") -> str:
        """Search the knowledge base for matching content.

        This is intentionally SYNC to demonstrate asyncio.to_thread wrapping.

        Args:
            query: Search query string.

        Returns:
            Matching knowledge base content or a "no results" message.

        Raises:
            RuntimeError: If fault injection is enabled.
        """
        if self._inject_failure:
            raise RuntimeError(
                f"Injected failure for mock_search "
                f"(INJECT_FAILURE={os.environ.get('INJECT_FAILURE', '')})"
            )

        if not query:
            return "ERROR: Search query cannot be empty."

        query_lower = query.lower()
        results: list[str] = []

        for key, content in _KNOWLEDGE_BASE.items():
            # Simple keyword matching — production would use embeddings
            if any(word in key for word in query_lower.split()):
                results.append(content)

        if not results:
            return (
                f"No results found for '{query}'. "
                f"Available topics: {', '.join(_KNOWLEDGE_BASE.keys())}"
            )

        return "\n\n---\n\n".join(results)
