"""agent_runs and agent_events tables

Revision ID: 5c9d1f3a0e21
Revises: 8f2c11a93b42
Create Date: 2026-09-03 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5c9d1f3a0e21"
down_revision: str | None = "8f2c11a93b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # New enum used by agent_runs.status (agent lifecycle). Postgres value
    # additions for existing enum types are handled by ALTER TYPE.
    postgresql.ENUM("RUNNING", "SUCCEEDED", "FAILED", name="agent_status").create(
        bind, checkfirst=True
    )

    op.create_table(
        "agent_runs",
        sa.Column("complaint_id", sa.UUID(), nullable=True),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "RUNNING", "SUCCEEDED", "FAILED", name="agent_status", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("structured_result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_runs_agent"), "agent_runs", ["agent"], unique=False)
    op.create_index(
        op.f("ix_agent_runs_complaint_id"), "agent_runs", ["complaint_id"], unique=False
    )
    op.create_index(op.f("ix_agent_runs_status"), "agent_runs", ["status"], unique=False)

    op.create_table(
        "agent_events",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("event", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_events_event"), "agent_events", ["event"], unique=False)
    op.create_index(op.f("ix_agent_events_run_id"), "agent_events", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_events_run_id"), table_name="agent_events")
    op.drop_index(op.f("ix_agent_events_event"), table_name="agent_events")
    op.drop_table("agent_events")

    op.drop_index(op.f("ix_agent_runs_status"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_complaint_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_agent"), table_name="agent_runs")
    op.drop_table("agent_runs")

    bind = op.get_bind()
    postgresql.ENUM("RUNNING", "SUCCEEDED", "FAILED", name="agent_status").drop(
        bind, checkfirst=True
    )
