"""priority engine v2: amplifiers, sla, new weights

Revision ID: a2f3b4c5d6e7
Revises: a1f2b3c4d5e6
Create Date: 2026-09-22 10:00:00.000000

Part 12 — Priority Engine v2 (deterministic 6-component model):

  * Adds ``risk_amplifiers`` (JSONB) and ``sla`` (JSONB) to
    ``complaint_priority_history`` so each score records the risk amplifiers
    fired on real evidence and the SEPARATE SLA/Escalation snapshot
    (a breached SLA never raises the score).
  * Reseeds ``priority_weights`` to the new six editable weights (severity 25,
    infrastructure exposure 20, affected population & report pressure 20,
    recurrence 15, weather 10, evidence confidence 10). The legacy keys
    ``location`` / ``crowd`` / ``time`` are replaced; ``weather`` keeps its key
    but only affects scores via the new engine.
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "a2f3b4c5d6e7"
down_revision: str | None = "a1f2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- complaint_priority_history: risk_amplifiers + sla -------------------- #
    op.add_column(
        "complaint_priority_history",
        sa.Column("risk_amplifiers", JSONB(), nullable=True),
    )
    op.add_column(
        "complaint_priority_history",
        sa.Column("sla", JSONB(), nullable=True),
    )

    # ---- priority_weights: reseed to the six new weights ---------------------- #
    weight_seed = [
        ("severity", "Severity / potential harm", 0.25),
        ("infrastructure", "Infrastructure exposure", 0.20),
        ("population", "Affected population & report pressure", 0.20),
        ("history", "Recurrence / incident pattern", 0.15),
        ("weather", "Weather / environmental risk", 0.10),
        ("evidence", "Evidence confidence", 0.10),
    ]
    op.execute("DELETE FROM priority_weights WHERE key IN ('location', 'crowd', 'time')")
    for key, label, weight in weight_seed:
        op.execute(
            sa.text(
                "INSERT INTO priority_weights (id, key, label, weight, is_active, "
                "created_at, updated_at) VALUES (:id, :key, :label, :weight, true, now(), now()) "
                "ON CONFLICT (key) DO UPDATE SET label = EXCLUDED.label, "
                "weight = EXCLUDED.weight, is_active = true, updated_at = now()"
            ).bindparams(id=uuid4(), key=key, label=label, weight=weight)
        )


def downgrade() -> None:
    op.drop_column("complaint_priority_history", "sla")
    op.drop_column("complaint_priority_history", "risk_amplifiers")

    # Restore the legacy six weights (best effort; the new engine no longer
    # consumes them).
    legacy_seed = [
        ("severity", "Severity", 0.30),
        ("weather", "Weather risk", 0.10),
        ("location", "Critical infrastructure proximity", 0.15),
        ("crowd", "Crowd pressure (population + reports)", 0.20),
        ("history", "Historical recurrence", 0.10),
        ("time", "Time unresolved", 0.15),
    ]
    op.execute("DELETE FROM priority_weights")
    for key, label, weight in legacy_seed:
        op.execute(
            sa.text(
                "INSERT INTO priority_weights (id, key, label, weight, is_active, "
                "created_at, updated_at) VALUES (:id, :key, :label, :weight, true, now(), now())"
            ).bindparams(id=uuid4(), key=key, label=label, weight=weight)
        )
