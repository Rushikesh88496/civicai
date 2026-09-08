"""sla_policies

Revision ID: e2e3f4a5b6c7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-06 14:00:00.000000

Part 20 — Configurable SLA Monitoring:
  * ``sla_policies`` — the runtime-editable SLA rulebook. Each rule is a
    specificity match over (priority, department, category) with a deadline
    (``sla_hours``) and an at-risk warning threshold (``at_risk_percent``).
    Replaces the dispatch agent's hard-coded P1=24/P2=48/P3=72/P4=168 mapping.
  * Seeds the four built-in priority defaults so existing behavior is preserved
    out-of-the-box; officers can add more specific department/category rules on
    top and the resolution service picks the most specific match.
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "e2e3f4a5b6c7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sla_policies",
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=True),
        sa.Column("department", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("sla_hours", sa.Integer(), nullable=False),
        sa.Column("at_risk_percent", sa.Float(), nullable=False),
        sa.Column(
            "escalate_on_breach", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sla_policies_priority"), "sla_policies", ["priority"], unique=False)
    op.create_index(
        op.f("ix_sla_policies_department"), "sla_policies", ["department"], unique=False
    )
    op.create_index(op.f("ix_sla_policies_category"), "sla_policies", ["category"], unique=False)
    op.create_index(op.f("ix_sla_policies_active"), "sla_policies", ["active"], unique=False)

    # Built-in defaults: pure priority rules (24/48/72/168h) with the at-risk
    # warning fired in the final quarter of the window.
    sla_policies = sa.table(
        "sla_policies",
        sa.column("id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("priority", sa.String()),
        sa.column("department", sa.String()),
        sa.column("category", sa.String()),
        sa.column("sla_hours", sa.Integer()),
        sa.column("at_risk_percent", sa.Float()),
        sa.column("escalate_on_breach", sa.Boolean()),
        sa.column("active", sa.Boolean()),
    )
    defaults = [
        {"name": "Default P1 (24h)", "priority": "P1_CRITICAL", "sla_hours": 24},
        {"name": "Default P2 (48h)", "priority": "P2_HIGH", "sla_hours": 48},
        {"name": "Default P3 (72h)", "priority": "P3_MEDIUM", "sla_hours": 72},
        {"name": "Default P4 (168h)", "priority": "P4_LOW", "sla_hours": 168},
    ]
    op.bulk_insert(
        sla_policies,
        [
            {
                "id": uuid4(),
                "name": row["name"],
                "priority": row["priority"],
                "department": None,
                "category": None,
                "sla_hours": row["sla_hours"],
                "at_risk_percent": 0.75,
                "escalate_on_breach": True,
                "active": True,
            }
            for row in defaults
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sla_policies_active"), table_name="sla_policies")
    op.drop_index(op.f("ix_sla_policies_category"), table_name="sla_policies")
    op.drop_index(op.f("ix_sla_policies_department"), table_name="sla_policies")
    op.drop_index(op.f("ix_sla_policies_priority"), table_name="sla_policies")
    op.drop_table("sla_policies")
