"""Internal canonical types for LLM communication.

All modules communicate through these types. NEVER pass provider-specific
dicts directly to a Client — each Client handles its own marshalling.

Design Decisions:
- dataclass over pydantic for zero-dependency core types
- Provider-NEUTRAL naming: `tool_call_id` (NOT `tool_use_id`)
- LLMClient is a Protocol — duck-typing for testability
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    """Tool specification in provider-neutral format.

    Each LLM Client independently translates this to its SDK's expected shape:
    - Anthropic: {"name", "description", "input_schema"}
    - OpenAI:    {"type": "function", "function": {"name", "description", "parameters"}}
    """

    name: str
    description: str
    parameters: dict  # JSON Schema


@dataclass
class ToolCall:
    """A single tool invocation requested by the LLM.

    Attributes:
        id: Provider-generated unique ID for matching tool_result back.
        name: Tool name matching a registered BaseTool.
        input: Arguments to pass to the tool's execute method.
    """

    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider.

    Attributes:
        content: Text content of the response (may be empty if tool_use).
        tool_calls: List of tool calls requested by the LLM.
        stop_reason: "end_turn" or "tool_use" — unified across providers.
        raw: Raw provider response for debugging.
    """

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use"
    raw: Any = None


@dataclass
class CanonicalMessage:
    """Internal canonical message format.

    NEVER pass provider-specific dicts directly to a Client.

    Field naming is provider-NEUTRAL. We use `tool_call_id` (NOT `tool_use_id`)
    deliberately to avoid Anthropic-term leakage into the internal IR — a leak
    would re-bias implementers toward 'think Anthropic first, OpenAI as fallback'
    and is a recurring contract-honesty pitfall.

    Attributes:
        role: "user" | "assistant" | "tool_result"
        content: Text content (None for pure tool_use assistant messages).
        tool_calls: Only for assistant role — tools the LLM wants to call.
        tool_call_id: Only for tool_result role — matches ToolCall.id.
    """

    role: str  # "user" | "assistant" | "tool_result"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # provider-neutral name


class LLMClient(Protocol):
    """Protocol for LLM provider clients.

    Each implementation must handle complete bidirectional translation:
    - Inbound:  CanonicalMessage + ToolSpec → provider SDK format
    - Outbound: provider SDK response → LLMResponse
    """

    async def chat(
        self,
        messages: list[CanonicalMessage],
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        """Send messages to LLM and return standardized response.

        Args:
            messages: Conversation history in canonical format.
            tools: Available tools for the model.
            system: System prompt.
            tool_choice: Tool selection strategy:
                - None: provider default (no constraint)
                - "auto": let model decide
                - "none": don't use tools
                - "<tool_name>": force model to use this specific tool
        """
        ...
