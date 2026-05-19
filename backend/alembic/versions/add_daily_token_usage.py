"""Add daily_token_usage table."""

from alembic import op
import sqlalchemy as sa

revision = "add_daily_token_usage"
down_revision = "add_agentbay_enum_value"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "daily_token_usage" not in inspector.get_table_names():
        op.create_table(
            "daily_token_usage",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("daily_token_usage")}
    if "uq_daily_token_usage_agent_date" not in existing_indexes:
        op.create_index("uq_daily_token_usage_agent_date", "daily_token_usage", ["agent_id", "date"], unique=True)
    if "ix_daily_token_usage_tenant_id" not in existing_indexes:
        op.create_index("ix_daily_token_usage_tenant_id", "daily_token_usage", ["tenant_id"], unique=False)
    if "ix_daily_token_usage_agent_id" not in existing_indexes:
        op.create_index("ix_daily_token_usage_agent_id", "daily_token_usage", ["agent_id"], unique=False)
    if "ix_daily_token_usage_date" not in existing_indexes:
        op.create_index("ix_daily_token_usage_date", "daily_token_usage", ["date"], unique=False)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS daily_token_usage")
