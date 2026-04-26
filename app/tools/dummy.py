"""Dummy tool for smoke testing.

A minimal tool that always returns "dummy ok" — used to verify
ToolRegistry and tool roundtrip work correctly in Layer 1.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import BaseTool


class DummyTool(BaseTool):
    """Simple test tool that returns a fixed response."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy tool for testing. Returns 'dummy ok'."

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Optional message to echo",
                },
            },
            "required": [],
        }

    def execute(self, message: str = "") -> str:
        """Execute dummy tool.

        This is intentionally SYNC to test asyncio.to_thread wrapping.

        Args:
            message: Optional message to include in response.

        Returns:
            "dummy ok" or "dummy ok: {message}".
        """
        if message:
            return f"dummy ok: {message}"
        return "dummy ok"
