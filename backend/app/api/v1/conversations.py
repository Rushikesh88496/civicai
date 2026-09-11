"""Complaint conversation API (Part 17).

Endpoints:
- GET    /conversations                          — the participant's inbox
- GET    /conversations/complaints/{id}          — one complaint conversation
- POST   /conversations/complaints/{id}/messages — post a message (optional attachments)
- POST   /conversations/complaints/{id}/attachments — upload a pending attachment
- POST   /conversations/complaints/{id}/read     — mark the conversation read
- POST   /conversations/complaints/{id}/ai-summary — AI draft summary + suggested reply (never sent)

All endpoints authenticate the current user and enforce conversation
participation in the service (owner citizen / ward representative / officer /
admin; FIELD_WORKER is denied).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.conversation import (
    AiDraftOut,
    AttachmentUploadOut,
    ConversationListOut,
    ConversationOut,
    MessageCreateIn,
)
from app.services import conversation_service
from app.services.ai_service import get_ai_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _conversation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ComplaintNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found.")
    if isinstance(exc, ComplaintAccessError):
        return HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You are not an authorized participant of this conversation.",
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("", response_model=ConversationListOut)
async def conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationListOut:
    try:
        return await conversation_service.list_conversations(db, user)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _conversation_error(exc) from exc


@router.get("/complaints/{complaint_id}", response_model=ConversationOut)
async def conversation(
    complaint_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    try:
        return await conversation_service.get_conversation(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _conversation_error(exc) from exc


@router.post("/complaints/{complaint_id}/messages", response_model=ConversationOut)
async def send_message(
    complaint_id: uuid.UUID,
    payload: MessageCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    try:
        return await conversation_service.send_message(
            db, user, complaint_id, payload.body, payload.attachment_ids
        )
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _conversation_error(exc) from exc


@router.post("/complaints/{complaint_id}/attachments", response_model=AttachmentUploadOut)
async def upload_attachment(
    complaint_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttachmentUploadOut:
    try:
        data = await file.read()
        content_type = file.content_type or ""
        return await conversation_service.upload_attachment(
            db, user, complaint_id, file.filename or "attachment", content_type, data
        )
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _conversation_error(exc) from exc


@router.post("/complaints/{complaint_id}/read", response_model=ConversationOut)
async def mark_read(
    complaint_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    try:
        return await conversation_service.mark_conversation_read(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _conversation_error(exc) from exc


@router.post("/complaints/{complaint_id}/ai-summary", response_model=AiDraftOut)
async def ai_summary(
    complaint_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiDraftOut:
    try:
        return await conversation_service.generate_draft(
            db, user, complaint_id, ai=get_ai_service()
        )
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _conversation_error(exc) from exc
