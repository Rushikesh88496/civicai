"""work_order_activities + work_order_photos + worker workflow timestamps

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-05 16:00:00.000000

Part 18 — Field Worker Application:
  * ``work_order_activities`` — append-only log of every field worker workflow
    step (accept / navigate / arrive / start / photo / notes / complete) with
    optional GPS capture and a ``geo_denied`` flag when device location was
    unavailable (privacy-respecting: coordinates only at explicit check-ins).
  * ``work_order_photos`` — before/after evidence photos uploaded by the worker
    (binaries in object storage; metadata only here).
  * ``work_orders`` gains ``accepted_at`` / ``started_at`` / ``completed_at`` /
    ``worker_notes``; ``worker_assignments`` gains ``accepted_at`` so the exact
    acceptance time is auditable even before the order moves to IN_PROGRESS.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_orders", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("work_orders", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "work_orders", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("work_orders", sa.Column("worker_notes", sa.Text(), nullable=True))

    op.add_column(
        "worker_assignments", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "work_order_photos",
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("worker_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("storage_backend", sa.String(length=20), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["worker_id"], ["field_workers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_work_order_photos_work_order_id"),
        "work_order_photos",
        ["work_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_order_photos_worker_id"), "work_order_photos", ["worker_id"], unique=False
    )

    op.create_table(
        "work_order_activities",
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("worker_id", sa.UUID(), nullable=False),
        sa.Column("activity_type", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geo_denied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("media_id", sa.UUID(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("client_ref", sa.String(length=64), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["media_id"], ["work_order_photos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["worker_id"], ["field_workers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "worker_id", "client_ref", name="uq_work_order_activities_worker_client_ref"
        ),
    )
    op.create_index(
        op.f("ix_work_order_activities_work_order_id"),
        "work_order_activities",
        ["work_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_order_activities_worker_id"),
        "work_order_activities",
        ["worker_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_work_order_activities_activity_type"),
        "work_order_activities",
        ["activity_type"],
        unique=False,
    )

    # Backfill has_before/has_after is derived at read time — nothing to do here.


def downgrade() -> None:
    op.drop_index(op.f("ix_work_order_photos_worker_id"), table_name="work_order_photos")
    op.drop_index(op.f("ix_work_order_photos_work_order_id"), table_name="work_order_photos")
    op.drop_table("work_order_photos")

    op.drop_index(
        op.f("ix_work_order_activities_activity_type"), table_name="work_order_activities"
    )
    op.drop_index(op.f("ix_work_order_activities_worker_id"), table_name="work_order_activities")
    op.drop_index(
        op.f("ix_work_order_activities_work_order_id"), table_name="work_order_activities"
    )
    op.drop_table("work_order_activities")

    op.drop_column("worker_assignments", "accepted_at")

    op.drop_column("work_orders", "worker_notes")
    op.drop_column("work_orders", "completed_at")
    op.drop_column("work_orders", "started_at")
    op.drop_column("work_orders", "accepted_at")
