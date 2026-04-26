"""Memory isolation tests.

Tests conversation isolation, clear behavior, and deque truncation.
NO pass placeholders — every test has real assertions.
"""

from __future__ import annotations

import asyncio

import pytest

from app.llm.base import CanonicalMessage
from app.memory.markdown_store import MarkdownMemory
from app.memory.working import WorkingMemory


# ── Working Memory Isolation ─────────────────────────────────────


def test_conv_isolation(working_memory: WorkingMemory) -> None:
    """conv-A and conv-B must NOT pollute each other."""
    msg_a = CanonicalMessage(role="user", content="Hello from A")
    msg_b = CanonicalMessage(role="user", content="Hello from B")

    working_memory.append("conv-A", msg_a)
    working_memory.append("conv-B", msg_b)

    a_msgs = working_memory.get_messages("conv-A")
    b_msgs = working_memory.get_messages("conv-B")

    assert len(a_msgs) == 1
    assert len(b_msgs) == 1
    assert a_msgs[0].content == "Hello from A"
    assert b_msgs[0].content == "Hello from B"

    # They must be completely independent
    assert a_msgs[0].content != b_msgs[0].content


def test_clear_specific_conv(working_memory: WorkingMemory) -> None:
    """clear('conv-A') must NOT affect conv-B."""
    working_memory.append("conv-A", CanonicalMessage(role="user", content="A"))
    working_memory.append("conv-B", CanonicalMessage(role="user", content="B"))

    working_memory.clear("conv-A")

    assert len(working_memory.get_messages("conv-A")) == 0
    assert len(working_memory.get_messages("conv-B")) == 1
    assert working_memory.get_messages("conv-B")[0].content == "B"


def test_clear_all(working_memory: WorkingMemory) -> None:
    """clear(None) must clear all conversations."""
    working_memory.append("conv-A", CanonicalMessage(role="user", content="A"))
    working_memory.append("conv-B", CanonicalMessage(role="user", content="B"))

    working_memory.clear()

    assert len(working_memory.get_messages("conv-A")) == 0
    assert len(working_memory.get_messages("conv-B")) == 0


def test_deque_maxlen_truncation() -> None:
    """Messages beyond maxlen should be silently dropped (oldest first)."""
    wm = WorkingMemory(maxlen=3)

    for i in range(5):
        wm.append("conv-1", CanonicalMessage(role="user", content=f"msg-{i}"))

    msgs = wm.get_messages("conv-1")
    assert len(msgs) == 3
    # Oldest messages (0, 1) should be dropped
    assert msgs[0].content == "msg-2"
    assert msgs[1].content == "msg-3"
    assert msgs[2].content == "msg-4"


# ── Markdown Memory Lock Tests ───────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_profile_writes(markdown_memory: MarkdownMemory) -> None:
    """Concurrent update_profile calls must NOT corrupt profile.json.

    This test verifies that Lock is an instance attribute (shared across calls).
    If Lock were local to update_profile, concurrent writes would interleave
    and corrupt the JSON.
    """
    async def writer(key: str, value: str) -> None:
        for i in range(10):
            await markdown_memory.update_profile(
                key,
                {"value": f"{value}-{i}", "type": "text"},
            )

    # Launch concurrent writers
    await asyncio.gather(
        writer("field_a", "A"),
        writer("field_b", "B"),
    )

    # Profile must be valid JSON with both fields
    profile = await markdown_memory.get_profile()
    assert "field_a" in profile
    assert "field_b" in profile
    # Both should have their final values
    assert profile["field_a"]["value"] == "A-9"
    assert profile["field_b"]["value"] == "B-9"


@pytest.mark.asyncio
async def test_atomic_write_preserves_on_failure(tmp_path) -> None:
    """If os.replace fails, original file must remain intact.

    Fault injection: mock os.replace to raise, verify original survives.
    """
    from unittest.mock import patch

    mm = MarkdownMemory(memory_dir=str(tmp_path / "mem"))

    # Write initial profile
    await mm.update_profile("name", {"value": "Akari", "type": "text"})
    profile_before = await mm.get_profile()
    assert profile_before["name"]["value"] == "Akari"

    # Fault injection: os.replace raises
    with patch("os.replace", side_effect=OSError("simulated disk failure")):
        with pytest.raises(OSError, match="simulated disk failure"):
            await mm.update_profile("name", {"value": "CORRUPTED", "type": "text"})

    # Original file must survive
    profile_after = await mm.get_profile()
    assert profile_after["name"]["value"] == "Akari", "Original file must be intact after os.replace failure"
