"""real infrastructure asset registry provenance

Revision ID: a4f5b6c7d8e9
Revises: a2f3b4c5d6e7
Create Date: 2026-09-23 16:40:00.000000

Part 37: the predictive-maintenance asset registry is populated from the REAL
verified facility registry (``critical_locations``) instead of demo rows. To do
that the ``infrastructure_assets`` table gains the same provenance columns as
the facility registry (``source`` / ``source_dataset`` / ``source_url`` /
``source_id``) plus a partial unique index on ``(source, source_id)`` so the
asset sync is idempotent and deduplicated on a real source key — an asset is
never created twice from the same real-world record, and a run can never
fabricate provenance.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a4f5b6c7d8e9"
down_revision: Union[str, None] = "a2f3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE infrastructure_assets ADD COLUMN source VARCHAR(64)")
    op.execute("ALTER TABLE infrastructure_assets ADD COLUMN source_dataset VARCHAR(255)")
    op.execute("ALTER TABLE infrastructure_assets ADD COLUMN source_url TEXT")
    op.execute("ALTER TABLE infrastructure_assets ADD COLUMN source_id VARCHAR(255)")
    op.create_index(
        "ix_infrastructure_assets_source", "infrastructure_assets", ["source"], unique=False
    )
    op.create_index(
        "ix_infrastructure_assets_source_id", "infrastructure_assets", ["source_id"], unique=False
    )
    op.create_index(
        "uix_infrastructure_assets_source_source_id",
        "infrastructure_assets",
        ["source", "source_id"],
        unique=True,
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uix_infrastructure_assets_source_source_id", table_name="infrastructure_assets"
    )
    op.drop_index("ix_infrastructure_assets_source_id", table_name="infrastructure_assets")
    op.drop_index("ix_infrastructure_assets_source", table_name="infrastructure_assets")
    op.execute("ALTER TABLE infrastructure_assets DROP COLUMN IF EXISTS source_id")
    op.execute("ALTER TABLE infrastructure_assets DROP COLUMN IF EXISTS source_url")
    op.execute("ALTER TABLE infrastructure_assets DROP COLUMN IF EXISTS source_dataset")
    op.execute("ALTER TABLE infrastructure_assets DROP COLUMN IF EXISTS source")
