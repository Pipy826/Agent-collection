"""Add agent_credentials table for storing encrypted login credentials and cookies."""

from alembic import op
import sqlalchemy as sa


revision = "add_agent_credentials"
down_revision = "add_tool_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "agent_credentials" not in inspector.get_table_names():
        op.create_table(
            "agent_credentials",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("credential_type", sa.String(length=20), nullable=True, server_default="website"),
            sa.Column("platform", sa.String(length=100), nullable=False),
            sa.Column("display_name", sa.String(length=200), nullable=True, server_default=""),
            sa.Column("username", sa.Text(), nullable=True),
            sa.Column("password", sa.Text(), nullable=True),
            sa.Column("login_url", sa.String(length=500), nullable=True),
            sa.Column("cookies_json", sa.Text(), nullable=True),
            sa.Column("cookies_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True, server_default="active"),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_injected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("agent_credentials")}
    if "ix_agent_credentials_agent_id" not in existing_indexes:
        op.create_index("ix_agent_credentials_agent_id", "agent_credentials", ["agent_id"], unique=False)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_credentials_agent_id")
    op.execute("DROP TABLE IF EXISTS agent_credentials")
