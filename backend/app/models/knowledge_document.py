"""Civic knowledge base document used by the Citizen AI Assistant (Part 25).

Each document is a small, citable unit of municipal policy / procedure text with
a stored pgvector embedding (BGE-small, 384-dim) for semantic retrieval. The RAG
pipeline matches a citizen's question to the nearest documents and the LLM
answers with only that context — every policy claim carries a source reference.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import KnowledgeCategory


def embedding_dim() -> int:
    """Return the configured embedding dimension (import-safe)."""
    return int(get_settings().EMBEDDING_DIM)


class KnowledgeDocument(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # Short section label (e.g. "SLA — Response Times").
    section: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[KnowledgeCategory] = mapped_column(
        Enum(KnowledgeCategory, name="knowledge_category"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Human-readable origin, e.g. "Council Policy CP-203 (v2, 2026)".
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    # pgvector embedding of title + content (BGE-small, 384-dim). Nullable so a
    # document can exist before embedding; retrieval only selects is_active rows
    # that have an embedding.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(embedding_dim()), nullable=True)

    def __repr__(self) -> str:
        return f"<KnowledgeDocument {self.title} ({self.category.value})>"
