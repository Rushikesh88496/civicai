"""ward_boundaries, critical_locations and spatial indexes

Revision ID: f7e8d9c0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-04 10:00:00.000000

Part 10 — GIS / Ward detection & spatial intelligence:
  * ``critical_location_category`` enum (HOSPITAL / SCHOOL / BUS_STOP /
    POLICE_STATION / FIRE_STATION / ROAD / TRANSPORT / OTHER).
  * ``ward_boundaries`` table — one POLYGON per ward in EPSG:4326, with an
    ``is_demo`` flag to label illustrative (non-authoritative) boundaries. GiST
    index ``idx_ward_boundaries_geom`` for point-in-polygon containment.
  * ``critical_locations`` table — public/critical facilities with a POINT in
    EPSG:4326 and an ``is_demo`` flag. GiST index ``idx_critical_locations_geom``
    for radius (ST_DWithin) queries.

The ``complaints.locations`` GiST index (``idx_complaint_locations_geom``) from
Part 4 is unchanged and reused for any complaint-space spatial query.
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f7e8d9c0a1b2"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WGS84 = 4326


def _category_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "HOSPITAL",
        "SCHOOL",
        "BUS_STOP",
        "POLICE_STATION",
        "FIRE_STATION",
        "ROAD",
        "TRANSPORT",
        "OTHER",
        name="critical_location_category",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(
        "HOSPITAL",
        "SCHOOL",
        "BUS_STOP",
        "POLICE_STATION",
        "FIRE_STATION",
        "ROAD",
        "TRANSPORT",
        "OTHER",
        name="critical_location_category",
    ).create(bind, checkfirst=True)

    op.create_table(
        "ward_boundaries",
        sa.Column("ward_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="POLYGON",
                srid=_WGS84,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["ward_id"], ["wards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ward_id"),
    )
    op.create_index(
        "idx_ward_boundaries_geom",
        "ward_boundaries",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "critical_locations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", _category_enum(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=_WGS84,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                spatial_index=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_critical_locations_category"),
        "critical_locations",
        ["category"],
        unique=False,
    )
    op.create_index(
        "idx_critical_locations_geom",
        "critical_locations",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_critical_locations_geom")
    op.drop_index(op.f("ix_critical_locations_category"), table_name="critical_locations")
    op.drop_table("critical_locations")

    op.execute("DROP INDEX IF EXISTS idx_ward_boundaries_geom")
    op.drop_table("ward_boundaries")

    bind = op.get_bind()
    postgresql.ENUM(name="critical_location_category").drop(bind, checkfirst=True)
