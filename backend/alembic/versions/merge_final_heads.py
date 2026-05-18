"""Merge final heads: add_agent_nodes and add_onboarding_phase.

Revision ID: merge_final_heads
Revises: add_agent_nodes, add_onboarding_phase
Create Date: 2026-05-16
"""
from typing import Sequence, Union
from alembic import op

revision: str = "merge_final_heads"
down_revision: Union[str, Sequence[str], None] = ("add_agent_nodes", "add_onboarding_phase")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
