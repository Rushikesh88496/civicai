"""complaint_department_history + department_overrides

Revision ID: be6083718a2c
Revises: b3c4d5e6f7a8
Create Date: 2026-09-04 09:23:25.741148

Part 13 — Department Routing Agent:
  * ``complaint_department_history`` — one append-only row per deterministic
    department routing computation (primary department, optional secondary
    departments, reason, confidence, ambiguous flag and the exact inputs used).
  * ``department_overrides`` — append-only audit trail of officer overrides
    (old / new department, reason, override_by -> users.id, timestamp).

Note: autogenerate compares a fresh SQLAlchemy metadata against the live DB and
reported several PostGIS / unrelated diffs (spatial_ref_sys, geometry indexes,
an index on complaint_correlations.decided_by). Those are artifacts of the
offline metadata and are intentionally NOT included here.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "be6083718a2c"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "complaint_department_history",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("primary_department", sa.String(length=64), nullable=False),
        sa.Column("secondary_departments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("routing_reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("ambiguous", sa.Boolean(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        op.f("ix_complaint_department_history_complaint_id"),
        "complaint_department_history",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_complaint_department_history_primary_department"),
        "complaint_department_history",
        ["primary_department"],
        unique=False,
    )

    op.create_table(
        "department_overrides",
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("old_department", sa.String(length=64), nullable=True),
        sa.Column("new_department", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("override_by", sa.UUID(), nullable=False),
        sa.Column(
            "overridden_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["override_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_department_overrides_complaint_id"),
        "department_overrides",
        ["complaint_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_department_overrides_new_department"),
        "department_overrides",
        ["new_department"],
        unique=False,
    )
    op.create_index(
        op.f("ix_department_overrides_override_by"),
        "department_overrides",
        ["override_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_department_overrides_override_by"), table_name="department_overrides")
    op.drop_index(op.f("ix_department_overrides_new_department"), table_name="department_overrides")
    op.drop_index(op.f("ix_department_overrides_complaint_id"), table_name="department_overrides")
    op.drop_table("department_overrides")

    op.drop_index(
        op.f("ix_complaint_department_history_primary_department"),
        table_name="complaint_department_history",
    )
    op.drop_index(
        op.f("ix_complaint_department_history_complaint_id"),
        table_name="complaint_department_history",
    )
    op.drop_table("complaint_department_history")
