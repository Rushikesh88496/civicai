"""citizen AI assistant knowledge base and conversations

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-09-06 17:00:00.000000

Part 25 — Citizen AI Assistant with RAG:
  * ``knowledge_documents`` — citable municipal policy / procedure text with a
    pgvector ``vector(384)`` embedding (BGE-small) and an HNSW cosine index so
    the assistant can semantically match citizen questions to official sources.
  * ``assistant_conversations`` — one persistent conversation per citizen
    (``user_id`` unique) plus ``assistant_messages`` for the turn history,
    sources cited and how each answer was generated.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _knowledge_category_enum() -> pg.ENUM:
    return pg.ENUM(
        "SLA_POLICY",
        "DEPARTMENT_RESPONSIBILITY",
        "COMPLAINT_CATEGORY",
        "CITIZEN_FAQ",
        "MUNICIPAL_PROCEDURE",
        name="knowledge_category",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    pg.ENUM(
        "SLA_POLICY",
        "DEPARTMENT_RESPONSIBILITY",
        "COMPLAINT_CATEGORY",
        "CITIZEN_FAQ",
        "MUNICIPAL_PROCEDURE",
        name="knowledge_category",
    ).create(bind, checkfirst=True)

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=False),
        sa.Column("category", _knowledge_category_enum(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=True),
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
        sa.UniqueConstraint("title"),
    )
    op.create_index("ix_knowledge_documents_title", "knowledge_documents", ["title"])
    op.create_index("ix_knowledge_documents_category", "knowledge_documents", ["category"])
    op.create_index("ix_knowledge_documents_source_ref", "knowledge_documents", ["source_ref"])
    op.create_index("ix_knowledge_documents_is_active", "knowledge_documents", ["is_active"])
    # HNSW index for fast cosine-distance semantic retrieval.
    op.execute(
        "CREATE INDEX idx_knowledge_documents_embedding_hnsw "
        "ON knowledge_documents USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_assistant_conversations_user_id", "assistant_conversations", ["user_id"])

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", pg.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("generated_by", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["assistant_conversations.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_assistant_messages_conversation_id", "assistant_messages", ["conversation_id"]
    )
    op.create_index("ix_assistant_messages_role", "assistant_messages", ["role"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_assistant_messages_role", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_conversation_id", table_name="assistant_messages")
    op.drop_table("assistant_messages")

    op.drop_index("ix_assistant_conversations_user_id", table_name="assistant_conversations")
    op.drop_table("assistant_conversations")

    op.execute("DROP INDEX IF EXISTS idx_knowledge_documents_embedding_hnsw")
    op.drop_index("ix_knowledge_documents_is_active", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_source_ref", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_category", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_title", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")

    pg.ENUM(name="knowledge_category").drop(bind, checkfirst=True)
