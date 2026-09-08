"""Persistent assistant conversation for the Citizen AI Assistant (Part 25).

A citizen gets exactly one conversation (``assistant_conversations.user_id`` is
unique). Every turn is stored as an ``AssistantMessage`` (``role`` in
{"user", "assistant"}) so the assistant can show history, support follow-ups and
restore a conversation after refresh. ``sources`` records the knowledge-base
references the assistant cited for that turn.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class AssistantConversation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "assistant_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    messages = relationship(
        "AssistantMessage",
        back_populates="conversation",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="AssistantMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<AssistantConversation user={self.user_id} messages={len(self.messages)}>"


class AssistantMessage(Base, UUIDMixin):
    __tablename__ = "assistant_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "user" | "assistant"
    role: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Knowledge-base references cited in the assistant answer ([] when none).
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # How the answer was produced: "groq" (LLM) or "synthesized" (fallback).
    generated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # ISO 639-1 language the message is in (Part 26). Null on legacy rows.
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation = relationship("AssistantConversation", back_populates="messages")

    def __repr__(self) -> str:
        return f"<AssistantMessage {self.role} {self.id.hex[:8]}>"
