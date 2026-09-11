"""reference wards and location accuracy

Revision ID: 31a2b3c4d5e6
Revises: e4f5a6b7c8d9
Create Date: 2026-09-08 10:00:00.000000

Part 31 — genuinely empty civic platform:

* ``complaint_locations.accuracy_m`` — GPS horizontal accuracy (metres) captured
  from the browser/device when a citizen reports from real coordinates.
* Four REFERENCE wards (WARD 1 .. WARD 4) with illustrative (``is_demo``) polygon
  boundaries that tessellate the demo bounding box (17.40..17.50, 78.35..78.49).
  The migration is additive + idempotent: it never touches existing wards, users
  or complaints. Legacy demo wards (W-001..W-003) and demo operational data are
  removed by the documented dev-reset script, not by this migration, because
  RESTRICT foreign keys from existing demo complaints would fail mid-upgrade.

The four boundaries cover only the demo box, so a coordinate inside the box maps
to exactly one ward via PostGIS ``ST_Contains`` and every coordinate outside it
maps to none.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "31a2b3c4d5e6"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WGS84 = 4326

# code -> (fixed id, name, description, WKT polygon)
# WKT rings are (longitude latitude) pairs; the four boxes tessellate the box.
_REFERENCE_WARDS: list[tuple[str, str, str, str, str]] = [
    (
        "WARD-1",
        "a0000000-0000-0000-0000-000000000001",
        "Ward 1",
        "South-west reference ward.",
        "POLYGON((78.35 17.40,78.42 17.40,78.42 17.45,78.35 17.45,78.35 17.40))",
    ),
    (
        "WARD-2",
        "a0000000-0000-0000-0000-000000000002",
        "Ward 2",
        "South-east reference ward.",
        "POLYGON((78.42 17.40,78.49 17.40,78.49 17.45,78.42 17.45,78.42 17.40))",
    ),
    (
        "WARD-3",
        "a0000000-0000-0000-0000-000000000003",
        "Ward 3",
        "North-west reference ward.",
        "POLYGON((78.35 17.45,78.42 17.45,78.42 17.50,78.35 17.50,78.35 17.45))",
    ),
    (
        "WARD-4",
        "a0000000-0000-0000-0000-000000000004",
        "Ward 4",
        "North-east reference ward.",
        "POLYGON((78.42 17.45,78.49 17.45,78.49 17.50,78.42 17.50,78.42 17.45))",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "complaint_locations",
        sa.Column("accuracy_m", sa.Float(), nullable=True),
    )

    for code, ward_id, name, description, wkt in _REFERENCE_WARDS:
        # Ward (unique by code, idempotent). Explicit CASTs keep asyncpg's
        # prepared-statement type inference unambiguous (varchar vs. text).
        bind.execute(
            sa.text(
                "INSERT INTO wards (id, name, code, description, is_active, created_at, updated_at) "
                "SELECT CAST(:wid AS UUID), CAST(:name AS VARCHAR), CAST(:code AS VARCHAR), "
                "CAST(:desc AS TEXT), TRUE, now(), now() "
                "WHERE NOT EXISTS (SELECT 1 FROM wards WHERE code = CAST(:code AS VARCHAR))"
            ),
            {"wid": ward_id, "name": name, "code": code, "desc": description},
        )
        # Boundary (unique by ward_id, idempotent).
        bind.execute(
            sa.text(
                "INSERT INTO ward_boundaries "
                "(id, ward_id, name, is_demo, geom, created_at, updated_at) "
                "SELECT CAST(:bid AS UUID), CAST(:wid AS UUID), CAST(:bname AS VARCHAR), TRUE, "
                "ST_SetSRID(ST_GeomFromText(:wkt), :srid), now(), now() "
                "WHERE NOT EXISTS "
                "(SELECT 1 FROM ward_boundaries WHERE ward_id = CAST(:wid AS UUID))"
            ),
            {
                "bid": _boundary_id(ward_id),
                "wid": ward_id,
                "bname": f"{name} boundary",
                "wkt": wkt,
                "srid": _WGS84,
            },
        )


def downgrade() -> None:
    for code, ward_id, _name, _description, _wkt in _REFERENCE_WARDS:
        op.execute(
            sa.text("DELETE FROM ward_boundaries WHERE ward_id = :wid"),
            {"wid": ward_id},
        )
        op.execute(
            sa.text("DELETE FROM wards WHERE code = :code"),
            {"code": code},
        )
    op.drop_column("complaint_locations", "accuracy_m")


def _boundary_id(ward_id: str) -> str:
    # Deterministic sibling UUID for the boundary row (distinct namespace).
    return "b" + ward_id[1:]
