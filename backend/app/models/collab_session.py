"""Collaborative session models — multi-agent group conversations.

A CollabSession allows multiple agents and humans to participate in a single
conversation, similar to a group chat. Messages are broadcast to all participants
and agents can be @mentioned to respond.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CollabSession(Base):
    """A collaborative multi-agent conversation session."""

    __tablename__ = "collab_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    # active | archived | completed
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Settings: auto_respond (bool), round_robin (bool), etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    participants: Mapped[list["CollabParticipant"]] = relationship(
        "CollabParticipant", back_populates="session", cascade="all, delete-orphan"
    )
    messages: Mapped[list["CollabMessage"]] = relationship(
        "CollabMessage", back_populates="session", cascade="all, delete-orphan"
    )


class CollabParticipant(Base):
    """A participant (human or agent) in a collaborative session."""

    __tablename__ = "collab_participants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collab_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # "human" | "agent"
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    # owner | member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["CollabSession"] = relationship("CollabSession", back_populates="participants")


class CollabMessage(Base):
    """A message in a collaborative session."""

    __tablename__ = "collab_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("collab_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # "human" | "agent" | "system"
    sender_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sender_name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), default="text", nullable=False)
    # text | task_result | file | system_event
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Can contain: mentions (list of agent/user IDs), attachments, etc.
    mentioned_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # List of agent/user UUIDs that were @mentioned
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["CollabSession"] = relationship("CollabSession", back_populates="messages")
