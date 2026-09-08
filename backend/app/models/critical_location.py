from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Enum, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TimestampMixin, UUIDMixin
from app.models.enums import CriticalLocationCategory

_WGS84 = 4326


class CriticalLocation(Base, UUIDMixin, TimestampMixin):
    """A critical / public facility with a known geo point (Part 10).

    Hospitals, schools, bus stops, roads-of-interest and other critical
    infrastructure are stored with a PostGIS POINT (EPSG:4326) so the GIS service
    can answer "what facilities are near this coordinate?" via ``ST_DWithin``.
    The GiST spatial index on ``geom`` is created explicitly in the migration.

    ``is_demo`` marks record that are illustrative placeholders (not an
    authoritative facility directory); they carry the ``GIS_DEMO_LABEL``.
    """

    __tablename__ = "critical_locations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[CriticalLocationCategory] = mapped_column(
        Enum(CriticalLocationCategory, name="critical_location_category"),
        nullable=False,
        index=True,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINT", srid=_WGS84, spatial_index=False),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<CriticalLocation {self.name} ({self.category.value})>"
