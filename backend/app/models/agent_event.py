import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin


class AgentEvent(Base, UUIDMixin):
    """Append-only trace event emitted by an agent execution (Part 7).

    Records the milestone (e.g. ``triage.started``, ``triage.completed``,
    ``validate.retrying``, ``persist.succeeded``) along with an optional JSON
    payload (e.g. the model request/result at that stage). Useful for
    observability and replaying how an agent reached a decision.
    """

    __tablename__ = "agent_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run = relationship("AgentRun", back_populates="events")

    def __repr__(self) -> str:
        return f"<AgentEvent {self.id} run={self.run_id} {self.event}>"
