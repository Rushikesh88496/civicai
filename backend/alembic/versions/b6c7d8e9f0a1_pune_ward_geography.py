"""Pune-only ward geography (4 operational corridors)

Revision ID: b6c7d8e9f0a1
Revises: b5a4c3d2e1f0
Create Date: 2026-09-12 10:00:00.000000

Replaces the illustrative Hyderabad bounding-box reference zones (created by
``31a2b3c4d5e6`` as a tessellating 2x2 grid over the old demo box
17.40..17.50 lat / 78.35..78.49 lon) with four real, documented CivicAgent
operational wards for Pune, Maharashtra, India:

* ``WARD-1`` -- Kondhwa (south Pune): Kondhwa, Bibvewadi, Kondhwa Khurd,
  Kondhwa Budruk, NIBM, Yewalewadi.
* ``WARD-2`` -- Kothrud (west Pune): Kothrud, Karve Nagar, Paud Road side and
  the Erandwane/Kothrud boundary areas.
* ``WARD-3`` -- Hadapsar (east-south Pune): Hadapsar, Mundhwa and the
  Magarpatta side.
* ``WARD-4`` -- Viman Nagar (north-east Pune): Viman Nagar, Kalyani Nagar,
  Nagar Road side and adjoining Pune East.

Each ward now carries its administrative geography (city ``Pune`` / state
``Maharashtra`` / country ``India``), a real 4326 polygon boundary whose
vertices are anchored on the verified locality coordinates above (rounded to a
project-specific operational zone, NOT the full official PMC ward tessellation),
an ``ST_Centroid`` anchor/label point and ``is_active`` true. The polygons are
mutually non-overlapping with small documented gaps, so PostGIS
point-in-polygon (``ST_Contains``) resolves a complaint or worker GPS point to
at most one ward and reports *none* for points outside all four (rendered by
the UI as "Outside CivicAgent operational wards").

The migration is additive + idempotent: it only ever touches the four reference
wards (by code), their boundaries and demo (``is_demo = true``) critical-location
placeholders -- never user, complaint, work-order or ML data.

The legacy demo critical facilities (City Central Hospital, Riverside Primary
School, Market Street Bus Stop, ...) seeded at Hyderabad coordinates are
removed; the platform now sources real nearby infrastructure from OSM (Overpass)
with an explicit "unavailable" fallback instead of hardcoded demo POIs.
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa

from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: str | None = "b5a4c3d2e1f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WGS84 = 4326

# code -> (name, description, WKT polygon)
# WKT rings are (longitude latitude) pairs. Vertices are anchored on verified
# Pune locality coordinates; they deliberately do NOT tessellate the full PMC.
_PUNE_REFERENCE_WARDS: list[tuple[str, str, str, str]] = [
    (
        "WARD-1",
        "Ward 1 — Kondhwa",
        "Kondhwa ward — Kondhwa, Bibvewadi, Kondhwa Khurd, Kondhwa Budruk, "
        "NIBM and Yewalewadi (south Pune).",
        (
            "POLYGON(("
            "73.8520 18.4540,73.8420 18.4360,73.8720 18.4210,73.9250 18.4200,"
            "73.9410 18.4620,73.9200 18.4840,73.8800 18.4860,73.8550 18.4740,"
            "73.8520 18.4540))"
        ),
    ),
    (
        "WARD-2",
        "Ward 2 — Kothrud",
        "Kothrud ward — Kothrud, Karve Nagar, Paud Road and the "
        "Erandwane/Kothrud boundary areas (west Pune).",
        (
            "POLYGON(("
            "73.8480 18.5170,73.7880 18.5160,73.7780 18.4990,73.7860 18.4820,"
            "73.7980 18.4720,73.8360 18.4780,73.8480 18.4860,73.8500 18.5080,"
            "73.8480 18.5170))"
        ),
    ),
    (
        "WARD-3",
        "Ward 3 — Hadapsar",
        "Hadapsar ward — Hadapsar, Mundhwa and the Magarpatta side (east-south Pune).",
        (
            "POLYGON(("
            "73.8960 18.4870,73.9520 18.4880,73.9520 18.5420,73.9100 18.5440,"
            "73.8960 18.5160,73.8960 18.4870))"
        ),
    ),
    (
        "WARD-4",
        "Ward 4 — Viman Nagar",
        "Viman Nagar ward — Viman Nagar, Kalyani Nagar, Nagar Road and "
        "adjoining Pune East (north-east Pune).",
        (
            "POLYGON(("
            "73.8620 18.5880,73.9600 18.5890,73.9560 18.5480,73.9020 18.5450,"
            "73.8700 18.5450,73.8620 18.5880))"
        ),
    ),
]


def upgrade() -> None:
    bind = op.get_bind()

    # --- administrative geography on wards -------------------------------- #
    op.add_column(
        "wards",
        sa.Column("city", sa.String(length=100), server_default="Pune", nullable=False),
    )
    op.add_column(
        "wards",
        sa.Column("state", sa.String(length=100), server_default="Maharashtra", nullable=False),
    )
    op.add_column(
        "wards",
        sa.Column("country", sa.String(length=100), server_default="India", nullable=False),
    )

    # --- label anchor point on ward boundaries ---------------------------- #
    op.add_column(
        "ward_boundaries",
        sa.Column(
            "centroid",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=_WGS84,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                spatial_index=False,
            ),
            nullable=True,
        ),
    )

    for code, name, description, wkt in _PUNE_REFERENCE_WARDS:
        # Idempotent metadata update (no-op when the reference wards are absent).
        bind.execute(
            sa.text(
                "UPDATE wards SET name = :name, description = :desc, "
                "city = 'Pune', state = 'Maharashtra', country = 'India', "
                "is_active = TRUE, updated_at = now() WHERE code = :code"
            ),
            {"name": name, "desc": description, "code": code},
        )
        # Idempotent boundary replacement + centroid for the reference wards.
        bind.execute(
            sa.text(
                "UPDATE ward_boundaries SET is_demo = FALSE, "
                "geom = ST_SetSRID(ST_GeomFromText(:wkt), :srid), "
                "centroid = ST_SetSRID(ST_Centroid(ST_GeomFromText(:wkt)), :srid), "
                "name = :bname, updated_at = now() "
                "WHERE ward_id IN (SELECT id FROM wards WHERE code = :code)"
            ),
            {
                "wkt": wkt,
                "srid": _WGS84,
                "bname": f"{name} boundary",
                "code": code,
            },
        )

    # Remove the legacy Hyderabad demo facility placeholders. Idempotent.
    bind.execute(sa.text("DELETE FROM critical_locations WHERE is_demo = TRUE"))


def downgrade() -> None:
    bind = op.get_bind()

    # Best-effort: restore the demo framing for the reference boundaries (the
    # original Hyderabad tessellation is not recoverable, so the Pune polygons
    # are kept but clearly flagged as demo again).
    for code, _name, _description, _wkt in _PUNE_REFERENCE_WARDS:
        bind.execute(
            sa.text(
                "UPDATE ward_boundaries SET is_demo = TRUE, updated_at = now() "
                "WHERE ward_id IN (SELECT id FROM wards WHERE code = :code)"
            ),
            {"code": code},
        )

    op.drop_column("ward_boundaries", "centroid")
    op.drop_column("wards", "country")
    op.drop_column("wards", "state")
    op.drop_column("wards", "city")
