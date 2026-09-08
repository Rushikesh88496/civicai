"""complaint_thread_messages (authorized citizen<->representative conversations)

Revision ID: d6e7f8a9b0c1
Revises: c685cc39bb71
Create Date: 2026-09-04 12:00:00.000000

Part 16 — Ward Representative Portal conversations:
  * ``complaint_thread_messages`` — one row per message in an authorized
    citizen ↔ representative thread. Each message belongs to a complaint, is
    authored by either the complaint's owner (citizen) or an authorized staff
    member (WARD_REPRESENTATIVE / OFFICER / ADMIN) whose ward / role grants them
    access. ``role`` snapshots the author's role at send time so threads render
    without extra joins; visibility is enforced on read by comparing the
    requesting user against the complaint's owner and ward.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c685cc39bb71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "complaint_thread_messages",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_complaint_thread_messages_complaint_id"),
        "complaint_thread_messages",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_complaint_thread_messages_author_id"),
        "complaint_thread_messages",
        ["author_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_complaint_thread_messages_role"),
        "complaint_thread_messages",
        ["role"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_complaint_thread_messages_role"), table_name="complaint_thread_messages")
    op.drop_index(
        op.f("ix_complaint_thread_messages_author_id"), table_name="complaint_thread_messages"
    )
    op.drop_index(
        op.f("ix_complaint_thread_messages_complaint_id"), table_name="complaint_thread_messages"
    )
    op.drop_table("complaint_thread_messages")
