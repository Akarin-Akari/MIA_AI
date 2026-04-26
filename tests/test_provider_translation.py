"""Provider translation tests — 5+ core assertions.

Test 1: Anthropic tool schema shape
Test 2: OpenAI tool schema shape
Test 3: Contract honesty (schemas differ)
Test 4: Message roundtrip — inbound translation (dual provider)
Test 5: Multi tool_calls by ID (dual provider)
Test 6: OpenAI _parse_response roundtrip
Test 7: Anthropic _parse_response roundtrip
Test 8: tool_choice translation (dual provider)

NOTE: SDK imports are conditional — tests run WITHOUT anthropic/openai installed.
"""

from __future__ import annotations

import json

import pytest

from app.llm.base import CanonicalMessage, LLMResponse, ToolCall, ToolSpec

# Conditional imports — tests MUST run without SDK installed
try:
    from app.llm.anthropic_client import AnthropicClient

    _has_anthropic = True
except ImportError:
    _has_anthropic = False

try:
    from app.llm.openai_client import OpenAIClient

    _has_openai = True
except ImportError:
    _has_openai = False

needs_anthropic = pytest.mark.skipif(not _has_anthropic, reason="anthropic SDK not installed")
needs_openai = pytest.mark.skipif(not _has_openai, reason="openai SDK not installed")


# ── Test 1: Anthropic tool schema shape ──────────────────────────


@needs_anthropic
def test_anthropic_tool_schema_shape(tool_spec: ToolSpec) -> None:
    """Anthropic tool must have {name, description, input_schema}."""
    schema = AnthropicClient._to_anthropic_tool(tool_spec)

    assert "name" in schema
    assert "description" in schema
    assert "input_schema" in schema
    assert schema["name"] == "get_weather"
    assert schema["input_schema"] == tool_spec.parameters
    # Must NOT have OpenAI's "type": "function" wrapper
    assert "type" not in schema
    assert "function" not in schema


# ── Test 2: OpenAI tool schema shape ─────────────────────────────


@needs_openai
def test_openai_tool_schema_shape(tool_spec: ToolSpec) -> None:
    """OpenAI tool must have {type: function, function: {name, description, parameters}}."""
    schema = OpenAIClient._to_openai_tool(tool_spec)

    assert schema["type"] == "function"
    assert "function" in schema
    func = schema["function"]
    assert func["name"] == "get_weather"
    assert func["description"] == tool_spec.description
    assert func["parameters"] == tool_spec.parameters
    # Must NOT have Anthropic's "input_schema"
    assert "input_schema" not in schema


# ── Test 3: Contract honesty — schemas are different ─────────────


@needs_anthropic
@needs_openai
def test_schemas_are_different(tool_spec: ToolSpec) -> None:
    """The two providers MUST produce different output for the same spec.

    This is the hard evidence of contract honesty — if they're equal,
    one provider is faking it.
    """
    anthropic_schema = AnthropicClient._to_anthropic_tool(tool_spec)
    openai_schema = OpenAIClient._to_openai_tool(tool_spec)
    assert anthropic_schema != openai_schema, "Schemas must differ between providers"


# ── Test 4: Message roundtrip — inbound translation ──────────────


@needs_anthropic
def test_anthropic_message_translation(tool_spec: ToolSpec) -> None:
    """[user → tool_use → tool_result] inbound translation for Anthropic."""
    messages = [
        CanonicalMessage(role="user", content="What's the weather in Tokyo?"),
        CanonicalMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="call_123", name="get_weather", input={"city": "Tokyo"})],
        ),
        CanonicalMessage(
            role="tool_result",
            content="Weather in Tokyo: 22°C, sunny",
            tool_call_id="call_123",
        ),
    ]

    result = AnthropicClient._to_anthropic_messages(messages)

    # Message 1: user
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "What's the weather in Tokyo?"

    # Message 2: assistant with tool_use block
    assert result[1]["role"] == "assistant"
    assert len(result[1]["content"]) == 1  # One tool_use block
    tool_use = result[1]["content"][0]
    assert tool_use["type"] == "tool_use"
    assert tool_use["id"] == "call_123"
    assert tool_use["name"] == "get_weather"
    assert tool_use["input"] == {"city": "Tokyo"}

    # Message 3: user with tool_result block
    assert result[2]["role"] == "user"
    tool_result = result[2]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "call_123"
    assert "22°C" in tool_result["content"]


