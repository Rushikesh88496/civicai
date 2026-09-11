"""Human-in-the-loop assignment provenance (Part 32).

Adds the columns that let the system always distinguish an *AI
recommendation* from an *official assignment*:

* ``work_orders.recommended_worker_id`` — the worker the Dispatch Agent
  recommended (frozen at draft time; ``worker_id`` may later change).
* ``worker_assignments.origin`` — how each assignment was created:
  ``AI_RECOMMENDATION`` (officer accepted the AI pick) /
  ``OFFICER_OVERRIDE`` (officer chose a different worker) / ``MANUAL``.

The draft work order is never an assignment by itself; only a
``worker_assignments`` row is the official, audit-logged assignment.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "d6e7f8a9b0c3"
down_revision = "31a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column(
            "recommended_worker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("field_workers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_work_orders_recommended_worker_id"),
        "work_orders",
        ["recommended_worker_id"],
        unique=False,
    )
    op.add_column(
        "worker_assignments",
        sa.Column("origin", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("worker_assignments", "origin")
    op.drop_index(op.f("ix_work_orders_recommended_worker_id"), table_name="work_orders")
    op.drop_column("work_orders", "recommended_worker_id")
