"""predictive infrastructure maintenance models

Revision ID: b1c2d3e4f5a6
Revises: 9a8b7c6d5e4f
Create Date: 2026-09-06 15:30:00.000000

Part 24: add the predictive infrastructure-maintenance tables:
``infrastructure_assets`` (registered municipal assets), ``infrastructure_models``
(its own model registry so retrains never touch the hotspot registry),
``infrastructure_predictions`` (stored risk outputs + officer review state) and
``preventive_work_orders`` (optional proactive work orders on approved assets).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "9a8b7c6d5e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "infrastructure_assets",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.Enum("ROAD", "BRIDGE", "WATER_MAIN", "SEWER", "DRAINAGE", "STREET_LIGHTING", "PARK", "PUBLIC_BUILDING", name="infrastructure_category"), nullable=False),
        sa.Column("ward_id", sa.UUID(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("installed_at", sa.Date(), nullable=True),
        sa.Column("condition_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["ward_id"], ["wards.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_infrastructure_assets_is_active", "infrastructure_assets", ["is_active"])
    op.create_index("ix_infrastructure_assets_category", "infrastructure_assets", ["category"])
    op.create_index("ix_infrastructure_assets_ward_id", "infrastructure_assets", ["ward_id"])
    op.create_index("ix_infrastructure_assets_name", "infrastructure_assets", ["name"])

    op.create_table(
        "infrastructure_models",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("artifact_filename", sa.String(length=255), nullable=False),
        sa.Column("metrics", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("config", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("trained_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trained_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("version", name="uq_infrastructure_models_version"),
    )
    op.create_index(
        "ix_infrastructure_models_is_active", "infrastructure_models", ["is_active"]
    )
    op.create_index("ix_infrastructure_models_version", "infrastructure_models", ["version"])

    op.create_table(
        "infrastructure_predictions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("model_version", sa.Integer(), nullable=False),
        sa.Column("failure_probability", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.Enum("LOW", "MEDIUM", "HIGH", "CRITICAL", name="infrastructure_risk_level"), nullable=False),
        sa.Column("recommended_inspection", sa.Text(), nullable=False),
        sa.Column("supporting_factors", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("history", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("ai_prediction", sa.Boolean(), nullable=False),
        sa.Column("review_status", sa.Enum("PENDING", "APPROVED", "REJECTED", name="prediction_review_status"), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["asset_id"], ["infrastructure_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_infrastructure_predictions_asset_id", "infrastructure_predictions", ["asset_id"]
    )
    op.create_index(
        "ix_infrastructure_predictions_review_status",
        "infrastructure_predictions",
        ["review_status"],
    )
    op.create_index(
        "ix_infrastructure_predictions_risk_level", "infrastructure_predictions", ["risk_level"]
    )

    op.create_table(
        "preventive_work_orders",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("prediction_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("PENDING_APPROVAL", "APPROVED", "REJECTED", "COMPLETED", "CANCELLED", name="preventive_work_order_status"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["prediction_id"], ["infrastructure_predictions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["infrastructure_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_preventive_work_orders_asset_id", "preventive_work_orders", ["asset_id"]
    )
    op.create_index(
        "ix_preventive_work_orders_department", "preventive_work_orders", ["department"]
    )
    op.create_index(
        "ix_preventive_work_orders_prediction_id", "preventive_work_orders", ["prediction_id"]
    )
    op.create_index(
        "ix_preventive_work_orders_status", "preventive_work_orders", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_preventive_work_orders_status", table_name="preventive_work_orders")
    op.drop_index("ix_preventive_work_orders_prediction_id", table_name="preventive_work_orders")
    op.drop_index("ix_preventive_work_orders_department", table_name="preventive_work_orders")
    op.drop_index("ix_preventive_work_orders_asset_id", table_name="preventive_work_orders")
    op.drop_table("preventive_work_orders")

    op.drop_index("ix_infrastructure_predictions_risk_level", table_name="infrastructure_predictions")
    op.drop_index("ix_infrastructure_predictions_review_status", table_name="infrastructure_predictions")
    op.drop_index("ix_infrastructure_predictions_asset_id", table_name="infrastructure_predictions")
    op.drop_table("infrastructure_predictions")

    op.drop_index("ix_infrastructure_models_version", table_name="infrastructure_models")
    op.drop_index("ix_infrastructure_models_is_active", table_name="infrastructure_models")
    op.drop_table("infrastructure_models")

    op.drop_index("ix_infrastructure_assets_name", table_name="infrastructure_assets")
    op.drop_index("ix_infrastructure_assets_ward_id", table_name="infrastructure_assets")
    op.drop_index("ix_infrastructure_assets_category", table_name="infrastructure_assets")
    op.drop_index("ix_infrastructure_assets_is_active", table_name="infrastructure_assets")
    op.drop_table("infrastructure_assets")

    op.execute("DROP TYPE IF EXISTS preventive_work_order_status")
    op.execute("DROP TYPE IF EXISTS prediction_review_status")
    op.execute("DROP TYPE IF EXISTS infrastructure_risk_level")
    op.execute("DROP TYPE IF EXISTS infrastructure_category")