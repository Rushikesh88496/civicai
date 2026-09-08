"""predictive hotspot model registry

Revision ID: 9a8b7c6d5e4f
Revises: 8f4e9d2c1b0a
Create Date: 2026-09-06 09:30:00.000000

Part 23: add the ``predictive_models`` table that persists the trained
Predictive Civic Hotspots model artifact metadata (version, artifacts file,
evaluation metrics, training config) so every model is recorded, versioned and
exactly one is ``is_active`` at a time.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9a8b7c6d5e4f"
down_revision: Union[str, None] = "8f4e9d2c1b0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "predictive_models",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("artifact_filename", sa.String(length=255), nullable=False),
        sa.Column("metrics", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("config", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("trained_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trained_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("version", name="uq_predictive_models_version"),
    )
    op.create_index(
        "ix_predictive_models_is_active", "predictive_models", ["is_active"], unique=False
    )
    op.create_index(
        "ix_predictive_models_version", "predictive_models", ["version"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_predictive_models_version", table_name="predictive_models")
    op.drop_index("ix_predictive_models_is_active", table_name="predictive_models")
    op.drop_table("predictive_models")