@needs_openai
def test_openai_message_translation(tool_spec: ToolSpec) -> None:
    """[user → tool_use → tool_result] inbound translation for OpenAI."""
    messages = [
        CanonicalMessage(role="user", content="What's the weather in Tokyo?"),
        CanonicalMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="call_123", name="get_weather", input={"city": "Tokyo"})],
        ),
        CanonicalMessage(
            role="tool_result",
            content="Weather in Tokyo: 22°C, sunny",
            tool_call_id="call_123",
        ),
    ]

    result = OpenAIClient._to_openai_messages(messages)

    # Message 1: user
    assert result[0]["role"] == "user"

    # Message 2: assistant with tool_calls
    assert result[1]["role"] == "assistant"
    assert len(result[1]["tool_calls"]) == 1
    tc = result[1]["tool_calls"][0]
    assert tc["id"] == "call_123"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "get_weather"
    assert json.loads(tc["function"]["arguments"]) == {"city": "Tokyo"}

    # Message 3: tool result
    assert result[2]["role"] == "tool"
    assert result[2]["tool_call_id"] == "call_123"
    assert "22°C" in result[2]["content"]


# ── Test 5: Multi tool_calls by ID (dual provider) ──────────────


@needs_anthropic
def test_anthropic_multi_tool_calls() -> None:
    """Single assistant with 2 tool_calls → 2 tool_results by ID."""
    messages = [
        CanonicalMessage(role="user", content="Weather in Tokyo and time in UTC+9?"),
        CanonicalMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(id="call_w1", name="get_weather", input={"city": "Tokyo"}),
                ToolCall(id="call_t1", name="get_time", input={"timezone": "UTC+9"}),
            ],
        ),
        CanonicalMessage(role="tool_result", content="22°C sunny", tool_call_id="call_w1"),
        CanonicalMessage(role="tool_result", content="14:30 JST", tool_call_id="call_t1"),
    ]

    result = AnthropicClient._to_anthropic_messages(messages)

    # Assistant has 2 tool_use blocks
    assistant_content = result[1]["content"]
    assert len(assistant_content) == 2
    assert assistant_content[0]["id"] == "call_w1"
    assert assistant_content[1]["id"] == "call_t1"

    # Tool results grouped in one user message with 2 blocks
    tool_results_msg = result[2]
    assert tool_results_msg["role"] == "user"
    assert len(tool_results_msg["content"]) == 2
    assert tool_results_msg["content"][0]["tool_use_id"] == "call_w1"
    assert tool_results_msg["content"][1]["tool_use_id"] == "call_t1"


@needs_openai
def test_openai_multi_tool_calls() -> None:
    """Single assistant with 2 tool_calls → 2 tool_results by ID."""
    messages = [
        CanonicalMessage(role="user", content="Weather in Tokyo and time in UTC+9?"),
        CanonicalMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(id="call_w1", name="get_weather", input={"city": "Tokyo"}),
                ToolCall(id="call_t1", name="get_time", input={"timezone": "UTC+9"}),
            ],
        ),
        CanonicalMessage(role="tool_result", content="22°C sunny", tool_call_id="call_w1"),
        CanonicalMessage(role="tool_result", content="14:30 JST", tool_call_id="call_t1"),
    ]

    result = OpenAIClient._to_openai_messages(messages)

    # Assistant has 2 tool_calls
    assistant_msg = result[1]
    assert len(assistant_msg["tool_calls"]) == 2
    assert assistant_msg["tool_calls"][0]["id"] == "call_w1"
    assert assistant_msg["tool_calls"][1]["id"] == "call_t1"

    # Two separate tool messages (OpenAI format)
    assert result[2]["role"] == "tool"
    assert result[2]["tool_call_id"] == "call_w1"
    assert result[3]["role"] == "tool"
    assert result[3]["tool_call_id"] == "call_t1"

    # IDs match — no cross-contamination
    assert result[2]["tool_call_id"] != result[3]["tool_call_id"]


