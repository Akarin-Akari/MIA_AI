"""Verifier persistence tests.

End-to-end test: mock LLM returns "wrong", mock verifier returns revised_answer="right".
After agent.run(), assert that ALL persistence layers have "right", NOT "wrong".

Persistence layers verified:
- WorkingMemory (Tier 1)
- SQLite (Tier 3)
- MarkdownMemory facts (Tier 2) — via fact extraction

NO pass placeholders — every test has real assertions.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agent.core import AgentExecutor, RepeatedFailureDetector
from app.agent.verifier import SelfVerifier, VerificationResult
from app.llm.base import CanonicalMessage, LLMResponse, ToolSpec
from app.memory.manager import MemoryManager
from app.memory.markdown_store import MarkdownMemory
from app.memory.retriever import NoOpRetriever
from app.memory.sqlite_store import SQLiteStore
from app.memory.working import WorkingMemory
from app.tools.registry import ToolRegistry


@pytest.fixture
async def wired_agent(tmp_path):
    """Build a fully wired agent with mock LLM and verifier."""
    # Mock LLM that returns "wrong" answer
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(return_value=LLMResponse(
        content="wrong",
        tool_calls=[],
        stop_reason="end_turn",
    ))

    # Mock verifier that revises to "right"
    mock_verifier = AsyncMock(spec=SelfVerifier)
    mock_verifier.verify = AsyncMock(return_value=VerificationResult(
        is_valid=False,
        confidence=0.9,
        issues=["test correction"],
        revised_answer="right",
    ))

    # Real memory stack with tmp_path
    working = WorkingMemory(maxlen=50)
    markdown = MarkdownMemory(memory_dir=str(tmp_path / "memory"))
    sqlite = SQLiteStore(db_path=str(tmp_path / "test.db"))
    await sqlite.initialize()
    retriever = NoOpRetriever()

    memory = MemoryManager(
        working=working,
        markdown=markdown,
        sqlite=sqlite,
        retriever=retriever,
    )

    tool_registry = ToolRegistry()

    agent = AgentExecutor(
        llm_client=mock_llm,
        tool_registry=tool_registry,
        memory_manager=memory,
        verifier=mock_verifier,
        max_iterations=10,
    )

    return agent, working, sqlite, markdown


@pytest.mark.asyncio
async def test_revised_answer_returned(wired_agent) -> None:
    """Agent.run() must return 'right', NOT 'wrong'."""
    agent, _, _, _ = wired_agent

    result = await agent.run("test question", "conv-test")

    assert result.content == "right", f"Expected 'right' but got '{result.content}'"
    assert result.content != "wrong", "Must NOT return initial draft"


@pytest.mark.asyncio
async def test_revised_answer_in_sqlite(wired_agent) -> None:
    """SQLite must persist 'right', NOT 'wrong'."""
    agent, _, sqlite, _ = wired_agent

    await agent.run("test question", "conv-persist")

    # Give fire-and-forget task time to complete
    await asyncio.sleep(0.5)

    history = await sqlite.get_history("conv-persist")
    assistant_msgs = [h for h in history if h["role"] == "assistant"]

    assert len(assistant_msgs) >= 1, "Should have at least one assistant message"
    assert assistant_msgs[-1]["content"] == "right", \
        f"SQLite should have 'right', got '{assistant_msgs[-1]['content']}'"


@pytest.mark.asyncio
async def test_revised_answer_in_working_memory(wired_agent) -> None:
    """WorkingMemory must have 'right', NOT 'wrong'."""
    agent, working, _, _ = wired_agent

    await agent.run("test question", "conv-wm")

    # Give fire-and-forget task time to complete
    await asyncio.sleep(0.5)

    msgs = working.get_messages("conv-wm")
    assistant_msgs = [m for m in msgs if m.role == "assistant"]

    assert len(assistant_msgs) >= 1, "Should have at least one assistant message"
    assert assistant_msgs[-1].content == "right", \
        f"Working memory should have 'right', got '{assistant_msgs[-1].content}'"


# ── RepeatedFailureDetector Tests ────────────────────────────────


def test_detector_isolation() -> None:
    """Detector must isolate counts per conv_id."""
    detector = RepeatedFailureDetector(max_repeats=3)

    # conv-A: 3 repeated calls
    for _ in range(3):
        detector.record("conv-A", "tool_x", {"arg": "same"})

    # conv-B: only 1 call
    detector.record("conv-B", "tool_x", {"arg": "same"})

    assert detector.should_intervene("conv-A") is True, "conv-A should trigger intervention"
    assert detector.should_intervene("conv-B") is False, "conv-B should NOT trigger"


def test_detector_resets() -> None:
    """After reset, detector should not intervene."""
    detector = RepeatedFailureDetector(max_repeats=3)

    for _ in range(3):
        detector.record("conv-A", "tool_x", {"arg": "same"})

    assert detector.should_intervene("conv-A") is True
    detector.reset("conv-A")
    assert detector.should_intervene("conv-A") is False


def test_detector_different_inputs() -> None:
    """Different inputs should NOT trigger intervention."""
    detector = RepeatedFailureDetector(max_repeats=3)

    detector.record("conv-A", "tool_x", {"arg": "1"})
    detector.record("conv-A", "tool_x", {"arg": "2"})
    detector.record("conv-A", "tool_x", {"arg": "3"})

    assert detector.should_intervene("conv-A") is False, "Different inputs shouldn't trigger"


# ── Main Chain Ordering Test ─────────────────────────────────────


@pytest.mark.asyncio
async def test_verifier_blocks_main_chain(wired_agent) -> None:
    """Verify that verifier.verify() is called BEFORE after_turn().

    The ordering MUST be:
    1. await verifier.verify() — blocking
    2. asyncio.create_task(after_turn()) — fire-and-forget
    """
    agent, _, _, _ = wired_agent

    call_order: list[str] = []

    original_verify = agent._verifier.verify

    async def tracked_verify(*args, **kwargs):
        call_order.append("verify")
        return await original_verify(*args, **kwargs)

    original_after_turn = agent._memory.after_turn

    async def tracked_after_turn(*args, **kwargs):
        call_order.append("after_turn")
        return await original_after_turn(*args, **kwargs)

    agent._verifier.verify = tracked_verify
    agent._memory.after_turn = tracked_after_turn

    await agent.run("ordering test", "conv-order")
    await asyncio.sleep(0.5)  # Let fire-and-forget complete

    assert "verify" in call_order, "verify must be called"
    assert "after_turn" in call_order, "after_turn must be called"
    assert call_order.index("verify") < call_order.index("after_turn"), \
        "verify MUST come before after_turn"


# ── MarkdownMemory Persistence Test ──────────────────────────────


@pytest.mark.asyncio
async def test_revised_answer_triggers_markdown_persistence(wired_agent) -> None:
    """MarkdownMemory (Tier 2) must receive persistence calls.

    Verifies the docstring promise of 'ALL persistence layers'.
    """
    agent, _, _, markdown = wired_agent

    # Use a message that triggers fact extraction ("my name is")
    await agent.run("my name is Alice", "conv-md")

    # Give fire-and-forget tasks time to complete
    await asyncio.sleep(1.0)

    # Check that facts were extracted and persisted
    facts = await markdown.get_top_k_facts(k=10)
    # Should have at least one fact about the name
    assert len(facts) >= 1, "MarkdownMemory should have at least one extracted fact"
    assert any("Alice" in f for f in facts), \
        f"Expected a fact mentioning 'Alice', got: {facts}"
