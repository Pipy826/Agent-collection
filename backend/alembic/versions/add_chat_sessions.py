"""Add chat_sessions table and update existing chat_messages conversation_ids."""

import sqlalchemy as sa
from alembic import op

revision = "add_chat_sessions"
down_revision = "add_agent_tool_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "chat_sessions" not in inspector.get_table_names():
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False, server_default="New Session"),
            sa.Column("source_channel", sa.String(length=20), nullable=False, server_default="web"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("chat_sessions")}
    if "ix_chat_sessions_agent_id" not in existing_indexes:
        op.create_index("ix_chat_sessions_agent_id", "chat_sessions", ["agent_id"], unique=False)
    if "ix_chat_sessions_user_id" not in existing_indexes:
        op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)
    if "ix_chat_sessions_created_at" not in existing_indexes:
        op.create_index("ix_chat_sessions_created_at", "chat_sessions", ["created_at"], unique=False)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_sessions")
