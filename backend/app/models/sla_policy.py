import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin


class SlaPolicy(Base, UUIDMixin, TimestampMixin):
    """A configurable SLA policy rule (Part 20).

    Replaces the dispatch agent's hard-coded ``P1=24 / P2=48 / P3=72 / P4=168``
    mapping with runtime-editable rules keyed by the most specific match of
    ``(priority, department, category)``. A rule may scope to *any* of those
    dimensions and leave the rest as wildcards (``NULL`` = matches anything), so
    operators can tune a department, a category or a single priority without
    touching code or redeploying.

    ``at_risk_percent`` is the fraction of the SLA window after which an open
    order is considered AT_RISK (e.g. ``0.75`` = last quarter of the window).
    ``escalate_on_breach`` controls whether the monitoring agent raises a breach
    notification to staff when the deadline passes.
    """

    __tablename__ = "sla_policies"

    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # One of DynamicPriority values (P1_CRITICAL..P4_LOW). NULL = any priority.
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # One of DepartmentCode values. NULL = any department.
    department: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # One of ComplaintCategory values. NULL = any category.
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Deadline length in hours applied to an order's start (approval) time.
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    # Fraction (0..1) of the window at which an order enters the at-risk warning.
    at_risk_percent: Mapped[float] = mapped_column(Float, nullable=False)
    # Raise a breach notification to staff when the deadline passes.
    escalate_on_breach: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    # Inactive rules are ignored when resolving a deadline.
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true", index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        scope = ",".join(str(v) or "*" for v in (self.priority, self.department, self.category))
        return f"<SlaPolicy {scope} -> {self.sla_hours}h active={self.active}>"
