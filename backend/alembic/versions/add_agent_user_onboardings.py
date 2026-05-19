"""Per-(user, agent) onboarding junction table + drop legacy bootstrapped flag."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_agent_user_onboardings"
down_revision: Union[str, None] = "add_tenant_default_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "agent_user_onboardings" not in inspector.get_table_names():
        op.create_table(
            "agent_user_onboardings",
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("agent_id", "user_id"),
        )

    if bind.dialect.name == "sqlite":
        bind.execute(sa.text("""
            INSERT OR IGNORE INTO agent_user_onboardings (agent_id, user_id, onboarded_at)
            SELECT agent_id, user_id, MIN(created_at)
            FROM chat_messages
            WHERE agent_id IS NOT NULL AND user_id IS NOT NULL
            GROUP BY agent_id, user_id
        """))
    else:
        op.execute("""
            INSERT INTO agent_user_onboardings (agent_id, user_id, onboarded_at)
            SELECT agent_id, user_id, MIN(created_at)
            FROM chat_messages
            WHERE agent_id IS NOT NULL AND user_id IS NOT NULL
            GROUP BY agent_id, user_id
            ON CONFLICT DO NOTHING
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_user_onboardings")
