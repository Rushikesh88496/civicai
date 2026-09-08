"""work_orders + work_order_status_history + worker_assignments + field_workers

Revision ID: c685cc39bb71
Revises: be6083718a2c
Create Date: 2026-09-04 10:04:57.016355

Part 14 — Work Orders & Autonomous Dispatch:
  * ``work_orders`` — one row per field-work order created for a complaint
    (complaint, incident label, routing ``department``, dynamic priority bucket,
    denormalized location, SLA / due, recommended action, status, ETA +
    ``eta_source``, current worker, creator/approver).
  * ``work_order_status_history`` — append-only audit trail of every officer
    action (dispatch / approve / assign / reassign / escalate / reject / close)
    with from→to status and acting user.
  * ``worker_assignments`` — worker ↔ order assignments (one active per order)
    used both to enforce deterministic, explainable selection and to compute
    each worker's current workload.
  * ``field_workers`` — added ``home_latitude`` / ``home_longitude`` (distance
    ranking), ``skill_tags`` / ``equipment`` (skill + equipment criteria) and
    ``max_active_orders`` (per-worker workload ceiling).

Note: autogenerate compares a fresh SQLAlchemy metadata against the live DB and
reported several PostGIS / unrelated diffs (spatial_ref_sys, geometry indexes,
``ix_complaint_correlations_decided_by``). Those are artifacts of the offline
metadata and are intentionally NOT included here.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c685cc39bb71"
down_revision: Union[str, None] = "be6083718a2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_orders",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("incident", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column("location_lat", sa.Float(), nullable=True),
        sa.Column("location_lon", sa.Float(), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("eta_minutes", sa.Integer(), nullable=True),
        sa.Column("eta_source", sa.String(length=16), nullable=True),
        sa.Column("worker_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["worker_id"], ["field_workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_work_orders_complaint_id"), "work_orders", ["complaint_id"], unique=False
    )
    op.create_index(op.f("ix_work_orders_department"), "work_orders", ["department"], unique=False)
    op.create_index(op.f("ix_work_orders_priority"), "work_orders", ["priority"], unique=False)
    op.create_index(op.f("ix_work_orders_status"), "work_orders", ["status"], unique=False)
    op.create_index(op.f("ix_work_orders_worker_id"), "work_orders", ["worker_id"], unique=False)

    op.create_table(
        "work_order_status_history",
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_work_order_status_history_work_order_id"),
        "work_order_status_history",
        ["work_order_id"],
        unique=False,
    )

    op.create_table(
        "worker_assignments",
        sa.Column("work_order_id", sa.UUID(), nullable=False),
        sa.Column("worker_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("assigned_by", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_id"], ["field_workers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_worker_assignments_work_order_id"),
        "worker_assignments",
        ["work_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_worker_assignments_worker_id"), "worker_assignments", ["worker_id"], unique=False
    )

    op.add_column("field_workers", sa.Column("home_latitude", sa.Float(), nullable=True))
    op.add_column("field_workers", sa.Column("home_longitude", sa.Float(), nullable=True))
    op.add_column(
        "field_workers",
        sa.Column(
            "skill_tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "field_workers",
        sa.Column(
            "equipment",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("field_workers", sa.Column("max_active_orders", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("field_workers", "max_active_orders")
    op.drop_column("field_workers", "equipment")
    op.drop_column("field_workers", "skill_tags")
    op.drop_column("field_workers", "home_longitude")
    op.drop_column("field_workers", "home_latitude")

    op.drop_index(op.f("ix_worker_assignments_worker_id"), table_name="worker_assignments")
    op.drop_index(op.f("ix_worker_assignments_work_order_id"), table_name="worker_assignments")
    op.drop_table("worker_assignments")

    op.drop_index(
        op.f("ix_work_order_status_history_work_order_id"), table_name="work_order_status_history"
    )
    op.drop_table("work_order_status_history")

    op.drop_index(op.f("ix_work_orders_worker_id"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_status"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_priority"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_department"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_complaint_id"), table_name="work_orders")
    op.drop_table("work_orders")
