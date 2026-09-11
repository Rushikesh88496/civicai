import uuid

from sqlalchemy import Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import WorkerStatus


class FieldWorker(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "field_workers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    specialty: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[WorkerStatus] = mapped_column(
        Enum(WorkerStatus, name="worker_status"),
        default=WorkerStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    # --- Part 14: worker-selection inputs (availability/skill/distance/workload/equipment)
    # Home-base coordinates used for deterministic distance-based ranking.
    home_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Human-readable registered/base location (e.g. "Kothrud, Pune, Maharashtra").
    # Describes where the worker is stationed — NOT a live GPS position.
    base_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Skill / capability tags relevant to recommended work (e.g. ["drainage-jetting"]).
    skill_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Equipment the worker can operate (e.g. ["jetting-rig", "excavator"]).
    equipment: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Upper bound on simultaneous active orders; None -> settings default.
    max_active_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user = relationship("User", back_populates="field_worker")
    department = relationship("Department", back_populates="field_workers")
    work_orders = relationship(
        "WorkOrder",
        back_populates="worker",
        foreign_keys="WorkOrder.worker_id",
        uselist=True,
    )
    assignments = relationship("WorkerAssignment", back_populates="worker", uselist=True)

    def __repr__(self) -> str:
        return f"<FieldWorker user={self.user_id} status={self.status.value}>"
