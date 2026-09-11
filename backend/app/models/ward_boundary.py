import uuid

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin

_WGS84 = 4326


class WardBoundary(Base, UUIDMixin, TimestampMixin):
    """A polygon boundary for a municipal ward (Part 10).

    The ``geom`` column stores a POLYGON (or MULTIPOLYGON) in EPSG:4326 so a
    point can be tested for containment (``ST_Contains``) to determine which ward
    a coordinate falls inside. The GiST spatial index is created explicitly in
    the migration (controlled name, ``spatial_index=False`` here).

    ``is_demo`` marks boundaries that are illustrative placeholders rather than
    authoritative municipal boundaries — such records are surfaced to users with
    the ``GIS_DEMO_LABEL`` ("DEMO DATA") and are never presented as authoritative.
    """

    __tablename__ = "ward_boundaries"

    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wards.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=_WGS84, spatial_index=False),
        nullable=False,
    )

    ward = relationship("Ward", back_populates="boundary")

    def __repr__(self) -> str:
        return f"<WardBoundary ward={self.ward_id} is_demo={self.is_demo}>"
