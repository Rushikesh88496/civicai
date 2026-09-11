"""Citizen AI Assistant schemas (Part 25).

* ``AssistantAskIn`` - a single citizen question.
* ``AssistantSource`` - a knowledge-base source (title + reference + relevance).
* ``AssistantAnswerOut`` - the non-streaming answer with sources + provenance.
* ``AssistantMessageOut`` / ``AssistantConversationOut`` - persisted history.
* ``AssistantClearOut`` - result of clearing a conversation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class AssistantAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Optional ISO 639-1 language for the reply (Part 26). When omitted the
    # pipeline falls back to the citizen's profile preference, then auto-detects
    # from the question.
    language: str | None = Field(default=None, min_length=2, max_length=10)

    @field_validator("question")
    @classmethod
    def _strip_non_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Question cannot be empty or blank.")
        return stripped


class AssistantSource(BaseModel):
    reference: str
    title: str
    relevance: float = Field(ge=0.0, le=1.0)


class AssistantMessageOut(BaseModel):
    id: str
    role: str
    content: str
    sources: list[AssistantSource] = Field(default_factory=list)
    generated_by: str | None = None
    # The language the assistant answered in (Part 26).
    language: str | None = None
    created_at: datetime


class AssistantAnswerOut(BaseModel):
    answer: str
    sources: list[AssistantSource] = Field(default_factory=list)
    generated_by: str = "groq"
    used_rag: bool = False
    ai_prediction: bool = True
    disclaimer: str
    # Detected source language of the question + language the answer is in (Part 26).
    detected_language: str = "en"
    language: str = "en"


class AssistantConversationOut(BaseModel):
    messages: list[AssistantMessageOut] = Field(default_factory=list)
    disclaimer: str
    language: str | None = None


class AssistantClearOut(BaseModel):
    cleared: bool = True
    messages_deleted: int = 0
