"""Add memory and learning loop tables.

Revision ID: add_memory_learning_tables
Revises: add_workflow_engine_tables
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_memory_learning_tables"
down_revision: Union[str, Sequence[str], None] = "add_workflow_engine_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type(dialect_name: str):
    return postgresql.UUID(as_uuid=True) if dialect_name == "postgresql" else sa.String(36)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    dialect_name = bind.dialect.name
    uuid_type = _uuid_type(dialect_name)

    if "memory_documents" not in table_names:
        op.create_table(
            "memory_documents",
            sa.Column("id", uuid_type, primary_key=True, nullable=False),
            sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("agent_id", uuid_type, sa.ForeignKey("agents.id"), nullable=True),
            sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_by", uuid_type, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("scope", sa.String(length=32), nullable=False, server_default="agent"),
            sa.Column("memory_type", sa.String(length=32), nullable=False, server_default="fact"),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("normalized_content", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_type", sa.String(length=50), nullable=False, server_default="manual"),
            sa.Column("source_ref_id", sa.String(length=100), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("importance_score", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("visibility", sa.String(length=32), nullable=False, server_default="private"),
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    memory_indexes = {idx["name"] for idx in inspector.get_indexes("memory_documents")}
    if "ix_memory_documents_tenant_id" not in memory_indexes:
        op.create_index("ix_memory_documents_tenant_id", "memory_documents", ["tenant_id"], unique=False)
    if "ix_memory_documents_agent_id" not in memory_indexes:
        op.create_index("ix_memory_documents_agent_id", "memory_documents", ["agent_id"], unique=False)
    if "ix_memory_documents_user_id" not in memory_indexes:
        op.create_index("ix_memory_documents_user_id", "memory_documents", ["user_id"], unique=False)

    if "answer_feedback" not in table_names:
        op.create_table(
            "answer_feedback",
            sa.Column("id", uuid_type, primary_key=True, nullable=False),
            sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("message_id", uuid_type, sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
            sa.Column("agent_id", uuid_type, sa.ForeignKey("agents.id"), nullable=False),
            sa.Column("user_id", uuid_type, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("feedback_type", sa.String(length=16), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("corrected_answer", sa.Text(), nullable=True),
            sa.Column("question_snapshot", sa.Text(), nullable=True),
            sa.Column("normalized_question", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    feedback_indexes = {idx["name"] for idx in inspector.get_indexes("answer_feedback")}
    if "ix_answer_feedback_tenant_id" not in feedback_indexes:
        op.create_index("ix_answer_feedback_tenant_id", "answer_feedback", ["tenant_id"], unique=False)
    if "ix_answer_feedback_message_id" not in feedback_indexes:
        op.create_index("ix_answer_feedback_message_id", "answer_feedback", ["message_id"], unique=False)
    if "ix_answer_feedback_agent_id" not in feedback_indexes:
        op.create_index("ix_answer_feedback_agent_id", "answer_feedback", ["agent_id"], unique=False)
    if "ix_answer_feedback_user_id" not in feedback_indexes:
        op.create_index("ix_answer_feedback_user_id", "answer_feedback", ["user_id"], unique=False)

    if "golden_examples" not in table_names:
        op.create_table(
            "golden_examples",
            sa.Column("id", uuid_type, primary_key=True, nullable=False),
            sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("agent_id", uuid_type, sa.ForeignKey("agents.id"), nullable=True),
            sa.Column("source_feedback_id", uuid_type, sa.ForeignKey("answer_feedback.id", ondelete="SET NULL"), nullable=True),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("normalized_question", sa.Text(), nullable=False),
            sa.Column("correct_answer", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_review"),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("reviewed_by", uuid_type, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    golden_indexes = {idx["name"] for idx in inspector.get_indexes("golden_examples")}
    if "ix_golden_examples_tenant_id" not in golden_indexes:
        op.create_index("ix_golden_examples_tenant_id", "golden_examples", ["tenant_id"], unique=False)
    if "ix_golden_examples_agent_id" not in golden_indexes:
        op.create_index("ix_golden_examples_agent_id", "golden_examples", ["agent_id"], unique=False)
    if "ix_golden_examples_source_feedback_id" not in golden_indexes:
        op.create_index("ix_golden_examples_source_feedback_id", "golden_examples", ["source_feedback_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_golden_examples_source_feedback_id", table_name="golden_examples")
    op.drop_index("ix_golden_examples_agent_id", table_name="golden_examples")
    op.drop_index("ix_golden_examples_tenant_id", table_name="golden_examples")
    op.drop_table("golden_examples")
    op.drop_index("ix_answer_feedback_user_id", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_agent_id", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_message_id", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_tenant_id", table_name="answer_feedback")
    op.drop_table("answer_feedback")
    op.drop_index("ix_memory_documents_user_id", table_name="memory_documents")
    op.drop_index("ix_memory_documents_agent_id", table_name="memory_documents")
    op.drop_index("ix_memory_documents_tenant_id", table_name="memory_documents")
    op.drop_table("memory_documents")