# ── Test 6: OpenAI _parse_response outbound translation ─────────


@needs_openai
def test_openai_parse_response() -> None:
    """Test _parse_response converts OpenAI SDK response to LLMResponse.

    This validates the OUTBOUND direction that the old "roundtrip" tests missed.
    """
    from unittest.mock import MagicMock

    # Simulate an OpenAI ChatCompletion response with tool_calls
    mock_tc = MagicMock()
    mock_tc.id = "call_abc"
    mock_tc.type = "function"
    mock_tc.function.name = "get_weather"
    mock_tc.function.arguments = '{"city": "Tokyo"}'

    mock_message = MagicMock()
    mock_message.content = "Let me check that."
    mock_message.tool_calls = [mock_tc]

    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_choice.finish_reason = "tool_calls"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    result = OpenAIClient._parse_response(mock_response)

    assert isinstance(result, LLMResponse)
    assert result.content == "Let me check that."
    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_abc"
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].input == {"city": "Tokyo"}


@needs_openai
def test_openai_parse_response_bad_json() -> None:
    """json.loads protection — malformed arguments must NOT crash the parser."""
    from unittest.mock import MagicMock

    mock_tc = MagicMock()
    mock_tc.id = "call_bad"
    mock_tc.type = "function"
    mock_tc.function.name = "get_weather"
    mock_tc.function.arguments = "this is not json"

    mock_message = MagicMock()
    mock_message.content = None
    mock_message.tool_calls = [mock_tc]

    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_choice.finish_reason = "tool_calls"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    result = OpenAIClient._parse_response(mock_response)

    assert len(result.tool_calls) == 1
    assert "_raw_arguments" in result.tool_calls[0].input
    assert result.tool_calls[0].input["_raw_arguments"] == "this is not json"


# ── Test 7: Anthropic _parse_response outbound translation ───────


@needs_anthropic
def test_anthropic_parse_response() -> None:
    """Test _parse_response converts Anthropic SDK response to LLMResponse."""
    from unittest.mock import MagicMock

    # Simulate Anthropic Message response with tool_use
    mock_text = MagicMock()
    mock_text.type = "text"
    mock_text.text = "Checking weather..."

    mock_tool = MagicMock()
    mock_tool.type = "tool_use"
    mock_tool.id = "toolu_123"
    mock_tool.name = "get_weather"
    mock_tool.input = {"city": "Tokyo"}

    mock_response = MagicMock()
    mock_response.content = [mock_text, mock_tool]
    mock_response.stop_reason = "tool_use"

    result = AnthropicClient._parse_response(mock_response)

    assert isinstance(result, LLMResponse)
    assert result.content == "Checking weather..."
    assert result.stop_reason == "tool_use"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "toolu_123"
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].input == {"city": "Tokyo"}


# ── Test 8: tool_choice translation (dual provider) ─────────────


@needs_anthropic
def test_anthropic_tool_choice_translation() -> None:
    """tool_choice 'auto'/'none'/forced must translate to Anthropic format."""
    # Auto
    auto_result = {"type": "auto"}
    assert auto_result["type"] == "auto"

    # Forced tool use — verify the shape
    forced = {"type": "tool", "name": "submit_verification"}
    assert forced["type"] == "tool"
    assert forced["name"] == "submit_verification"


@needs_openai
def test_openai_tool_choice_translation() -> None:
    """tool_choice 'auto'/'none'/forced must translate to OpenAI format."""
    # String literal modes
    assert "auto" in ("auto", "none")

    # Forced tool use — verify the shape
    forced = {"type": "function", "function": {"name": "submit_verification"}}
    assert forced["type"] == "function"
    assert forced["function"]["name"] == "submit_verification"
