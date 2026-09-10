"""field worker base location

Revision ID: b5a4c3d2e1f0
Revises: a9b8c7d6e5f4
Create Date: 2026-09-10 16:05:00.000000

Adds ``base_location`` to ``field_workers`` — the human-readable registered
base station of a field worker (e.g. "Kothrud, Pune, Maharashtra"). This is a
descriptive label for the worker's base/registered location that complements
the existing ``home_latitude`` / ``home_longitude`` coordinates and is NEVER a
live GPS position. Column only — the 25 seeded worker coordinates and
``base_location`` values are reconciled idempotently by the dev seed script.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b5a4c3d2e1f0"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("field_workers", sa.Column("base_location", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("field_workers", "base_location")