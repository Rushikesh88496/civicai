"""work completion + evidence submission timestamps

Revision ID: f0e1d2c3b4a5
Revises: e1f2a3b4c5d6
Create Date: 2026-09-10 13:00:00.000000

Adds ``evidence_submitted_at`` to ``work_orders``. The field worker now walks
IN_PROGRESS → WORK_COMPLETED (finish) → EVIDENCE_SUBMITTED (submit resolution
evidence); the complaint is only marked RESOLVED after the AI resolution
verification / human review confirms the repair. The two new WorkOrderStatus
values are short strings that fit the existing ``status`` column, so no column
change is needed beyond the evidence timestamp.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f0e1d2c3b4a5"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_orders", sa.Column("evidence_submitted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("work_orders", "evidence_submitted_at")