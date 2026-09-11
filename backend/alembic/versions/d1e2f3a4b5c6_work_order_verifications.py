"""work_order_verifications

Revision ID: d1e2f3a4b5c6
Revises: b4c5d6e7f8a9
Create Date: 2026-09-06 12:00:00.000000

Part 19 — AI Resolution Verification:
  * ``work_order_verifications`` — persisted outcome of comparing a work order's
    BEFORE / AFTER photos against the original complaint. Stores the structured
    columns (repair_evidence / remaining_issue / confidence / verification_status
    / human_review_required / source) plus the authorized human's review
    (reviewed_by / reviewed_at / review_note). The agent run remains traceable in
    ``agent_runs`` (agent="verify_repair").
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_order_verifications",
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("before_photo_id", sa.UUID(), nullable=True),
        sa.Column("after_photo_id", sa.UUID(), nullable=True),
        sa.Column("repair_evidence", sa.Text(), nullable=True),
        sa.Column("remaining_issue", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("human_review_required", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
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
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["after_photo_id"], ["work_order_photos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["before_photo_id"], ["work_order_photos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_work_order_verifications_work_order_id"),
        "work_order_verifications",
        ["work_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_order_verifications_complaint_id"),
        "work_order_verifications",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_order_verifications_verification_status"),
        "work_order_verifications",
        ["verification_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_order_verifications_human_review_required"),
        "work_order_verifications",
        ["human_review_required"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_work_order_verifications_human_review_required"),
        table_name="work_order_verifications",
    )
    op.drop_index(
        op.f("ix_work_order_verifications_verification_status"),
        table_name="work_order_verifications",
    )
    op.drop_index(
        op.f("ix_work_order_verifications_complaint_id"), table_name="work_order_verifications"
    )
    op.drop_index(
        op.f("ix_work_order_verifications_work_order_id"), table_name="work_order_verifications"
    )
    op.drop_table("work_order_verifications")
