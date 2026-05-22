"""Add A2A cross-instance and collaborative session tables.

Revision ID: add_a2a_collab_tables
Revises: add_onboarding_phase
Create Date: 2026-05-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON


revision: str = "add_a2a_collab_tables"
down_revision: Union[str, Sequence[str], None] = "add_onboarding_phase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── A2A Remote Instances ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS a2a_remote_instances (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenants(id),
            name VARCHAR(200) NOT NULL,
            base_url VARCHAR(500) NOT NULL,
            protocol_version VARCHAR(20) NOT NULL DEFAULT '0.3.0',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            auth_type VARCHAR(32) NOT NULL DEFAULT 'api_key',
            auth_credential TEXT,
            public_key TEXT,
            last_seen TIMESTAMPTZ,
            last_sync_at TIMESTAMPTZ,
            metadata_json JSONB NOT NULL DEFAULT '{}',
            is_enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── A2A Remote Agent Cards ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS a2a_remote_agent_cards (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            remote_instance_id UUID NOT NULL REFERENCES a2a_remote_instances(id) ON DELETE CASCADE,
            remote_agent_id VARCHAR(200) NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT DEFAULT '',
            capabilities JSONB NOT NULL DEFAULT '{}',
            skills JSONB NOT NULL DEFAULT '[]',
            labels JSONB NOT NULL DEFAULT '[]',
            availability_status VARCHAR(32) NOT NULL DEFAULT 'available',
            supported_task_types JSONB NOT NULL DEFAULT '[]',
            last_synced_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── A2A Tasks ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS a2a_tasks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenants(id),
            source_agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            direction VARCHAR(16) NOT NULL,
            target_instance_id UUID REFERENCES a2a_remote_instances(id) ON DELETE SET NULL,
            target_agent_ref VARCHAR(200),
            request_payload JSONB NOT NULL DEFAULT '{}',
            response_payload JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            callback_url VARCHAR(500),
            callback_token VARCHAR(200) UNIQUE,
            external_task_id VARCHAR(200),
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
    """)

    # ── A2A Event Logs ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS a2a_event_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenants(id),
            task_id UUID REFERENCES a2a_tasks(id) ON DELETE SET NULL,
            instance_id UUID REFERENCES a2a_remote_instances(id) ON DELETE SET NULL,
            event_type VARCHAR(64) NOT NULL,
            direction VARCHAR(16) NOT NULL DEFAULT 'outbound',
            payload JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── Collaborative Sessions ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS collab_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenants(id),
            created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL,
            description TEXT DEFAULT '',
            status VARCHAR(32) NOT NULL DEFAULT 'active',
            settings JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── Collaborative Participants ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS collab_participants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES collab_sessions(id) ON DELETE CASCADE,
            participant_type VARCHAR(16) NOT NULL,
            user_id UUID REFERENCES users(id) ON DELETE CASCADE,
            agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
            display_name VARCHAR(100) NOT NULL,
            role VARCHAR(32) NOT NULL DEFAULT 'member',
            is_active BOOLEAN NOT NULL DEFAULT true,
            joined_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── Collaborative Messages ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS collab_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES collab_sessions(id) ON DELETE CASCADE,
            sender_type VARCHAR(16) NOT NULL,
            sender_id UUID,
            sender_name VARCHAR(100) NOT NULL,
            content TEXT NOT NULL,
            message_type VARCHAR(32) NOT NULL DEFAULT 'text',
            metadata_json JSONB NOT NULL DEFAULT '{}',
            mentioned_ids JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── Indexes ──
    op.execute("CREATE INDEX IF NOT EXISTS ix_a2a_remote_instances_tenant ON a2a_remote_instances(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_a2a_remote_agent_cards_instance ON a2a_remote_agent_cards(remote_instance_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_a2a_tasks_tenant ON a2a_tasks(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_a2a_tasks_source_agent ON a2a_tasks(source_agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_a2a_event_logs_tenant ON a2a_event_logs(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_a2a_event_logs_task ON a2a_event_logs(task_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_collab_sessions_tenant ON collab_sessions(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_collab_participants_session ON collab_participants(session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_collab_messages_session ON collab_messages(session_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS collab_messages")
    op.execute("DROP TABLE IF EXISTS collab_participants")
    op.execute("DROP TABLE IF EXISTS collab_sessions")
    op.execute("DROP TABLE IF EXISTS a2a_event_logs")
    op.execute("DROP TABLE IF EXISTS a2a_tasks")
    op.execute("DROP TABLE IF EXISTS a2a_remote_agent_cards")
    op.execute("DROP TABLE IF EXISTS a2a_remote_instances")
