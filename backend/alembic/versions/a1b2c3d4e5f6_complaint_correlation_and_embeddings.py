"""complaint correlation, embeddings and correlation_status column

Revision ID: a1b2c3d4e5f6
Revises: 5c9d1f3a0e21
Create Date: 2026-09-04 09:00:00.000000

Part 9 — Duplicate / incident correlation:
  * ``correlation_status`` enum + column on ``complaints`` (NEW_INCIDENT /
    POSSIBLE_DUPLICATE / CONFIRMED_DUPLICATE).
  * ``complaint_correlations`` table — candidate duplicate pairs written by the
    correlation agent, with a ``correlation_match_status`` PENDING/CONFIRMED/
    REJECTED lifecycle that officers flip.
  * ``complaint_embeddings`` table — pgvector ``vector(384)`` embedding per
    complaint, provided by the local Sentence-Transformer (fastembed), with an
    HNSW vector_cosine_ops index for efficient semantic similarity search.

The geospatial "nearby" query reuses the existing PostGIS GiST index
``idx_complaint_locations_geom`` on ``complaint_locations.geom`` (created in the
Part 4 location migration); no new spatial index is required there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ENUM

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "5c9d1f3a0e21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _correlation_status_enum() -> ENUM:
    return postgresql.ENUM(
        "NEW_INCIDENT",
        "POSSIBLE_DUPLICATE",
        "CONFIRMED_DUPLICATE",
        name="correlation_status",
        create_type=False,
    )


def _match_status_enum() -> ENUM:
    return postgresql.ENUM(
        "PENDING",
        "CONFIRMED",
        "REJECTED",
        name="correlation_match_status",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # ---- enum types --------------------------------------------------------
    postgresql.ENUM(
        "NEW_INCIDENT",
        "POSSIBLE_DUPLICATE",
        "CONFIRMED_DUPLICATE",
        name="correlation_status",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "PENDING",
        "CONFIRMED",
        "REJECTED",
        name="correlation_match_status",
    ).create(bind, checkfirst=True)

    # ---- complaints.correlation_status -------------------------------------
    op.add_column(
        "complaints",
        sa.Column("correlation_status", _correlation_status_enum(), nullable=True),
    )
    op.create_index(
        op.f("ix_complaints_correlation_status"),
        "complaints",
        ["correlation_status"],
        unique=False,
    )

    # ---- complaint_correlations --------------------------------------------
    op.create_table(
        "complaint_correlations",
        sa.Column("source_complaint_id", sa.UUID(), nullable=False),
        sa.Column("target_complaint_id", sa.UUID(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("time_diff_hours", sa.Float(), nullable=True),
        sa.Column("category_match", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", _match_status_enum(), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["source_complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_complaint_correlations_source_complaint_id"),
        "complaint_correlations",
        ["source_complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_complaint_correlations_target_complaint_id"),
        "complaint_correlations",
        ["target_complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_complaint_correlations_status"),
        "complaint_correlations",
        ["status"],
        unique=False,
    )

    # ---- complaint_embeddings (pgvector) -----------------------------------
    op.create_table(
        "complaint_embeddings",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("text_input", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
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
    # HNSW index for fast cosine-distance semantic search.
    op.execute(
        "CREATE INDEX idx_complaint_embeddings_embedding_hnsw "
        "ON complaint_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_complaint_embeddings_embedding_hnsw")
    op.drop_table("complaint_embeddings")

    op.drop_index(op.f("ix_complaint_correlations_status"), table_name="complaint_correlations")
    op.drop_index(
        op.f("ix_complaint_correlations_target_complaint_id"),
        table_name="complaint_correlations",
    )
    op.drop_index(
        op.f("ix_complaint_correlations_source_complaint_id"),
        table_name="complaint_correlations",
    )
    op.drop_table("complaint_correlations")

    op.drop_index(op.f("ix_complaints_correlation_status"), table_name="complaints")
    op.drop_column("complaints", "correlation_status")

    bind = op.get_bind()
    ENUM(name="correlation_match_status").drop(bind, checkfirst=True)
    ENUM(name="correlation_status").drop(bind, checkfirst=True)
