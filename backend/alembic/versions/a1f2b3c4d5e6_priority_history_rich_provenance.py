"""priority history rich provenance columns

Revision ID: a1f2b3c4d5e6
Revises: d7f8e9a2b3c4
Create Date: 2026-09-22 08:00:00.000000

Part 12 (rebuilt) — the deterministic Priority Engine now records the honest
data-readiness and full provenance of every computation. ``complaint_priority_history``
gains:

* ``data_status`` — READY / PARTIAL / INSUFFICIENT_DATA (how much real data the
  score was based on).
* ``components`` — the rich per-component breakdown (score / max / unit / status /
  source / calculated_at) so the UI can reconstruct the score cards from history.
* ``sources`` — provenance of every source actually queried (Open-Meteo, PostGIS
  registry, PostGIS historical/reports, complaint fields).
* ``reason`` — why the computation ran (``manual``, ``auto-context``, ...).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1f2b3c4d5e6"
down_revision: str | None = "d7f8e9a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE complaint_priority_history ADD COLUMN data_status VARCHAR(32)"
    )
    op.execute(
        "ALTER TABLE complaint_priority_history ADD COLUMN components JSONB"
    )
    op.execute(
        "ALTER TABLE complaint_priority_history ADD COLUMN sources JSONB"
    )
    op.execute(
        "ALTER TABLE complaint_priority_history ADD COLUMN reason VARCHAR(255)"
    )
    # Historical rows predate the readable statuses; treat them as honest unknowns.
    op.execute(
        "UPDATE complaint_priority_history SET data_status = 'PARTIAL'"
        " WHERE data_status IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE complaint_priority_history DROP COLUMN IF EXISTS reason")
    op.execute("ALTER TABLE complaint_priority_history DROP COLUMN IF EXISTS sources")
    op.execute("ALTER TABLE complaint_priority_history DROP COLUMN IF EXISTS components")
    op.execute("ALTER TABLE complaint_priority_history DROP COLUMN IF EXISTS data_status")


# Keep the schema-hygiene check happy (this migration only alters existing rows).
def _noop() -> None:  # pragma: no cover
    return None
