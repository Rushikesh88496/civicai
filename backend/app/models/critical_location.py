from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import CriticalLocationCategory, InfrastructureDataStatus

_WGS84 = 4326


class CriticalLocation(Base, UUIDMixin, TimestampMixin):
    """A critical / public facility with a known geo point (Part 10).

    Hospitals, schools, bus stops, roads-of-interest and other critical
    infrastructure are stored with a PostGIS POINT (EPSG:4326) so the GIS service
    can answer "what facilities are near this coordinate?" via ``ST_DWithin``.
    The GiST spatial index on ``geom`` is created explicitly in the migration.

    Since the Real Nearby Infrastructure pipeline (Part 35) this is the verified
    facility registry: every record carries provenance (``source`` /
    ``source_dataset`` / ``source_url`` / ``source_id``), a data-quality
    ``verification_status``, a ``last_verified_at`` freshness stamp and optional
    structured ``metadata``. Records without resolvable coordinates are kept as
    ``PENDING_VERIFICATION`` registry candidates with NULL lat/long/geom so a
    fresh dataset never fabricates positions.

    ``is_demo`` marks illustrative placeholders (never produced by the real
    pipeline); they carry the ``GIS_DEMO_LABEL``.
    """

    __tablename__ = "critical_locations"
    __table_args__ = (
        Index(
            "uix_critical_locations_source_source_id",
            "source",
            "source_id",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[CriticalLocationCategory] = mapped_column(
        Enum(CriticalLocationCategory, name="critical_location_category"),
        nullable=False,
        index=True,
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Part 35 registry provenance + data-quality fields.
    source: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_dataset: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[InfrastructureDataStatus] = mapped_column(
        Enum(InfrastructureDataStatus, name="infrastructure_data_status"),
        nullable=False,
        default=InfrastructureDataStatus.FOUND,
        index=True,
    )
    last_verified_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    asset_metadata: Mapped[dict | None] = mapped_column(
        JSONB, name="metadata", nullable=True
    )
    ward_id: Mapped[object | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wards.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=_WGS84, spatial_index=False),
        nullable=True,
    )

    ward = relationship("Ward", back_populates="critical_locations", lazy="selectin")

    def __repr__(self) -> str:
        return f"<CriticalLocation {self.name} ({self.category.value})>"
