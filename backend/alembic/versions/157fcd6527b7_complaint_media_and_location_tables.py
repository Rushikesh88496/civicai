"""complaint media and location tables

Revision ID: 157fcd6527b7
Revises: 621f36f8c889
Create Date: 2026-09-02 19:10:21.376467
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa

from alembic import op

revision: str = "157fcd6527b7"
down_revision: str | None = "621f36f8c889"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# New complaint categories introduced by the multimodal submission flow.
_NEW_CATEGORIES = ["WATER_LEAK", "FLOODING", "GARBAGE", "DRAINAGE", "FALLEN_TREE"]


def upgrade() -> None:
    # Extend the existing complaint_category ENUM with the Part 4 categories.
    # (PostgreSQL 12+ permits ALTER TYPE ... ADD VALUE inside a transaction as
    # long as the new values are not used in the same transaction, which they
    # are not here.)
    bind = op.get_bind()
    for value in _NEW_CATEGORIES:
        bind.execute(sa.text(f"ALTER TYPE complaint_category ADD VALUE IF NOT EXISTS '{value}'"))

    op.create_table(
        "complaint_locations",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                spatial_index=False,
            ),
            nullable=True,
        ),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("geopoint_denied", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("complaint_id"),
    )
    op.create_index(
        "idx_complaint_locations_geom",
        "complaint_locations",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_table(
        "complaint_media",
        sa.Column("complaint_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("media_type", sa.Enum("IMAGE", "VIDEO", name="media_type"), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("storage_backend", sa.String(length=20), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_complaint_media_complaint_id"), "complaint_media", ["complaint_id"], unique=False
    )
    op.create_index(
        op.f("ix_complaint_media_user_id"), "complaint_media", ["user_id"], unique=False
    )
    # NOTE: 'spatial_ref_sys' is a PostGIS system table — it is intentionally NOT in
    # Python metadata and must never be dropped by Autogenerate.


def downgrade() -> None:
    op.drop_index(op.f("ix_complaint_media_user_id"), table_name="complaint_media")
    op.drop_index(op.f("ix_complaint_media_complaint_id"), table_name="complaint_media")
    op.drop_table("complaint_media")
    op.drop_index(
        "idx_complaint_locations_geom", table_name="complaint_locations", postgresql_using="gist"
    )
    op.drop_table("complaint_locations")
    # Note: enum values are not removed on downgrade as dropping individual
    # values requires Postgres 15+ and would break existing rows.
