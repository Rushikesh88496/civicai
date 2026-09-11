import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin


class DepartmentOverride(Base, UUIDMixin):
    """An officer's manual correction of a complaint's department (Part 13).

    When an authorized officer (OFFICER / ADMIN / WARD_REPRESENTATIVE) disagrees
    with the Routing Agent's recommendation they may override the department. Each
    override records the *previous* department, the *new* one, the officer's
    reason, who performed it (``override_by`` -> ``users.id``) and a timestamp, so
    the audit trail is complete and reversible.
    """

    __tablename__ = "department_overrides"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The department in effect before the override (or null if none was routed).
    old_department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The department the officer chose.
    new_department: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # The officer's stated reason for the change.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Who performed the override (an authorized officer/admin).
    override_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    overridden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="department_overrides")
    override_by_user = relationship("User", uselist=False)

    def __repr__(self) -> str:
        return (
            f"<DepartmentOverride {self.complaint_id} "
            f"{self.old_department} -> {self.new_department}>"
        )
