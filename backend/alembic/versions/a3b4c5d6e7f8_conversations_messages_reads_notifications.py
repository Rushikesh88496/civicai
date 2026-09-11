"""conversations + messages + message_attachments + message_reads + notifications

Revision ID: a3b4c5d6e7f8
Revises: d6e7f8a9b0c1
Create Date: 2026-09-05 14:00:00.000000

Part 17 — Civic Communication:
  * ``conversations`` — one row per complaint (1:1). Participation is gated in
    the service against the complaint's owner citizen, the representative of the
    complaint's ward, and officers / admins.
  * ``messages`` (renamed from ``complaint_thread_messages``) — gains
    ``conversation_id`` (FK) alongside the legacy ``complaint_id`` (kept
    denormalized). Existing Part 16 messages get a conversation backfilled per
    complaint.
  * ``message_attachments`` — a file attached to a message; ``message_id`` is
    NULL while the upload is pending linkage to a sent message.
  * ``message_reads`` — one read receipt per (message, user).
  * ``notifications`` — an in-app notification produced when a new message is
    posted (staff reply -> citizen owner; citizen update -> ward representatives).
"""

import uuid as _uuid
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    op.create_table(
        "conversations",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("complaint_id", name="uq_conversations_complaint_id"),
    )
    op.create_index(
        op.f("ix_conversations_complaint_id"), "conversations", ["complaint_id"], unique=False
    )

    # Backfill one conversation per complaint that already has thread messages so
    # the rename + new FK can point every existing message at its conversation.
    distinct = connection.exec_driver_sql(
        "SELECT DISTINCT complaint_id FROM complaint_thread_messages"
    ).fetchall()
    for (complaint_id,) in distinct:
        connection.execute(
            sa.text(
                "INSERT INTO conversations (id, complaint_id, created_at, updated_at) "
                "VALUES (:id, :cid, now(), now())"
            ),
            {"id": _uuid.uuid4(), "cid": complaint_id},
        )

    op.drop_index(op.f("ix_complaint_thread_messages_role"), table_name="complaint_thread_messages")
    op.drop_index(
        op.f("ix_complaint_thread_messages_author_id"), table_name="complaint_thread_messages"
    )
    op.drop_index(
        op.f("ix_complaint_thread_messages_complaint_id"), table_name="complaint_thread_messages"
    )
    op.rename_table("complaint_thread_messages", "messages")

    op.add_column("messages", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_messages_conversation_id",
        "messages",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    connection.execute(
        sa.text(
            "UPDATE messages SET conversation_id = conversations.id "
            "FROM conversations WHERE conversations.complaint_id = messages.complaint_id"
        )
    )
    op.alter_column("messages", "conversation_id", nullable=False)
    op.create_index(
        op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False
    )
    op.create_index(op.f("ix_messages_complaint_id"), "messages", ["complaint_id"], unique=False)
    op.create_index(op.f("ix_messages_author_id"), "messages", ["author_id"], unique=False)
    op.create_index(op.f("ix_messages_role"), "messages", ["role"], unique=False)

    op.create_table(
        "message_attachments",
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("uploader_id", sa.UUID(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_message_attachments_message_id"),
        "message_attachments",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_message_attachments_complaint_id"),
        "message_attachments",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_message_attachments_uploader_id"),
        "message_attachments",
        ["uploader_id"],
        unique=False,
    )

    op.create_table(
        "message_reads",
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_reads_message_user"),
    )
    op.create_index(
        op.f("ix_message_reads_message_id"), "message_reads", ["message_id"], unique=False
    )
    op.create_index(op.f("ix_message_reads_user_id"), "message_reads", ["user_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("notification_type", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("complaint_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.String(length=255), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_notifications_complaint_id"), "notifications", ["complaint_id"], unique=False
    )
    op.create_index(
        op.f("ix_notifications_notification_type"),
        "notifications",
        ["notification_type"],
        unique=False,
    )
    op.create_index(op.f("ix_notifications_is_read"), "notifications", ["is_read"], unique=False)
    op.create_index(op.f("ix_notifications_actor_id"), "notifications", ["actor_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_actor_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_is_read"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_notification_type"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_complaint_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(op.f("ix_message_reads_user_id"), table_name="message_reads")
    op.drop_index(op.f("ix_message_reads_message_id"), table_name="message_reads")
    op.drop_table("message_reads")

    op.drop_index(op.f("ix_message_attachments_uploader_id"), table_name="message_attachments")
    op.drop_index(op.f("ix_message_attachments_complaint_id"), table_name="message_attachments")
    op.drop_index(op.f("ix_message_attachments_message_id"), table_name="message_attachments")
    op.drop_table("message_attachments")

    op.drop_index(op.f("ix_messages_role"), table_name="messages")
    op.drop_index(op.f("ix_messages_author_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_complaint_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_constraint("fk_messages_conversation_id", "messages", type_="foreignkey")
    op.drop_column("messages", "conversation_id")
    op.rename_table("messages", "complaint_thread_messages")
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

    op.drop_index(op.f("ix_conversations_complaint_id"), table_name="conversations")
    op.drop_table("conversations")
