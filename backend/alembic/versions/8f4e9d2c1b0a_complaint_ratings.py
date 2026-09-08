"""complaint ratings table

Revision ID: 8f4e9d2c1b0a
Revises: 7d3e8528ec1c
Create Date: 2026-09-06 06:12:00.000000

Part 22: add the ``complaint_ratings`` table that powers the citizen
satisfaction KPI in the civic analytics dashboard:

- ``complaint_id`` — unique FK to complaints (one rating per complaint; CASCADE)
- ``user_id`` — the citizen who owns the complaint (RESTRICT)
- ``rating`` — 1..5 star score
- ``comment`` — optional free-text feedback
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8f4e9d2c1b0a"
down_revision: Union[str, None] = "7d3e8528ec1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "complaint_ratings",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("complaint_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["complaint_id"], ["complaints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("complaint_id", name="uq_complaint_ratings_complaint_id"),
    )
    op.create_index("ix_complaint_ratings_complaint_id", "complaint_ratings", ["complaint_id"], unique=False)
    op.create_index("ix_complaint_ratings_user_id", "complaint_ratings", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_complaint_ratings_user_id", table_name="complaint_ratings")
    op.drop_index("ix_complaint_ratings_complaint_id", table_name="complaint_ratings")
    op.drop_table("complaint_ratings")
