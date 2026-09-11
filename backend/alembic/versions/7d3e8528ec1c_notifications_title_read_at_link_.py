"""notifications title read_at link channel payload work_order_id

Revision ID: 7d3e8528ec1c
Revises: e2e3f4a5b6c7
Create Date: 2026-09-06 02:53:12.950988

Part 21: extend the notifications table with the fields needed by the
centralized notification system:
- ``title``    — short human-readable headline
- ``read_at``  — timestamp marking when the row was marked read
- ``link``     — deep link target for the UI (client-side)
- ``channel``  — delivery channel ("inbox" or "email"; default "inbox")
- ``payload``  — JSON envelope for structured event data
- ``work_order_id`` — FK to work_orders (SET NULL on delete)
- composite index ``ix_notifications_user_unread`` for the badge query
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "7d3e8528ec1c"
down_revision: Union[str, None] = "e2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOTIFICATIONS_FK = "fk_notifications_work_order_id_work_orders"


def upgrade() -> None:
    op.add_column("notifications", sa.Column("work_order_id", sa.UUID(), nullable=True))
    op.add_column("notifications", sa.Column("title", sa.String(length=180), nullable=True))
    op.add_column("notifications", sa.Column("link", sa.String(length=255), nullable=True))
    op.add_column(
        "notifications",
        sa.Column("channel", sa.String(length=16), server_default="inbox", nullable=False),
    )
    op.add_column("notifications", sa.Column("payload", sa.JSON(), nullable=True))
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_notifications_user_unread", "notifications", ["user_id", "is_read"], unique=False
    )
    op.create_index(
        op.f("ix_notifications_work_order_id"), "notifications", ["work_order_id"], unique=False
    )
    op.create_foreign_key(
        _NOTIFICATIONS_FK,
        "notifications",
        "work_orders",
        ["work_order_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_NOTIFICATIONS_FK, "notifications", type_="foreignkey")
    op.drop_index(op.f("ix_notifications_work_order_id"), table_name="notifications")
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_column("notifications", "read_at")
    op.drop_column("notifications", "payload")
    op.drop_column("notifications", "channel")
    op.drop_column("notifications", "link")
    op.drop_column("notifications", "title")
    op.drop_column("notifications", "work_order_id")
