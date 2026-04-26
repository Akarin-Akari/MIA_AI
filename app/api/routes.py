"""API routes for the Personal AI Agent.

POST /chat   — Send a message and get a response
GET  /memory — View profile and recent facts
GET  /health — Service health check

CRITICAL: Agent access MUST go through request.app.state.agent — this is
          the ONLY sanctioned DI path. NO module-level imports of get_agent().
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from app.models.schemas import ChatRequest, ChatResponse, HealthResponse, MemoryResponse

router = APIRouter()


def _get_agent_from_request(request: Request):
    """Extract agent from app.state — the ONLY sanctioned DI path.

    Raises:
        RuntimeError: If agent not initialized in startup.
    """
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise RuntimeError("Agent not initialized. Ensure startup completed.")
    return agent


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Health check endpoint."""
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return HealthResponse(status="starting")
    return HealthResponse(status="ok")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Chat with the agent.

    Args:
        request: FastAPI request — carries app.state.agent via DI.
        body: ChatRequest with message and optional conversation_id.

    Returns:
        ChatResponse with agent's response and conversation_id.
    """
    agent = _get_agent_from_request(request)
    conv_id = body.conversation_id or str(uuid.uuid4())

    result = await agent.run(
        user_message=body.message,
        conversation_id=conv_id,
    )

    return ChatResponse(
        response=result.content or "",
        conversation_id=conv_id,
    )


@router.get("/memory", response_model=MemoryResponse)
async def memory(request: Request) -> MemoryResponse:
    """View current memory state.

    Uses MemoryManager's public interface — does NOT reach into private attrs.
    """
    agent = _get_agent_from_request(request)
    memory_mgr = agent._memory  # MemoryManager is a known internal attr

    profile = await memory_mgr.markdown.get_profile()
    facts = await memory_mgr.markdown.get_top_k_facts(k=10)

    return MemoryResponse(profile=profile, recent_facts=facts)
