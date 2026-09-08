"""complaint status history table and lifecycle statuses

Revision ID: 8f2c11a93b42
Revises: 157fcd6527b7
Create Date: 2026-09-02 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8f2c11a93b42"
down_revision: str | None = "157fcd6527b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The linear lifecycle statuses added by Part 5 (Complaint Tracking & Timeline).
# The legacy statuses OPEN / IN_PROGRESS / RESOLVED / ESCALATED already exist.
_NEW_STATUSES = [
    "SUBMITTED",
    "AI_ANALYZING",
    "EVIDENCE_VERIFIED",
    "WARD_IDENTIFIED",
    "PRIORITIZED",
    "DEPARTMENT_ASSIGNED",
    "WORK_ORDER_CREATED",
    "WORKER_ASSIGNED",
    "CITIZEN_VERIFIED",
    "CLOSED",
]


def upgrade() -> None:
    bind = op.get_bind()
    for value in _NEW_STATUSES:
        bind.execute(sa.text(f"ALTER TYPE complaint_status ADD VALUE IF NOT EXISTS '{value}'"))

    op.create_table(
        "complaint_status_history",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "OPEN",
                "IN_PROGRESS",
                "RESOLVED",
                "ESCALATED",
                "SUBMITTED",
                "AI_ANALYZING",
                "EVIDENCE_VERIFIED",
                "WARD_IDENTIFIED",
                "PRIORITIZED",
                "DEPARTMENT_ASSIGNED",
                "WORK_ORDER_CREATED",
                "WORKER_ASSIGNED",
                "CITIZEN_VERIFIED",
                "CLOSED",
                name="complaint_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_complaint_status_history_complaint_id"),
        "complaint_status_history",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_complaint_status_history_status"),
        "complaint_status_history",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_complaint_status_history_actor_id"),
        "complaint_status_history",
        ["actor_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_complaint_status_history_actor_id"), table_name="complaint_status_history"
    )
    op.drop_index(op.f("ix_complaint_status_history_status"), table_name="complaint_status_history")
    op.drop_index(
        op.f("ix_complaint_status_history_complaint_id"), table_name="complaint_status_history"
    )
    op.drop_table("complaint_status_history")
    # Enum values are not removed on downgrade (requires Postgres 15+ per-value
    # drop and would break any rows that use them).
