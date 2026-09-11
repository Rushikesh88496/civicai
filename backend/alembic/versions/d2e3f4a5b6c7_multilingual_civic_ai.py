"""multilingual civic AI — language columns

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-07 09:00:00.000000

Part 26 — Multilingual Civic AI (English / Hindi / Marathi):

  * ``complaints.language`` — ISO 639-1 code of the citizen's complaint text
    (``en`` / ``hi`` / ``mr``), computed by the deterministic language pipeline
    at submission time and reused downstream (triage, priority, notification
    translation). Null before Part 26 rows are simple English.
  * ``user_profiles.language`` — the citizen's persisted UI/assistant preference
    (used by the frontend language selector and as the default assistant reply
    language). Null means "use automatic / English".

Both columns are nullable and unconstrained-code so a malformed/mixed input can
continue to be stored without a schema error; detection normalizes to the three
supported codes or ``en``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("complaints", sa.Column("language", sa.String(length=10), nullable=True))
    op.add_column("user_profiles", sa.Column("language", sa.String(length=10), nullable=True))
    op.add_column("assistant_messages", sa.Column("language", sa.String(length=10), nullable=True))
    op.create_index("ix_complaints_language", "complaints", ["language"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_complaints_language", table_name="complaints")
    op.drop_column("assistant_messages", "language")
    op.drop_column("user_profiles", "language")
    op.drop_column("complaints", "language")
