import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import VerificationStatus


class WorkOrderVerification(Base, UUIDMixin, TimestampMixin):
    """A persisted AI repair-verification for a completed work order (Part 19).

    The Resolution-Verification agent compares the complaint description and the
    worker's BEFORE / AFTER photos and records, as structured columns:

    * ``repair_evidence`` — what the model observed that shows the fix.
    * ``remaining_issue`` — anything that still looks unresolved.
    * ``confidence`` (0..1) — how sure the model is.
    * ``verification_status`` — VERIFIED / PARTIALLY_RESOLVED / NOT_RESOLVED /
      NEEDS_HUMAN_REVIEW after the deterministic safety gates were applied.
    * ``human_review_required`` — whether an authorized human must sign off
      (always true for non-VERIFIED outcomes and for critical-priority orders).

    ``source`` records how the outcome was produced: ``"groq"`` (multimodal
    model) or ``"pixel-diff"`` (deterministic guard that the AFTER photo is
    identical to the BEFORE photo — no repair is visible). The full agent run
    remains traceable in ``agent_runs`` / ``agent_events`` (agent="verify_repair").

    ``reviewed_by`` / ``reviewed_at`` / ``review_note`` capture the authorized
    human's appraisal: either CONFIRM_VERIFIED (certify the repair) or
    REQUIRES_FOLLOWUP (which reopens the work order).
    """

    __tablename__ = "work_order_verifications"

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized so verification state can be queried by complaint directly.
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The two evidence photos compared (nullable until photos exist).
    before_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_order_photos.id", ondelete="SET NULL"),
        nullable=True,
    )
    after_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_order_photos.id", ondelete="SET NULL"),
        nullable=True,
    )

    repair_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    remaining_issue: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        "verification_status",
        String(32),
        default=VerificationStatus.NEEDS_HUMAN_REVIEW,
        nullable=False,
        index=True,
    )
    human_review_required: Mapped[bool] = mapped_column(
        "human_review_required",
        Boolean,
        default=True,
        nullable=False,
        index=True,
    )
    # Outcome source: "groq" (multimodal model) or "pixel-diff" (deterministic
    # unchanged-photo guard that short-circuits the AI call).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="groq")

    # Authorized human review (CONFIRM_VERIFIED / REQUIRES_FOLLOWUP).
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    work_order = relationship("WorkOrder", back_populates="verifications")
    complaint = relationship("Complaint")
    before_photo = relationship("WorkOrderPhoto", foreign_keys=[before_photo_id])
    after_photo = relationship("WorkOrderPhoto", foreign_keys=[after_photo_id])
    reviewed_by_user = relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self) -> str:
        return f"<WorkOrderVerification {self.id} {self.verification_status.value}>"
