import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.session import Base
from app.models.base import UUIDMixin


def embedding_dim() -> int:
    """Return the configured embedding dimension (import-safe)."""
    return int(get_settings().EMBEDDING_DIM)


class ComplaintEmbedding(Base, UUIDMixin):
    """A stored vector embedding for a complaint's text (Part 9).

    Text (description + category) is embedded with the configured local Sentence
    Transformer (fastembed) and persisted here as a pgvector ``vector`` so the
    correlation agent can find semantically-similar complaints with a cosine
    query. The column is indexed with HNSW (vector_cosine_ops) in the migration.
    """

    __tablename__ = "complaint_embeddings"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    # What was embedded (the exact text). Useful for auditing / re-embedding.
    text_input: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(embedding_dim()), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="embedding")

    def __repr__(self) -> str:
        return (
            f"<ComplaintEmbedding {self.id} complaint={self.complaint_id} "
            f"{self.model} dim={self.dimensions}>"
        )
