import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.base import UUIDMixin

# WGS 84 — the latitude/longitude coordinate system used by GPS.
_WGS84 = 4326


class ComplaintLocation(Base, UUIDMixin):
    """GPS / manually-entered location for a complaint.

    The PostGIS geometry column (`geom`) stores a POINT in EPSG:4326 so the
    location can be queried spatially. Latitude/longitude/geopoint_status are
    kept as plain columns for convenience; ``source`` records whether it came
    from device GPS or manual entry.
    """

    __tablename__ = "complaint_locations"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # Browser/device GPS horizontal accuracy in metres, when the coordinate came
    # from navigator.geolocation (Part 31). None for manual map picks.
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Geographic POINT in EPSG:4326 (SRID 4326). The GiST spatial index is
    # created explicitly in the migration (controlled name).
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINT", srid=_WGS84, spatial_index=False), nullable=True
    )
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "gps" when taken from navigator.geolocation, "manual" when typed by hand.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # True when the submitter denied / had no GPS permission and typed coords manually.
    geopoint_denied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    complaint = relationship("Complaint", back_populates="complaint_location")

    def __repr__(self) -> str:
        return f"<ComplaintLocation {self.id} ({self.latitude:.5f}, {self.longitude:.5f})>"
