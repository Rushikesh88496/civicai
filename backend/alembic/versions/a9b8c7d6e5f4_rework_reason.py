"""rework reason on work orders

Revision ID: a9b8c7d6e5f4
Revises: f0e1d2c3b4a5
Create Date: 2026-09-10 14:30:00.000000

Adds ``rework_reason`` to ``work_orders``. An authorized officer can reject the
submitted resolution evidence with ``REQUEST_REWORK``, moving the order to
``RETURNED_FOR_REWORK`` and recording the required fixes here so the field
worker always sees them when they restart the job (the worker then restarts via
a fresh GPS check-in + START_REWORK). The new WorkOrderStatus / WorkOrderAction
values are short strings that fit the existing ``status`` / action columns, so
no further column change is needed.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "f0e1d2c3b4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_orders", sa.Column("rework_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_orders", "rework_reason")
