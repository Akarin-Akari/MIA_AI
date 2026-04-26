"""OpenAI Chat Completions API client with complete bidirectional translation.

Inbound:  CanonicalMessage + ToolSpec → OpenAI Chat Completions format
Outbound: OpenAI SDK response → LLMResponse

CRITICAL: Uses Chat Completions API ONLY (messages + tools + message.tool_calls).
          Responses API is STRICTLY FORBIDDEN (different tool_call protocol).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import openai

from app.llm.base import CanonicalMessage, LLMResponse, ToolCall, ToolSpec

logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI Chat Completions API client with full marshal/unmarshal.

    MUST use `client.chat.completions.create()` — NEVER `responses.create()`.
    """

    def __init__(self, api_key: str, model: str, base_url: str = "") -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._model = model

    # ── Inbound Translation ──────────────────────────────────────────

    @staticmethod
    def _to_openai_tool(spec: ToolSpec) -> dict[str, Any]:
        """Convert ToolSpec to OpenAI function tool schema.

        OpenAI shape: {"type": "function", "function": {"name", "description", "parameters"}}
        """
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }

    @staticmethod
    def _to_openai_messages(
        messages: list[CanonicalMessage],
        system: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert CanonicalMessage list to OpenAI message format.

        Key translations:
        - system prompt → messages[0] with role="system"
        - assistant with tool_calls → message.tool_calls array
        - tool_result → role="tool" + tool_call_id
        """
        openai_msgs: list[dict[str, Any]] = []

        # OpenAI: system prompt goes as first message
        if system:
            openai_msgs.append({"role": "system", "content": system})

        for msg in messages:
            if msg.role == "user":
                openai_msgs.append({"role": "user", "content": msg.content or ""})

            elif msg.role == "assistant":
                assistant_msg: dict[str, Any] = {"role": "assistant"}

                if msg.content:
                    assistant_msg["content"] = msg.content
                else:
                    assistant_msg["content"] = None

                # Convert tool_calls to OpenAI format
                if msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.input),
                            },
                        }
                        for tc in msg.tool_calls
                    ]

                openai_msgs.append(assistant_msg)

            elif msg.role == "tool_result":
                # OpenAI: each tool_result is a separate message with role="tool"
                openai_msgs.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content or "",
                })

            else:
                logger.warning("Unknown message role: %s, skipping", msg.role)

        return openai_msgs

    # ── Outbound Translation ─────────────────────────────────────────

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        """Convert OpenAI response to LLMResponse.

        Extracts:
        - Text content from message.content
        - ALL ToolCalls from message.tool_calls (not just first)
        - Unified stop_reason mapping
        """
        choice = response.choices[0]
        message = choice.message

        text = message.content or ""
        tool_calls: list[ToolCall] = []

        # Extract ALL tool_calls — NEVER take only the first one
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    parsed_input = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    parsed_input = {"_raw_arguments": tc.function.arguments}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=parsed_input,
                ))

        # Map OpenAI finish_reason to unified format
        stop_reason = "end_turn"
        if choice.finish_reason == "tool_calls":
            stop_reason = "tool_use"

        return LLMResponse(
            content=text,
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
        """Send messages to OpenAI Chat Completions API.

        CRITICAL: Uses `chat.completions.create()` — NEVER `responses.create()`.

        Args:
            messages: Conversation history in canonical format.
            tools: Available tools for the model.
            system: System prompt (injected as messages[0] role=system).
            tool_choice: Tool selection strategy — translated to OpenAI format:
                - None → not set (provider default)
                - "auto" / "none" → passed as string literal
                - "<tool_name>" → {"type": "function", "function": {"name": "<name>"}}

        Returns:
            LLMResponse with content, tool_calls, and unified stop_reason.
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": self._to_openai_messages(messages, system=system),
        }

        if tools:
            kwargs["tools"] = [self._to_openai_tool(t) for t in tools]

            # OpenAI tool_choice translation
            if tool_choice:
                if tool_choice in ("auto", "none"):
                    kwargs["tool_choice"] = tool_choice
                else:
                    # Forced tool use
                    kwargs["tool_choice"] = {
                        "type": "function",
                        "function": {"name": tool_choice},
                    }

        logger.debug("OpenAI request: model=%s, msgs=%d", self._model, len(messages))

        # CRITICAL: chat.completions.create — NOT responses.create
        response = await self._client.chat.completions.create(**kwargs)
        return self._parse_response(response)
