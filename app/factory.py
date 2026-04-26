"""DI factory — explicit dependency injection wiring.

build_agent() assembles all components based on Settings and returns
a fully wired AgentExecutor. NO module-level mutable globals.

This is the ONLY place where concrete implementations are selected.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.agent.core import AgentExecutor
from app.agent.verifier import SelfVerifier
from app.config import Settings
from app.memory.manager import MemoryManager
from app.memory.markdown_store import MarkdownMemory
from app.memory.retriever import NoOpRetriever
from app.memory.sqlite_store import SQLiteStore
from app.memory.working import WorkingMemory
from app.tools.dummy import DummyTool
from app.tools.notes import NoteTool
from app.tools.registry import ToolRegistry
from app.tools.weather import WeatherTool

logger = logging.getLogger(__name__)


async def build_agent(settings: Settings) -> AgentExecutor:
    """Build and wire a complete AgentExecutor from settings.

    This function is the single assembly point for all components.
    All dependencies are explicitly injected — no hidden globals.

    Args:
        settings: Application settings.

    Returns:
        Fully wired AgentExecutor ready for use.
    """
    # ── LLM Client ───────────────────────────────────────────────
    model = settings.resolved_model()

    if settings.llm_provider == "anthropic":
        from app.llm.anthropic_client import AnthropicClient
        llm_client = AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=model,
            max_tokens=settings.llm_max_tokens,
        )
    elif settings.llm_provider == "openai":
        from app.llm.openai_client import OpenAIClient
        llm_client = OpenAIClient(
            api_key=settings.openai_api_key,
            model=model,
            base_url=settings.openai_base_url,
        )
    else:
        supported = ", ".join(sorted(["anthropic", "openai"]))
        raise ValueError(
            f"Unsupported LLM provider: '{settings.llm_provider}'. "
            f"Supported providers: [{supported}]. "
            f"Set LLM_PROVIDER env var or llm_provider in .env."
        )

    logger.info("LLM Client: %s (model=%s)", settings.llm_provider, model)

    # ── Tool Registry ────────────────────────────────────────────
    tool_registry = ToolRegistry()
    tool_registry.register(DummyTool())
    tool_registry.register(WeatherTool())
    tool_registry.register(NoteTool(memory_dir=settings.memory_dir))

    # ── Memory Stack ─────────────────────────────────────────────
    # Ensure memory directory exists
    memory_dir = Path(settings.memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)

    # Ensure DB directory exists
    db_dir = Path(settings.db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    working = WorkingMemory(maxlen=settings.working_max_per_conv)
    markdown = MarkdownMemory(memory_dir=settings.memory_dir)
    sqlite = SQLiteStore(db_path=settings.db_path)
    await sqlite.initialize()

    # Retriever: NoOp by default, Layer 2 adds real implementations
    retriever = NoOpRetriever()

    memory_manager = MemoryManager(
        working=working,
        markdown=markdown,
        sqlite=sqlite,
        retriever=retriever,
    )

    # ── Self-Verifier ────────────────────────────────────────────
    verifier = SelfVerifier(
        llm_client=llm_client if settings.verification_enabled else None,
        sampling_rate=settings.verifier_sampling_rate,
        soft_fallback=settings.verifier_soft_fallback,
        enabled=settings.verification_enabled,
    )

    # ── Agent Executor ───────────────────────────────────────────
    agent = AgentExecutor(
        llm_client=llm_client,
        tool_registry=tool_registry,
        memory_manager=memory_manager,
        verifier=verifier,
        max_iterations=settings.max_iterations,
    )

    logger.info("Agent built successfully (provider=%s, model=%s)", settings.llm_provider, model)
    return agent
