"""Complaint conversation business logic (Part 17).

Gives every participant of a complaint-authorized conversation a first-class,
secure messaging experience:

* **Participation** — only the complaint's citizen owner, the representative of
  the complaint's ward, and officers / admins may read or post. Access reuses
  ``complaint_tracking_service.user_can_view`` plus an explicit role allow-list
  (FIELD_WORKER is excluded even though they have broad view rights).
* **Messages** — post a message (with optional attachments), read the thread,
  and mark messages read. Read receipts are tracked per (message, user).
* **Attachments** — two-phase upload: the file is stored and authorized against
  ``complaint_id`` + ``uploader_id`` before it is linked to a message, so
  ownership is always enforced.
* **AI drafts** — ``generate_draft`` returns a *summary + suggested reply* that
  is always ``draft=True`` and never sent automatically; only the real, verified
  user posting through the message endpoint creates a message. The AI never
  impersonates an official.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import (
    Complaint,
    Conversation,
    Message,
    MessageAttachment,
    MessageRead,
    Role,
    User,
)
from app.models.enums import RoleName
from app.schemas.conversation import (
    AiDraftOut,
    AttachmentOut,
    AttachmentUploadOut,
    ConversationListItem,
    ConversationListOut,
    ConversationOut,
    MessageOut,
    MessageReadReceipt,
)
from app.services import notification_service
from app.services.ai_service import AIService, get_ai_service
from app.services.complaint_tracking_service import (
    ComplaintAccessError,
    ComplaintNotFoundError,
    user_can_view,
)
from app.storage import get_storage

# Roles allowed to participate in an authorized conversation.
_CONVERSATION_ROLES = {
    RoleName.CITIZEN.value,
    RoleName.WARD_REPRESENTATIVE.value,
    RoleName.OFFICER.value,
    RoleName.ADMIN.value,
}

# Attachments beyond complaint media: images, short videos and PDF documents.
_ALLOWED_ATTACHMENT_TYPES = {
    "image/jpeg": ("jpg", "images"),
    "image/png": ("png", "images"),
    "image/webp": ("webp", "images"),
    "image/gif": ("gif", "images"),
    "video/mp4": ("mp4", "videos"),
    "video/webm": ("webm", "videos"),
    "video/quicktime": ("mov", "videos"),
    "application/pdf": ("pdf", "documents"),
}
_DOCUMENT_MAX_MB = 10

_NOTIFICATION_TYPE_MESSAGE = "MESSAGE"


class _AiDraft(BaseModel):
    """Structured Groq response for a conversation draft."""

    summary: str
    suggested_reply: str


# --------------------------------------------------------------------------- #
# Access helpers
# --------------------------------------------------------------------------- #
async def _load_complaint_for_participant(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> Complaint:
    complaint = await db.scalar(
        select(Complaint)
        .where(Complaint.id == complaint_id)
        .options(selectinload(Complaint.ward))
        .execution_options(populate_existing=True)
    )
    if user.role.name not in _CONVERSATION_ROLES:
        raise ComplaintAccessError
    if complaint is None:
        raise ComplaintNotFoundError
    if not user_can_view(user, complaint):
        raise ComplaintAccessError
    return complaint


async def _ensure_conversation(db: AsyncSession, complaint_id: uuid.UUID) -> Conversation:
    """Return the complaint's conversation, creating it on first use."""
    conversation = await db.scalar(
        select(Conversation).where(Conversation.complaint_id == complaint_id)
    )
    if conversation is None:
        conversation = Conversation(complaint_id=complaint_id)
        db.add(conversation)
        await db.flush()
    return conversation


async def _get_conversation_or_none(
    db: AsyncSession, complaint_id: uuid.UUID
) -> Conversation | None:
    # populate_existing guarantees freshly loaded read receipts even when the
    # same instances are already present in the session's identity map (e.g.
    # right after mark-conversation-read committed new MessageRead rows).
    return await db.scalar(
        select(Conversation)
        .where(Conversation.complaint_id == complaint_id)
        .options(
            selectinload(Conversation.complaint),
            selectinload(Conversation.messages).selectinload(Message.author),
            selectinload(Conversation.messages).selectinload(Message.attachments),
            selectinload(Conversation.messages)
            .selectinload(Message.reads)
            .selectinload(MessageRead.user),
        )
        .execution_options(populate_existing=True)
    )


