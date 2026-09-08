"""Pydantic schemas for complaint conversations, attachments and AI drafts (Part 17)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ComplaintStatus


# --------------------------------------------------------------------------- #
# Attachments
# --------------------------------------------------------------------------- #
class AttachmentOut(BaseModel):
    """A file attached to a conversation message (or pending for one)."""

    id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    url: str | None = None
    created_at: datetime


class AttachmentUploadOut(AttachmentOut):
    """Result of uploading a file before it is attached to a message."""

    # Same fields as AttachmentOut; kept as a distinct alias for clarity.


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #
class MessageCreateIn(BaseModel):
    """Payload for posting a new message on a complaint conversation."""

    body: str = Field(..., min_length=1, max_length=4000)
    attachment_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class MessageReadReceipt(BaseModel):
    """Who has read a message and when."""

    user_id: uuid.UUID
    user_name: str | None = None
    read_at: datetime


class MessageOut(BaseModel):
    """One message in a complaint conversation."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    complaint_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str | None = None
    role: str
    body: str
    created_at: datetime
    attachments: list[AttachmentOut] = Field(default_factory=list)
    read_by: list[MessageReadReceipt] = Field(default_factory=list)
    read_by_all: bool = False
    is_read_by_me: bool = False


class ConversationOut(BaseModel):
    """A complaint conversation plus its (authorized) messages."""

    complaint_id: uuid.UUID
    complaint_title: str
    complaint_status: ComplaintStatus | None = None
    messages: list[MessageOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Inbox
# --------------------------------------------------------------------------- #
class ConversationListItem(BaseModel):
    """A single conversation preview for the messages inbox."""

    complaint_id: uuid.UUID
    complaint_title: str
    complaint_status: ComplaintStatus | None = None
    last_message: str | None = None
    last_message_at: datetime | None = None
    last_author_name: str | None = None
    unread_count: int = 0


class ConversationListOut(BaseModel):
    """The participant's conversations, latest activity first."""

    items: list[ConversationListItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# AI-assist drafts
# --------------------------------------------------------------------------- #
class AiDraftOut(BaseModel):
    """An AI-generated draft reply / summary for the authorized user to review.

    ``draft`` is always True: the text is a *suggestion rendered for review* and
    is never sent automatically. The only way a message is created is when the
    real, authenticated user posts it through the message endpoint — AI never
    impersonates an official by auto-sending.
    """

    summary: str
    suggested_reply: str
    draft: bool = True
    generated_by: str = "synthesized"


__all__ = [
    "AttachmentOut",
    "AttachmentUploadOut",
    "AiDraftOut",
    "ConversationListItem",
    "ConversationListOut",
    "ConversationOut",
    "MessageCreateIn",
    "MessageOut",
    "MessageReadReceipt",
]
