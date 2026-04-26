"""Anthropic Messages API client with complete bidirectional translation.

Inbound:  CanonicalMessage + ToolSpec → Anthropic SDK format
Outbound: Anthropic SDK response → LLMResponse

Uses standard Messages API with tool_use / tool_result content blocks.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.llm.base import CanonicalMessage, LLMResponse, ToolCall, ToolSpec

logger = logging.getLogger(__name__)


class AnthropicClient:
    """Anthropic Messages API client with full marshal/unmarshal."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    # ── Inbound Translation ──────────────────────────────────────────

    @staticmethod
    def _to_anthropic_tool(spec: ToolSpec) -> dict[str, Any]:
        """Convert ToolSpec to Anthropic tool schema.

        Anthropic shape: {"name", "description", "input_schema"}
        """
        return {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.parameters,
        }

    @staticmethod
    def _to_anthropic_messages(
        messages: list[CanonicalMessage],
    ) -> list[dict[str, Any]]:
        """Convert CanonicalMessage list to Anthropic message format.

        Key translations:
        - assistant with tool_calls → content blocks with type="tool_use"
        - tool_result → content block with type="tool_result" + tool_use_id
        - Consecutive tool_results for same assistant turn are grouped
        """
        anthropic_msgs: list[dict[str, Any]] = []

        i = 0
        while i < len(messages):
            msg = messages[i]

            if msg.role == "user":
                anthropic_msgs.append({"role": "user", "content": msg.content or ""})
                i += 1

            elif msg.role == "assistant":
                content_blocks: list[dict[str, Any]] = []

                # Add text content if present
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})

                # Add tool_use blocks
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.input,
                        })

                if not content_blocks:
                    content_blocks.append({"type": "text", "text": ""})

                anthropic_msgs.append({"role": "assistant", "content": content_blocks})
                i += 1

            elif msg.role == "tool_result":
                # Collect consecutive tool_results into one user message
                tool_result_blocks: list[dict[str, Any]] = []
                while i < len(messages) and messages[i].role == "tool_result":
                    tr = messages[i]
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tr.tool_call_id,  # Anthropic uses tool_use_id
                        "content": tr.content or "",
                    })
                    i += 1

                anthropic_msgs.append({"role": "user", "content": tool_result_blocks})

            else:
                logger.warning("Unknown message role: %s, skipping", msg.role)
                i += 1

        return anthropic_msgs

    # ── Outbound Translation ─────────────────────────────────────────

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        """Convert Anthropic response to LLMResponse.

        Extracts:
        - Text from text content blocks
        - ToolCalls from tool_use content blocks
        - Unified stop_reason mapping
        """
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                ))

        # Map Anthropic stop_reason to unified format
        stop_reason = "end_turn"
        if response.stop_reason == "tool_use":
            stop_reason = "tool_use"

        return LLMResponse(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            raw=response,
        )

    # ── Public API ───────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[CanonicalMessage],
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        """Send messages to Anthropic and return standardized response.

        Args:
            messages: Conversation history in canonical format.
            tools: Available tools for the model.
            system: System prompt (Anthropic uses separate parameter).
            tool_choice: Tool selection strategy — translated to Anthropic format:
                - None → not set (provider default)
                - "auto" → {"type": "auto"}
                - "none" → not sent (omit tools instead)
                - "<tool_name>" → {"type": "tool", "name": "<tool_name>"}

        Returns:
            LLMResponse with content, tool_calls, and unified stop_reason.
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": self._to_anthropic_messages(messages),
        }

        # Anthropic: system prompt is a separate top-level parameter
        if system:
            kwargs["system"] = system

        if tools:
            kwargs["tools"] = [self._to_anthropic_tool(t) for t in tools]

            # Anthropic tool_choice translation
            if tool_choice:
                if tool_choice == "auto":
                    kwargs["tool_choice"] = {"type": "auto"}
                elif tool_choice == "none":
                    # Don't send tools at all for "none"
                    del kwargs["tools"]
                else:
                    # Forced tool use — {"type": "tool", "name": "<name>"}
                    kwargs["tool_choice"] = {"type": "tool", "name": tool_choice}

        logger.debug("Anthropic request: model=%s, msgs=%d", self._model, len(messages))

        response = await self._client.messages.create(**kwargs)
        return self._parse_response(response)
