import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class Conversation(Base, UUIDMixin, TimestampMixin):
    """A complaint's conversation (Part 17).

    One conversation per complaint (1:1). Participation is gated by the service:
    the complaint's citizen owner, the representative of the complaint's ward,
    and officers / admins (via ``user_can_view``). ``Message`` rows carry a
    snapshot of the author's role at send time for rendering.
    """

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("complaint_id", name="uq_conversations_complaint_id"),)

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    complaint = relationship("Complaint", back_populates="conversation")
    messages = relationship(
        "Message",
        back_populates="conversation",
        uselist=True,
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    def __repr__(self) -> str:
        return f"<Conversation {self.id} complaint={self.complaint_id}>"
