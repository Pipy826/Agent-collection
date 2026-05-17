"""Merge agent nodes and onboarding migration heads.

Revision ID: merge_agent_nodes_onboarding
Revises: add_agent_nodes, add_onboarding_phase
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "merge_agent_nodes_onboarding"
down_revision: Union[str, Sequence[str], None] = (
    "add_agent_nodes",
    "add_onboarding_phase",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Normalize the OpenCode last-seen column name across deployments."""
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS opencode_last_seen TIMESTAMPTZ
            """
        )
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'agents'
                      AND column_name = 'openclaw_last_seen'
                ) THEN
                    UPDATE agents
                    SET opencode_last_seen = COALESCE(opencode_last_seen, openclaw_last_seen);
                END IF;
            END $$;
            """
        )
        return

    if dialect == "sqlite":
        columns = {
            row[1]
            for row in bind.execute(sa.text("PRAGMA table_info(agents)")).fetchall()
        }
        if "opencode_last_seen" not in columns:
            op.execute("ALTER TABLE agents ADD COLUMN opencode_last_seen TIMESTAMPTZ")
        if "openclaw_last_seen" in columns:
            op.execute(
                """
                UPDATE agents
                SET opencode_last_seen = COALESCE(opencode_last_seen, openclaw_last_seen)
                """
            )


def downgrade() -> None:
    pass
