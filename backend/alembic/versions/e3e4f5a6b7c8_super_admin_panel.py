"""super admin panel

Revision ID: e3e4f5a6b7c8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-07 09:00:00.000000

Part 27 — Super-Admin Panel data model:

  * Adds ``is_active`` soft-disable flags to ``roles``, ``wards`` and
    ``departments`` (existing rows default to active; history is preserved).
  * ``audit_logs`` — append-only trail of every panel mutation (actor, action,
    before/after, IP). NEVER stores secret values in plaintext.
  * ``system_settings`` — runtime override layer on top of environment-based
    configuration; secrets are stored Fernet-encrypted (or not at all).
  * ``complaint_categories`` — admin-managed category registry seeded from the
    ``ComplaintCategory`` enum.
  * ``priority_weights`` — runtime-editable Priority Engine factor weights
    seeded from the built-in defaults.
  * Seeds the ``SUPER_ADMIN`` role used to gate the panel.
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "e3e4f5a6b7c8"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_is_active(table: str) -> None:
    op.add_column(
        table,
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    # ---- soft-disable flags -------------------------------------------------- #
    _add_is_active("roles")
    _add_is_active("wards")
    _add_is_active("departments")

    # ---- audit_logs ---------------------------------------------------------- #
    op.create_table(
        "audit_logs",
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_entity_type"), "audit_logs", ["entity_type"], unique=False)
    op.create_index(op.f("ix_audit_logs_entity_id"), "audit_logs", ["entity_id"], unique=False)

    # ---- system_settings ------------------------------------------------------ #
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=2000), nullable=True),
        sa.Column("is_secret", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_editable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_settings_key"), "system_settings", ["key"], unique=True)
    op.create_index(
        op.f("ix_system_settings_category"), "system_settings", ["category"], unique=False
    )

    # The recognisable configuration surface (metadata only — effective values
    # come from the environment; ``value`` stays NULL until a panel override).
    settings_t = sa.table(
        "system_settings",
        sa.column("id", sa.UUID()),
        sa.column("key", sa.String()),
        sa.column("label", sa.String()),
        sa.column("category", sa.String()),
        sa.column("value_type", sa.String()),
        sa.column("value", sa.String()),
        sa.column("is_secret", sa.Boolean()),
        sa.column("is_editable", sa.Boolean()),
    )
    settings_seed = [
        ("GROQ_API_KEY", "Groq API Key", "AI", "secret", True),
        ("GROQ_MODEL", "Groq Chat Model", "AI", "text", False),
        ("ASSISTANT_MODEL", "Citizen Assistant Model", "AI", "text", False),
        ("EMBEDDING_MODEL", "Embedding Model", "AI", "text", False),
        ("VISION_MODEL", "Vision / Evidence Model", "Vision", "text", False),
        ("ROUTING_API_URL", "Live Routing API URL", "Integrations", "text", False),
        ("ROUTING_API_KEY", "Live Routing API Key", "Integrations", "secret", True),
        ("EMAIL_PROVIDER", "Email Provider", "Email", "text", False),
        ("SMTP_HOST", "SMTP Host", "Email", "text", False),
        ("SMTP_PORT", "SMTP Port", "Email", "int", False),
        ("SMTP_USER", "SMTP Username", "Email", "text", False),
        ("SMTP_PASSWORD", "SMTP Password", "Email", "secret", True),
    ]
    op.bulk_insert(
        settings_t,
        [
            {
                "id": uuid4(),
                "key": key,
                "label": label,
                "category": category,
                "value_type": value_type,
                "value": None,
                "is_secret": is_secret,
                "is_editable": True,
            }
            for key, label, category, value_type, is_secret in settings_seed
        ],
    )

    # ---- complaint_categories ------------------------------------------------ #
    op.create_table(
        "complaint_categories",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_complaint_categories_code"), "complaint_categories", ["code"], unique=True
    )

    categories_t = sa.table(
        "complaint_categories",
        sa.column("id", sa.UUID()),
        sa.column("code", sa.String()),
        sa.column("label", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    category_seed = [
        ("ROAD", "Road", "Roads, potholes and street surfaces."),
        ("SANITATION", "Sanitation", "Waste collection and street cleanliness."),
        ("WATER", "Water", "Supply, pressure and quality."),
        ("ELECTRICITY", "Electricity", "Power supply and outages."),
        ("PUBLIC_SAFETY", "Public Safety", "Hazards that endanger the public."),
        ("PARKS", "Parks", "Public parks and playgrounds."),
        ("STREET_LIGHTING", "Street Lighting", "Street lights and poles."),
        ("OTHER", "Other", "Anything not covered by another category."),
        ("WATER_LEAK", "Water Leak", "Leaking pipes and water wastage."),
        ("FLOODING", "Flooding", "Street / property flooding."),
        ("GARBAGE", "Garbage", "Uncollected or overflowing garbage."),
        ("DRAINAGE", "Drainage", "Blocked or damaged drainage."),
        ("FALLEN_TREE", "Fallen Tree", "Fallen trees or large branches."),
    ]
    op.bulk_insert(
        categories_t,
        [
            {
                "id": uuid4(),
                "code": code,
                "label": label,
                "description": desc,
                "is_active": True,
                "sort_order": idx,
            }
            for idx, (code, label, desc) in enumerate(category_seed)
        ],
    )

    # ---- priority_weights ------------------------------------------------------ #
    op.create_table(
        "priority_weights",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_priority_weights_key"), "priority_weights", ["key"], unique=True)

    weights_t = sa.table(
        "priority_weights",
        sa.column("id", sa.UUID()),
        sa.column("key", sa.String()),
        sa.column("label", sa.String()),
        sa.column("weight", sa.Float()),
        sa.column("is_active", sa.Boolean()),
    )
    weight_seed = [
        ("severity", "Severity", 0.30),
        ("weather", "Weather risk", 0.10),
        ("location", "Critical infrastructure proximity", 0.15),
        ("crowd", "Crowd pressure (population + reports)", 0.20),
        ("history", "Historical recurrence", 0.10),
        ("time", "Time unresolved", 0.15),
    ]
    op.bulk_insert(
        weights_t,
        [
            {"id": uuid4(), "key": key, "label": label, "weight": weight, "is_active": True}
            for key, label, weight in weight_seed
        ],
    )

    # ---- SUPER_ADMIN role ------------------------------------------------------ #
    op.execute(
        sa.text(
            "INSERT INTO roles (id, name, description, is_active, created_at, updated_at) "
            "VALUES (:rid, 'SUPER_ADMIN', 'Super administrator with panel management rights.', "
            "true, now(), now()) "
            "ON CONFLICT (name) DO NOTHING"
        ).bindparams(rid=uuid4())
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_priority_weights_key"), table_name="priority_weights")
    op.drop_table("priority_weights")
    op.drop_index(op.f("ix_complaint_categories_code"), table_name="complaint_categories")
    op.drop_table("complaint_categories")
    op.drop_index(op.f("ix_system_settings_category"), table_name="system_settings")
    op.drop_index(op.f("ix_system_settings_key"), table_name="system_settings")
    op.drop_table("system_settings")
    op.drop_index(op.f("ix_audit_logs_entity_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_entity_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_column("departments", "is_active")
    op.drop_column("wards", "is_active")
    op.drop_column("roles", "is_active")
