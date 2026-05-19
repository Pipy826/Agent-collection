"""Add agent_nodes table for multi-node OpenCode management."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "add_agent_nodes"
down_revision = "user_refactor_v1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    is_sqlite = bind.dialect.name == "sqlite"

    if "agent_nodes" not in table_names:
        op.create_table(
            "agent_nodes",
            sa.Column("id", sa.String(length=36) if is_sqlite else postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("agent_id", sa.String(length=36) if is_sqlite else postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("owner_user_id", sa.String(length=36) if is_sqlite else postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", sa.String(length=36) if is_sqlite else postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("node_name", sa.String(200), server_default="", nullable=False),
            sa.Column("api_key_hash", sa.String(128), nullable=False),
            sa.Column("status", sa.String(20), server_default="idle", nullable=False),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.String(50), nullable=True),
            sa.Column("config", sa.JSON() if is_sqlite else postgresql.JSON(), server_default="{}", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    node_indexes = {idx["name"] for idx in inspector.get_indexes("agent_nodes")}
    if "ix_agent_nodes_agent_id" not in node_indexes:
        op.create_index("ix_agent_nodes_agent_id", "agent_nodes", ["agent_id"])
    if "ix_agent_nodes_tenant_id" not in node_indexes:
        op.create_index("ix_agent_nodes_tenant_id", "agent_nodes", ["tenant_id"])
    if "ix_agent_nodes_api_key_hash" not in node_indexes:
        op.create_index("ix_agent_nodes_api_key_hash", "agent_nodes", ["api_key_hash"])

    gateway_columns = {col["name"] for col in inspector.get_columns("gateway_messages")}
    if "agent_node_id" not in gateway_columns:
        op.add_column(
            "gateway_messages",
            sa.Column("agent_node_id", sa.String(length=36) if is_sqlite else postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "sender_agent_node_id" not in gateway_columns:
        op.add_column(
            "gateway_messages",
            sa.Column("sender_agent_node_id", sa.String(length=36) if is_sqlite else postgresql.UUID(as_uuid=True), nullable=True),
        )

    conn = bind
    rows = conn.execute(
        sa.text(
            "SELECT id, creator_id, tenant_id, api_key_hash FROM agents "
            "WHERE agent_type = 'opencode' AND api_key_hash IS NOT NULL"
        )
    ).fetchall()

    import uuid as _uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    existing_agent_ids = {
        str(row[0])
        for row in conn.execute(sa.text("SELECT agent_id FROM agent_nodes")).fetchall()
        if row[0] is not None
    }

    created = 0
    for row in rows:
        if str(row.id) in existing_agent_ids:
            continue
        node_id = str(_uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO agent_nodes (id, agent_id, owner_user_id, tenant_id, node_name, api_key_hash, "
                "status, created_at, updated_at) "
                "VALUES (:id, :agent_id, :owner_user_id, :tenant_id, :node_name, :api_key_hash, "
                ":status, :created_at, :updated_at)"
            ),
            {
                "id": node_id,
                "agent_id": str(row.id),
                "owner_user_id": str(row.creator_id),
                "tenant_id": None if row.tenant_id is None else str(row.tenant_id),
                "node_name": "Default",
                "api_key_hash": row.api_key_hash,
                "status": "idle",
                "created_at": now,
                "updated_at": now,
            },
        )
        created += 1

    if created:
        print(f"[migration] Created default AgentNode for {created} existing opencode agents")


def downgrade():
    op.drop_column("gateway_messages", "sender_agent_node_id")
    op.drop_column("gateway_messages", "agent_node_id")
    op.drop_index("ix_agent_nodes_api_key_hash", table_name="agent_nodes")
    op.drop_index("ix_agent_nodes_tenant_id", table_name="agent_nodes")
    op.drop_index("ix_agent_nodes_agent_id", table_name="agent_nodes")
    op.drop_table("agent_nodes")
