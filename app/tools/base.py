"""Base tool abstraction.

All tools inherit from BaseTool and implement execute().
BaseTool provides `to_spec()` for automatic ToolSpec generation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.llm.base import ToolSpec


class BaseTool(ABC):
    """Abstract base class for all tools.

    Subclasses must define:
    - name: Tool identifier
    - description: What the tool does
    - parameters(): JSON Schema for the tool's input
    - execute(**kwargs): The actual tool logic (sync or async)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable tool description."""
        ...

    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """Return JSON Schema for tool input parameters."""
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Execute the tool. May be sync or async.

        ToolRegistry detects sync vs async via inspect.iscoroutinefunction
        and wraps sync tools with asyncio.to_thread automatically.

        Returns:
            Tool result (will be str-ified by registry).
        """
        ...

    def to_spec(self) -> ToolSpec:
        """Generate ToolSpec from this tool's metadata.

        Returns:
            ToolSpec with name, description, and parameters.
        """
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters(),
        )
