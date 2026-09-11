"""security audit and ai governance

Revision ID: e4f5a6b7c8d9
Revises: e3e4f5a6b7c8
Create Date: 2026-09-07 14:00:00.000000

Part 28 — Security, Audit & AI Governance data model:

  * ``ai_decision_logs`` — append-only log of every AI/agent decision
    (triage, priority, routing, dispatch, vision) with model name, prompt
    version, confidence, tool calls and result.
  * ``evidence_checks`` — cross-check of an AI claim against ground-truth
    (GIS / tool / database) data; records match/mismatch + discrepancy.
  * ``human_overrides`` — officer overrides of AI decisions: original and
    new values, reason, actor, and optional link back to the decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "e3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_decision_logs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "complaint_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("tool_calls", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("result", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("is_override", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_decision_logs_complaint_id",
        "ai_decision_logs",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_decision_logs_agent_name",
        "ai_decision_logs",
        ["agent_name"],
        unique=False,
    )

    op.create_table(
        "evidence_checks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "complaint_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "decision_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("claim_type", sa.String(length=64), nullable=False),
        sa.Column("claimed_value", sa.Text(), nullable=False),
        sa.Column("actual_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("is_match", sa.Boolean(), nullable=False),
        sa.Column("discrepancy_pct", sa.Float(), nullable=True),
        sa.Column("evidence_data", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decision_id"], ["ai_decision_logs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_checks_complaint_id",
        "evidence_checks",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_checks_decision_id",
        "evidence_checks",
        ["decision_id"],
        unique=False,
    )

    op.create_table(
        "human_overrides",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "complaint_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "decision_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("override_type", sa.String(length=64), nullable=False),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("original_data", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("new_data", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decision_id"], ["ai_decision_logs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_human_overrides_complaint_id",
        "human_overrides",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        "ix_human_overrides_decision_id",
        "human_overrides",
        ["decision_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_human_overrides_decision_id", table_name="human_overrides")
    op.drop_index("ix_human_overrides_complaint_id", table_name="human_overrides")
    op.drop_table("human_overrides")

    op.drop_index("ix_evidence_checks_decision_id", table_name="evidence_checks")
    op.drop_index("ix_evidence_checks_complaint_id", table_name="evidence_checks")
    op.drop_table("evidence_checks")

    op.drop_index("ix_ai_decision_logs_agent_name", table_name="ai_decision_logs")
    op.drop_index("ix_ai_decision_logs_complaint_id", table_name="ai_decision_logs")
    op.drop_table("ai_decision_logs")
