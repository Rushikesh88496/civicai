"""enable postgis and pgvector extensions

Revision ID: cfbd4ce21b49
Revises:
Create Date: 2026-09-02 15:26:07.984434
"""

from collections.abc import Sequence

from alembic import op

revision: str = "cfbd4ce21b49"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')


def downgrade() -> None:
    op.execute('DROP EXTENSION IF EXISTS "vector"')
    op.execute("DROP EXTENSION IF EXISTS postgis")