def _attachment_out(attachment: MessageAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=attachment.id,
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        url=get_storage().url(attachment.storage_key),
        created_at=attachment.created_at,
    )


def _message_out(
    message: Message,
    current_user_id: uuid.UUID,
    participants: set[uuid.UUID],
) -> MessageOut:
    read_user_ids = {r.user_id for r in message.reads}
    others = {uid for uid in participants if uid != message.author_id}
    read_by_all = bool(others) and others.issubset(read_user_ids)
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        complaint_id=message.complaint_id,
        author_id=message.author_id,
        author_name=message.author.full_name if message.author else None,
        role=message.role,
        body=message.body,
        created_at=message.created_at,
        attachments=[_attachment_out(a) for a in message.attachments],
        read_by=[
            MessageReadReceipt(
                user_id=r.user_id,
                user_name=r.user.full_name if r.user else None,
                read_at=r.read_at,
            )
            for r in message.reads
        ],
        read_by_all=read_by_all,
        is_read_by_me=current_user_id in read_user_ids,
    )


def _conversation_out(conversation: Conversation, current_user_id: uuid.UUID) -> ConversationOut:
    participants = {m.author_id for m in conversation.messages}
    if conversation.complaint is not None:
        participants.add(conversation.complaint.user_id)
    return ConversationOut(
        complaint_id=conversation.complaint_id,
        complaint_title=conversation.complaint.title if conversation.complaint else "",
        complaint_status=conversation.complaint.status if conversation.complaint else None,
        messages=[_message_out(m, current_user_id, participants) for m in conversation.messages],
    )


