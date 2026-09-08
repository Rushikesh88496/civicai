import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin
from app.models.enums import AgentStatus


class AgentRun(Base, UUIDMixin):
    """A single execution of an agent against a complaint (Part 7).

    Tracks which agent ran, the underlying model, its lifecycle status, the
    wall-clock duration and — once the graph finishes — the structured JSON
    result (or an error message if it failed). The complaint that was analyzed
    may be null because exactly one run is created per triage request.
    """

    __tablename__ = "agent_runs"

    complaint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"),
        default=AgentStatus.RUNNING,
        nullable=False,
        index=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structured_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    complaint = relationship("Complaint", back_populates="agent_runs")
    events = relationship(
        "AgentEvent", back_populates="run", uselist=True, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.id} {self.agent} ({self.status.value})>"
