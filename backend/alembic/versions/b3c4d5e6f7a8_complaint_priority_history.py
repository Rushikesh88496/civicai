"""complaint_priority_history + dynamic_priority enum

Revision ID: b3c4d5e6f7a8
Revises: f7e8d9c0a1b2
Create Date: 2026-09-04 11:00:00.000000

Part 12 — Dynamic Priority & Risk Engine:
  * ``dynamic_priority`` enum (P1_CRITICAL / P2_HIGH / P3_MEDIUM / P4_LOW).
  * ``complaint_priority_history`` table — one append-only row per deterministic
    priority computation (score 0..100, bucket, previous score, changed flag and
    the JSON inputs / factor breakdown used to produce it), so the UI can show a
    score history and detect significant re-prioritizations.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "f7e8d9c0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _priority_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "P1_CRITICAL",
        "P2_HIGH",
        "P3_MEDIUM",
        "P4_LOW",
        name="dynamic_priority",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(
        "P1_CRITICAL",
        "P2_HIGH",
        "P3_MEDIUM",
        "P4_LOW",
        name="dynamic_priority",
    ).create(bind, checkfirst=True)

    op.create_table(
        "complaint_priority_history",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("priority", _priority_enum(), nullable=False),
        sa.Column("previous_score", sa.Integer(), nullable=True),
        sa.Column("changed", sa.Boolean(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_complaint_priority_history_complaint_id"),
        "complaint_priority_history",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_complaint_priority_history_priority"),
        "complaint_priority_history",
        ["priority"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_complaint_priority_history_priority"),
        table_name="complaint_priority_history",
    )
    op.drop_index(
        op.f("ix_complaint_priority_history_complaint_id"),
        table_name="complaint_priority_history",
    )
    op.drop_table("complaint_priority_history")

    bind = op.get_bind()
    postgresql.ENUM(name="dynamic_priority").drop(bind, checkfirst=True)
