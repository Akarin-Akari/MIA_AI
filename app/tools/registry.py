"""Tool registry with automatic sync/async detection.

Manages tool registration, lookup, and execution. Sync tools are automatically
wrapped with asyncio.to_thread to prevent Event Loop blocking.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from app.llm.base import ToolSpec
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for tool management and execution.

    Key behaviors:
    - register(): Adds a tool to the registry
    - execute(): Runs a tool by name, auto-wrapping sync tools with to_thread
    - specs(): Returns all tool specs for LLM consumption
    - Exceptions are caught and returned as "ERROR: ..." strings (never raised)
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool by its name.

        Args:
            tool: BaseTool instance to register.
        """
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name.

        Args:
            name: Tool name.

        Returns:
            BaseTool instance or None if not found.
        """
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def specs(self) -> list[ToolSpec]:
        """Return ToolSpec list for all registered tools.

        Used to provide tool definitions to LLM clients.
        """
        return [tool.to_spec() for tool in self._tools.values()]

    async def execute(self, name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool by name with given input.

        Automatically detects sync vs async execute methods:
        - Async: awaited directly
        - Sync: wrapped with asyncio.to_thread to prevent Event Loop blocking

        Args:
            name: Tool name.
            tool_input: Arguments dict to pass to tool.execute().

        Returns:
            String result. Errors are returned as "ERROR: ..." strings,
            NEVER raised out of the registry.
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"ERROR: Tool '{name}' not found. Available: {self.list_tools()}"

        try:
            if inspect.iscoroutinefunction(tool.execute):
                # Async tool — await directly
                result = await tool.execute(**tool_input)
            else:
                # Sync tool — wrap with to_thread to avoid blocking Event Loop
                result = await asyncio.to_thread(tool.execute, **tool_input)

            return str(result)

        except Exception as e:
            error_msg = f"ERROR: Tool '{name}' failed: {type(e).__name__}: {e}"
            logger.error(error_msg, exc_info=True)
            return error_msg
