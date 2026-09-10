"""work_order_activities GPS accuracy

Revision ID: e1f2a3b4c5d6
Revises: d6e7f8a9b0c3
Create Date: 2026-09-10 12:00:00.000000

Adds ``accuracy_m`` (browser GPS horizontal accuracy in metres) to the field
worker check-in activity rows. The worker app captures latitude / longitude /
accuracy / timestamp from the browser Geolocation API during an explicit GPS
check-in; accuracy is stored alongside the coordinates so a recorded fix is
never presented as more precise than it really was. It is optional (older
clients / geo-denied check-ins record None).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d6e7f8a9b0c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_order_activities", sa.Column("accuracy_m", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("work_order_activities", "accuracy_m")