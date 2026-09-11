"""Citizen AI Assistant API (Part 25).

Citizen-only RAG assistant powered by Groq + pgvector:

- POST /assistant/ask         — single answer (non-streaming)
- POST /assistant/ask/stream  — Server-Sent-Events streaming answer
- GET  /assistant/conversation — saved turn history for this citizen
- DELETE /assistant/conversation — clear this citizen's conversation

Permission model: authenticated CITIZEN only (401 anonymous, 403 for other
roles). All data lookups are scoped to the authenticated user by the service, so
the assistant can never expose another citizen's records.

If ``GROQ_API_KEY`` is not configured and an answer requires the LLM, a 503 is
returned with instructions to configure the key.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.assistant import (
    AssistantAnswerOut,
    AssistantAskIn,
    AssistantClearOut,
    AssistantConversationOut,
)
from app.services import assistant_service
from app.services.ai_service import AIConfigurationError, AIService, get_ai_service

router = APIRouter(prefix="/assistant", tags=["assistant"])

_CITIZEN = RoleName.CITIZEN.value

_CONFIG_MESSAGE = (
    "GROQ_API_KEY is not configured, so the assistant cannot answer this question. "
    "Set GROQ_API_KEY in the backend environment and restart the service."
)


async def _ai_for_request(settings: Settings = Depends(get_settings)) -> AIService:
    """Request-scoped AI service dependency.

    ``get_ai_service`` itself accepts an optional ``settings`` argument, which
    FastAPI would otherwise bind as a second (embedded) body parameter; wrapping
    it in a proper dependency keeps the request body a single ``payload``.
    """
    return get_ai_service(settings)


def _require_citizen(user: User) -> None:
    if user.role.name != _CITIZEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The AI assistant is a citizen-facing tool.",
        )


@router.post("/ask", response_model=AssistantAnswerOut)
async def ask(
    payload: AssistantAskIn,
    user: User = Depends(require_roles(_CITIZEN)),
    db: AsyncSession = Depends(get_db),
    ai: AIService = Depends(_ai_for_request),
) -> AssistantAnswerOut:
    _require_citizen(user)
    try:
        return await assistant_service.answer(
            db, user, payload.question, ai, language=payload.language
        )
    except AIConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_CONFIG_MESSAGE,
        ) from None


@router.post("/ask/stream")
async def ask_stream(
    payload: AssistantAskIn,
    user: User = Depends(require_roles(_CITIZEN)),
    db: AsyncSession = Depends(get_db),
    ai: AIService = Depends(_ai_for_request),
) -> StreamingResponse:
    """Stream the answer as Server-Sent Events (meta / delta / sources / done).

    Config is validated up-front so an unconfigured key returns a 503 before any
    event is written (symmetric with the non-streaming endpoint).
    """
    _require_citizen(user)
    prepared = await assistant_service.prepare(
        db, user, payload.question, language=payload.language
    )
    if prepared.needs_llm and not getattr(ai, "is_configured", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_CONFIG_MESSAGE,
        )

    generator = assistant_service.stream_response(
        db, user, payload.question, ai, prepared, language=payload.language
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversation", response_model=AssistantConversationOut)
async def get_conversation(
    user: User = Depends(require_roles(_CITIZEN)),
    db: AsyncSession = Depends(get_db),
) -> AssistantConversationOut:
    _require_citizen(user)
    conversation = await assistant_service.get_conversation(db, user)
    return AssistantConversationOut(**conversation)


@router.delete("/conversation", response_model=AssistantClearOut)
async def clear_conversation(
    user: User = Depends(require_roles(_CITIZEN)),
    db: AsyncSession = Depends(get_db),
) -> AssistantClearOut:
    _require_citizen(user)
    deleted = await assistant_service.clear_conversation(db, user)
    return AssistantClearOut(cleared=True, messages_deleted=deleted)
