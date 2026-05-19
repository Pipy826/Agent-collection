"""Add usage quota fields to users, agents, and tenants tables."""

import sqlalchemy as sa
from alembic import op

revision = "add_quota_fields"
down_revision = "initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def add_column_if_missing(table_name: str, column: sa.Column) -> None:
        existing = {col["name"] for col in inspector.get_columns(table_name)}
        if column.name not in existing:
            op.add_column(table_name, column)

    add_column_if_missing("users", sa.Column("quota_message_limit", sa.Integer(), server_default="50"))
    add_column_if_missing("users", sa.Column("quota_message_period", sa.String(length=20), server_default="permanent"))
    add_column_if_missing("users", sa.Column("quota_messages_used", sa.Integer(), server_default="0"))
    add_column_if_missing("users", sa.Column("quota_period_start", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing("users", sa.Column("quota_max_agents", sa.Integer(), server_default="2"))
    add_column_if_missing("users", sa.Column("quota_agent_ttl_hours", sa.Integer(), server_default="0"))

    add_column_if_missing("agents", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing("agents", sa.Column("is_expired", sa.Boolean(), server_default=sa.false()))
    add_column_if_missing("agents", sa.Column("llm_calls_today", sa.Integer(), server_default="0"))
    add_column_if_missing("agents", sa.Column("max_llm_calls_per_day", sa.Integer(), server_default="1000"))
    add_column_if_missing("agents", sa.Column("llm_calls_reset_at", sa.DateTime(timezone=True), nullable=True))

    add_column_if_missing("tenants", sa.Column("default_message_limit", sa.Integer(), server_default="50"))
    add_column_if_missing("tenants", sa.Column("default_message_period", sa.String(length=20), server_default="permanent"))
    add_column_if_missing("tenants", sa.Column("default_max_agents", sa.Integer(), server_default="2"))
    add_column_if_missing("tenants", sa.Column("default_agent_ttl_hours", sa.Integer(), server_default="0"))
    add_column_if_missing("tenants", sa.Column("default_max_llm_calls_per_day", sa.Integer(), server_default="1000"))
    add_column_if_missing("tenants", sa.Column("min_heartbeat_interval_minutes", sa.Integer(), server_default="120"))


def downgrade() -> None:
    pass
