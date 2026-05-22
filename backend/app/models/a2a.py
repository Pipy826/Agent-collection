"""A2A (Agent-to-Agent) cross-instance collaboration models.

Implements the data layer for standardized cross-instance agent discovery,
task delegation, and audit logging per A2A_PROTOCOL_DEV_SPEC.md Phase 1.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RemoteInstance(Base):
    """A remote Clawith/OpenCode deployment that this instance can communicate with."""

    __tablename__ = "a2a_remote_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(20), default="0.3.0", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # Status: pending | active | unreachable | disabled
    auth_type: Mapped[str] = mapped_column(String(32), default="api_key", nullable=False)
    # Auth: api_key | hmac | none
    auth_credential: Mapped[str | None] = mapped_column(Text)
    # Encrypted API key or HMAC secret for outbound calls
    public_key: Mapped[str | None] = mapped_column(Text)
    # Public key for signature verification on inbound calls
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent_cards: Mapped[list["RemoteAgentCard"]] = relationship(
        "RemoteAgentCard", back_populates="instance", cascade="all, delete-orphan"
    )


class RemoteAgentCard(Base):
    """Capability card for an agent on a remote instance."""

    __tablename__ = "a2a_remote_agent_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    remote_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("a2a_remote_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    remote_agent_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # The agent's ID on the remote system (opaque string)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    skills: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    labels: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    availability_status: Mapped[str] = mapped_column(String(32), default="available", nullable=False)
    # available | busy | offline
    supported_task_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    instance: Mapped["RemoteInstance"] = relationship("RemoteInstance", back_populates="agent_cards")


class A2ATask(Base):
    """A task delegated to or received from a remote instance."""

    __tablename__ = "a2a_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    source_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    # outbound (we send to remote) | inbound (remote sends to us)
    target_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("a2a_remote_instances.id", ondelete="SET NULL"), index=True
    )
    target_agent_ref: Mapped[str | None] = mapped_column(String(200))
    # Remote agent ID reference
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # pending | submitted | in_progress | completed | failed | cancelled | timeout
    callback_url: Mapped[str | None] = mapped_column(String(500))
    callback_token: Mapped[str | None] = mapped_column(String(200), unique=True)
    external_task_id: Mapped[str | None] = mapped_column(String(200))
    # Task ID on the remote system
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class A2AEventLog(Base):
    """Audit log for all A2A cross-instance interactions."""

    __tablename__ = "a2a_event_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("a2a_tasks.id", ondelete="SET NULL"), index=True
    )
    instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("a2a_remote_instances.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Events: instance_registered, instance_synced, task_created, task_submitted,
    #         task_completed, task_failed, callback_received, auth_failed
    direction: Mapped[str] = mapped_column(String(16), default="outbound", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
