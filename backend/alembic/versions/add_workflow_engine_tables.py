"""Add workflow engine tables.

Revision ID: add_workflow_engine_tables
Revises: merge_agent_nodes_onboarding
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_workflow_engine_tables"
down_revision: Union[str, Sequence[str], None] = "merge_agent_nodes_onboarding"
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

    if "workflow_definitions" not in table_names:
        op.create_table(
            "workflow_definitions",
            sa.Column("id", uuid_type, primary_key=True, nullable=False),
            sa.Column("agent_id", uuid_type, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=True),
            sa.Column("created_by", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("definition", sa.JSON(), nullable=False),
            sa.Column("canvas_layout", sa.JSON(), nullable=False),
            sa.Column("input_schema", sa.JSON(), nullable=False),
            sa.Column("output_schema", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    workflow_definition_indexes = {idx["name"] for idx in inspector.get_indexes("workflow_definitions")}
    if "ix_workflow_definitions_agent_id" not in workflow_definition_indexes:
        op.create_index("ix_workflow_definitions_agent_id", "workflow_definitions", ["agent_id"], unique=False)

    if "workflow_runs" not in table_names:
        op.create_table(
            "workflow_runs",
            sa.Column("id", uuid_type, primary_key=True, nullable=False),
            sa.Column(
                "workflow_id", uuid_type, sa.ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("agent_id", uuid_type, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("started_by", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("input_payload", sa.JSON(), nullable=False),
            sa.Column("context_snapshot", sa.JSON(), nullable=False),
            sa.Column("output_payload", sa.JSON(), nullable=False),
            sa.Column("current_node_key", sa.String(length=120), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    workflow_run_indexes = {idx["name"] for idx in inspector.get_indexes("workflow_runs")}
    if "ix_workflow_runs_workflow_id" not in workflow_run_indexes:
        op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"], unique=False)

    if "workflow_node_runs" not in table_names:
        op.create_table(
            "workflow_node_runs",
            sa.Column("id", uuid_type, primary_key=True, nullable=False),
            sa.Column("workflow_run_id", uuid_type, sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("node_key", sa.String(length=120), nullable=False),
            sa.Column("node_type", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("input_payload", sa.JSON(), nullable=False),
            sa.Column("output_payload", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    workflow_node_run_indexes = {idx["name"] for idx in inspector.get_indexes("workflow_node_runs")}
    if "ix_workflow_node_runs_workflow_run_id" not in workflow_node_run_indexes:
        op.create_index(
            "ix_workflow_node_runs_workflow_run_id", "workflow_node_runs", ["workflow_run_id"], unique=False
        )


def downgrade() -> None:
    op.drop_index("ix_workflow_node_runs_workflow_run_id", table_name="workflow_node_runs")
    op.drop_table("workflow_node_runs")
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_workflow_definitions_agent_id", table_name="workflow_definitions")
    op.drop_table("workflow_definitions")
