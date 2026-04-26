"""API request/response schemas.

Pydantic v2 models for FastAPI endpoint validation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /chat request body."""

    message: str = Field(..., min_length=1, description="User message")
    conversation_id: str | None = Field(
        default=None,
        description="Conversation ID for context continuity. Auto-generated if omitted.",
    )


class ChatResponse(BaseModel):
    """POST /chat response body."""

    response: str = Field(..., description="Agent's response")
    conversation_id: str = Field(..., description="Conversation ID used")


class HealthResponse(BaseModel):
    """GET /health response body."""

    status: str = "ok"
    provider: str = ""
    model: str = ""


class MemoryResponse(BaseModel):
    """GET /memory response body."""

    profile: dict = Field(default_factory=dict)
    recent_facts: list[str] = Field(default_factory=list)
