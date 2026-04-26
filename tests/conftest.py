"""Shared test fixtures.

CRITICAL:
- Use tmp_path file DB, NEVER :memory: (cross-connection data loss)
- All fixtures use real instances, not mocks, unless explicitly noted
"""

from __future__ import annotations

import pytest

from app.llm.base import ToolSpec
from app.memory.markdown_store import MarkdownMemory
from app.memory.sqlite_store import SQLiteStore
from app.memory.working import WorkingMemory


@pytest.fixture
def tool_spec() -> ToolSpec:
    """Standard test ToolSpec."""
    return ToolSpec(
        name="get_weather",
        description="Get weather for a city",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        },
    )


@pytest.fixture
def second_tool_spec() -> ToolSpec:
    """Second test ToolSpec for multi-tool tests."""
    return ToolSpec(
        name="get_time",
        description="Get current time for a timezone",
        parameters={
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "Timezone"},
            },
            "required": ["timezone"],
        },
    )


@pytest.fixture
def working_memory() -> WorkingMemory:
    """Fresh WorkingMemory instance."""
    return WorkingMemory(maxlen=50)


@pytest.fixture
async def sqlite_store(tmp_path) -> SQLiteStore:
    """SQLiteStore with tmp_path file DB (NOT :memory:)."""
    db_path = str(tmp_path / "test.db")
    store = SQLiteStore(db_path=db_path)
    await store.initialize()
    return store


@pytest.fixture
def markdown_memory(tmp_path) -> MarkdownMemory:
    """MarkdownMemory with tmp_path directory."""
    return MarkdownMemory(memory_dir=str(tmp_path / "memory"))