# --------------------------------------------------------------------------- #
# Read / write
# --------------------------------------------------------------------------- #
async def get_conversation(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> ConversationOut:
    """Return the complaint's conversation for an authorized participant."""
    complaint = await _load_complaint_for_participant(db, user, complaint_id)
    conversation = await _get_conversation_or_none(db, complaint.id)
    if conversation is None:
        return ConversationOut(
            complaint_id=complaint.id,
            complaint_title=complaint.title,
            complaint_status=complaint.status,
        )
    return _conversation_out(conversation, user.id)


async def send_message(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
    body: str,
    attachment_ids: list[uuid.UUID] | None = None,
) -> ConversationOut:
    """Post a message (and optionally attach previously uploaded files)."""
    complaint = await _load_complaint_for_participant(db, user, complaint_id)
    body = body.strip()
    if not body:
        raise ValueError("Message body must not be empty.")
    if len(body) > 4000:
        raise ValueError("Message body must be at most 4000 characters.")

    conversation = await _ensure_conversation(db, complaint.id)
    message = Message(
        conversation_id=conversation.id,
        complaint_id=complaint.id,
        author_id=user.id,
        role=user.role.name,
        body=body,
    )
    db.add(message)
    await db.flush()

    for attachment_id in (attachment_ids or [])[:10]:
        attachment = await db.get(MessageAttachment, attachment_id)
        if (
            attachment is None
            or attachment.uploader_id != user.id
            or attachment.complaint_id != complaint.id
            or attachment.message_id is not None
        ):
            await db.rollback()
            raise ValueError("One or more attachments are invalid or already used.")
        attachment.message_id = message.id

    await _notify_new_message(db, complaint, user, message)
    await db.commit()
    return await get_conversation(db, user, complaint.id)


async def upload_attachment(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
    filename: str,
    content_type: str,
    data: bytes,
) -> AttachmentUploadOut:
    """Validate and store an attachment for a complaint conversation."""
    complaint = await _load_complaint_for_participant(db, user, complaint_id)
    media_type = _ALLOWED_ATTACHMENT_TYPES.get(content_type)
    if media_type is None:
        raise ValueError("Unsupported attachment type.")
    category = media_type[1]
    max_bytes = get_settings().MAX_VIDEO_MB if category == "videos" else _DOCUMENT_MAX_MB
    if not data:
        raise ValueError("Uploaded file is empty.")
    if len(data) > max_bytes * 1024 * 1024:
        raise ValueError(f"Attachment exceeds the {max_bytes} MB limit.")

    ext = media_type[0]
    key = f"conversations/{complaint.id}/{user.id}/{uuid.uuid4().hex}.{ext}"
    get_storage().upload(key, data, content_type)
    safe_name = filename.replace("\\", "/").rsplit("/", 1)[-1][:255] or "attachment"
    attachment = MessageAttachment(
        complaint_id=complaint.id,
        uploader_id=user.id,
        original_filename=safe_name,
        content_type=content_type,
        storage_key=key,
        size_bytes=len(data),
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return AttachmentUploadOut(
        id=attachment.id,
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        url=get_storage().url(attachment.storage_key),
        created_at=attachment.created_at,
    )


async def mark_conversation_read(
    db: AsyncSession, user: User, complaint_id: uuid.UUID
) -> ConversationOut:
    """Mark every unread message in the conversation as read by ``user``."""
    complaint = await _load_complaint_for_participant(db, user, complaint_id)
    conversation = await _get_conversation_or_none(db, complaint.id)
    if conversation is None:
        return ConversationOut(
            complaint_id=complaint.id,
            complaint_title=complaint.title,
            complaint_status=complaint.status,
        )

    for message in conversation.messages:
        if message.author_id == user.id:
            continue
        if any(r.user_id == user.id for r in message.reads):
            continue
        db.add(MessageRead(message_id=message.id, user_id=user.id))
    await db.commit()
    return await get_conversation(db, user, complaint.id)


# --------------------------------------------------------------------------- #
# Inbox
# --------------------------------------------------------------------------- #
async def list_conversations(db: AsyncSession, user: User) -> ConversationListOut:
    """List the conversations this user is authorized to participate in."""
    if user.role.name not in _CONVERSATION_ROLES:
        raise ComplaintAccessError

    stmt = (
        select(Conversation)
        .join(Conversation.complaint)
        .options(selectinload(Conversation.complaint))
    )
    if user.role.name == RoleName.CITIZEN.value:
        stmt = stmt.where(Complaint.user_id == user.id)
    elif user.role.name == RoleName.WARD_REPRESENTATIVE.value:
        stmt = stmt.where(Complaint.ward_id == user.ward_id)

    conversations = (
        (await db.execute(stmt.order_by(Conversation.created_at.desc()))).scalars().all()
    )
    conversation_ids = [c.id for c in conversations]
    if not conversation_ids:
        return ConversationListOut(items=[])

    last_rows = (
        await db.execute(
            select(Message.conversation_id, Message.body, Message.created_at, User.full_name)
            .join(Message.author)
            .where(Message.conversation_id.in_(conversation_ids))
            .order_by(Message.created_at.desc())
        )
    ).all()
    last_by_conversation: dict[uuid.UUID, dict] = {}
    for conversation_id, body, created_at, author_name in last_rows:
        if conversation_id not in last_by_conversation:
            last_by_conversation[conversation_id] = {
                "last_message": body,
                "last_message_at": created_at,
                "last_author_name": author_name,
            }

    unread_rows = (
        await db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.author_id != user.id,
                ~select(MessageRead.id)
                .where(
                    MessageRead.message_id == Message.id,
                    MessageRead.user_id == user.id,
                )
                .exists(),
            )
            .group_by(Message.conversation_id)
        )
    ).all()
    unread_by_conversation = {conversation_id: count for conversation_id, count in unread_rows}

    items: list[ConversationListItem] = []
    for conversation in conversations:
        last = last_by_conversation.get(conversation.id, {})
        items.append(
            ConversationListItem(
                complaint_id=conversation.complaint_id,
                complaint_title=(
                    conversation.complaint.title if conversation.complaint else "Complaint"
                ),
                complaint_status=conversation.complaint.status if conversation.complaint else None,
                last_message=last.get("last_message"),
                last_message_at=last.get("last_message_at"),
                last_author_name=last.get("last_author_name"),
                unread_count=unread_by_conversation.get(conversation.id, 0),
            )
        )
    items.sort(
        key=lambda item: item.last_message_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return ConversationListOut(items=items)


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
async def _ward_reps_for(db: AsyncSession, complaint: Complaint) -> list[User]:
    if complaint.ward_id is None:
        return []
    return list(
        (
            await db.execute(
                select(User).where(
                    User.ward_id == complaint.ward_id,
                    User.is_active.is_(True),
                    User.role.has(Role.name == RoleName.WARD_REPRESENTATIVE.value),
                )
            )
        )
        .scalars()
        .all()
    )


async def _notify_new_message(
    db: AsyncSession, complaint: Complaint, author: User, message: Message
) -> None:
    """Notify the message's recipients (never the author themselves) (Part 21)."""
    recipients: set[uuid.UUID] = set()
    if author.id == complaint.user_id:
        # A citizen update -> the complaint ward's representatives.
        for rep in await _ward_reps_for(db, complaint):
            if rep.id != author.id:
                recipients.add(rep.id)
    else:
        # A staff reply -> the complaint owner.
        owner = await db.get(User, complaint.user_id)
        if owner is not None and owner.is_active and owner.id != author.id:
            recipients.add(owner.id)

    for recipient_id in recipients:
        notification_service.create_notification(
            db,
            user_id=recipient_id,
            actor_id=author.id,
            notification_type=_NOTIFICATION_TYPE_MESSAGE,
            message_id=message.id,
            complaint_id=complaint.id,
            body=f"New message on '{complaint.title}'",
            title="New message",
            link=f"/messages/{complaint.id}",
        )


# --------------------------------------------------------------------------- #
# AI-assist drafts (never auto-sent)
# --------------------------------------------------------------------------- #
def _synthesize_draft(messages: list[Message], complaint_title: str) -> dict:
    if not messages:
        return {
            "summary": "No messages have been exchanged on this complaint yet.",
            "suggested_reply": "Thank you for your message. We will respond shortly.",
        }
    role_counts: dict[str, int] = {}
    for message in messages:
        role_counts[message.role] = role_counts.get(message.role, 0) + 1
    labels = {
        RoleName.CITIZEN.value: "from the citizen",
        RoleName.WARD_REPRESENTATIVE.value: "from the ward representative",
        RoleName.OFFICER.value: "from the officer",
        RoleName.ADMIN.value: "from the administrator",
    }
    description = []
    for role, count in role_counts.items():
        description.append(f"{count} message(s) {labels.get(role, role.lower())}")
    summary = (
        f"{len(messages)} message(s) on '{complaint_title}': {', '.join(description)}. "
        "Prepared from the conversation's real messages."
    )
    suggested_reply = (
        "Thank you for your message. We have noted your update and will review it and "
        "get back to you as soon as possible."
    )
    return {"summary": summary, "suggested_reply": suggested_reply}


async def generate_draft(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
    *,
    ai: AIService | None = None,
) -> AiDraftOut:
    """Generate a summary + suggested reply for the conversation (draft only).

    The returned draft is never stored or sent: it is a suggestion rendered for
    the authenticated user to review and post manually. The prompt explicitly
    instructs the model not to imitate a named official, and the final message is
    always authored by the real user.
    """
    complaint = await _load_complaint_for_participant(db, user, complaint_id)
    conversation = await _get_conversation_or_none(db, complaint.id)
    messages = conversation.messages if conversation is not None else []

    service = ai or get_ai_service()
    if service.is_configured:
        try:
            transcript = "\n".join(
                f"[{m.role}] {m.author.full_name if m.author else '?'}: {m.body}" for m in messages
            )
            system_prompt = (
                "You are a civic-complaint assistant drafting a *suggestion* for review. "
                "Write a short concise summary of the conversation and a suggested reply "
                "addressed to the citizen. Never claim to be, or write as, a specific named "
                "official — the response is drafted for a human to review and send. Keep the "
                "suggested reply under 3 sentences and ground everything in the provided "
                "conversation only."
            )
            result = await service.structured_completion(
                [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Complaint: {complaint.title}\n\nConversation:\n"
                        f"{transcript or '(no messages yet)'}",
                    },
                ],
                _AiDraft,
                temperature=0.2,
                max_tokens=300,
            )
            return AiDraftOut(
                summary=result.summary.strip(),
                suggested_reply=result.suggested_reply.strip(),
                draft=True,
                generated_by="groq",
            )
        except Exception:
            # Fall through to the deterministic draft on any provider failure.
            pass

    canned = _synthesize_draft(messages, complaint.title)
    return AiDraftOut(
        summary=canned["summary"],
        suggested_reply=canned["suggested_reply"],
        draft=True,
        generated_by="synthesized",
    )


__all__ = [
    "generate_draft",
    "get_conversation",
    "list_conversations",
    "mark_conversation_read",
    "send_message",
    "upload_attachment",
]
