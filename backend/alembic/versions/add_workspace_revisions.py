"""Add workspace file revision and edit lock tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_workspace_revisions"
down_revision: Union[str, None] = "okr_agent_id_sys_uq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "workspace_file_revisions" not in inspector.get_table_names():
        op.create_table(
            "workspace_file_revisions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("operation", sa.String(length=40), nullable=False, server_default="write"),
            sa.Column("actor_type", sa.String(length=20), nullable=False),
            sa.Column("actor_id", sa.String(length=36), nullable=True),
            sa.Column("session_id", sa.String(length=200), nullable=True),
            sa.Column("before_content", sa.Text(), nullable=True),
            sa.Column("after_content", sa.Text(), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("group_key", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "workspace_edit_locks" not in inspector.get_table_names():
        op.create_table(
            "workspace_edit_locks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=200), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("heartbeat_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("agent_id", "path", name="uq_workspace_edit_locks_agent_path"),
        )

    file_indexes = {idx["name"] for idx in inspector.get_indexes("workspace_file_revisions")}
    if "ix_workspace_file_revisions_agent_id" not in file_indexes:
        op.create_index("ix_workspace_file_revisions_agent_id", "workspace_file_revisions", ["agent_id"], unique=False)
    if "ix_workspace_file_revisions_path" not in file_indexes:
        op.create_index("ix_workspace_file_revisions_path", "workspace_file_revisions", ["path"], unique=False)
    if "ix_workspace_file_revisions_group_key" not in file_indexes:
        op.create_index("ix_workspace_file_revisions_group_key", "workspace_file_revisions", ["group_key"], unique=False)
    if "ix_workspace_file_revisions_created_at" not in file_indexes:
        op.create_index("ix_workspace_file_revisions_created_at", "workspace_file_revisions", ["created_at"], unique=False)

    lock_indexes = {idx["name"] for idx in inspector.get_indexes("workspace_edit_locks")}
    if "ix_workspace_edit_locks_agent_id" not in lock_indexes:
        op.create_index("ix_workspace_edit_locks_agent_id", "workspace_edit_locks", ["agent_id"], unique=False)
    if "ix_workspace_edit_locks_path" not in lock_indexes:
        op.create_index("ix_workspace_edit_locks_path", "workspace_edit_locks", ["path"], unique=False)
    if "ix_workspace_edit_locks_user_id" not in lock_indexes:
        op.create_index("ix_workspace_edit_locks_user_id", "workspace_edit_locks", ["user_id"], unique=False)
    if "ix_workspace_edit_locks_expires_at" not in lock_indexes:
        op.create_index("ix_workspace_edit_locks_expires_at", "workspace_edit_locks", ["expires_at"], unique=False)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workspace_edit_locks")
    op.execute("DROP TABLE IF EXISTS workspace_file_revisions")
