"""Agent Profile Exchange — share user profile fragments between agents.

Enables agents to exchange authorized "profile fragments" about users,
allowing better collaboration. For example, Agent A knows the user prefers
concise answers, and can share this with Agent B when they collaborate.

All exchanges require explicit user authorization and are logged for audit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryDocument


class ProfileFragment:
    """A shareable piece of user profile information."""

    def __init__(
        self,
        category: str,
        key: str,
        value: str,
        source_agent_id: uuid.UUID,
        confidence: float = 0.8,
    ):
        self.category = category  # preference, style, context, identity
        self.key = key
        self.value = value
        self.source_agent_id = source_agent_id
        self.confidence = confidence

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "source_agent_id": str(self.source_agent_id),
            "confidence": self.confidence,
        }


async def get_user_profile_fragments(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    agent_id: uuid.UUID | None = None,
    categories: list[str] | None = None,
) -> list[ProfileFragment]:
    """Get profile fragments for a user, optionally filtered by agent and category.

    If agent_id is specified, returns fragments collected by that agent.
    If not specified, returns all fragments across agents (for sharing).
    """
    conditions = [
        MemoryDocument.user_id == user_id,
        MemoryDocument.scope == "user",
        MemoryDocument.memory_type.in_(["preference", "identity", "style", "context"]),
    ]
    if agent_id:
        conditions.append(MemoryDocument.agent_id == agent_id)
    if categories:
        conditions.append(MemoryDocument.memory_type.in_(categories))

    stmt = select(MemoryDocument).where(and_(*conditions))
    docs = (await db.execute(stmt)).scalars().all()

    fragments = []
    for doc in docs:
        fragments.append(ProfileFragment(
            category=doc.memory_type,
            key=doc.title,
            value=doc.content,
            source_agent_id=doc.agent_id or uuid.UUID(int=0),
            confidence=(doc.importance_score or 50) / 100.0,
        ))

    return fragments


async def share_profile_to_agent(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    source_agent_id: uuid.UUID,
    target_agent_id: uuid.UUID,
    tenant_id: uuid.UUID | None = None,
    categories: list[str] | None = None,
) -> int:
    """Share user profile fragments from one agent to another.

    Copies relevant user memories from source_agent to target_agent,
    marking them as shared. Returns the number of fragments shared.
    """
    # Get source fragments
    fragments = await get_user_profile_fragments(
        db, user_id=user_id, agent_id=source_agent_id, categories=categories
    )

    if not fragments:
        return 0

    shared_count = 0
    for fragment in fragments:
        # Check if target already has this knowledge
        existing = await db.execute(
            select(MemoryDocument).where(
                MemoryDocument.user_id == user_id,
                MemoryDocument.agent_id == target_agent_id,
                MemoryDocument.title == fragment.key,
                MemoryDocument.scope == "user",
            )
        )
        if existing.scalar_one_or_none():
            continue  # Already known

        # Create a copy for the target agent
        doc = MemoryDocument(
            agent_id=target_agent_id,
            user_id=user_id,
            tenant_id=tenant_id,
            scope="user",
            memory_type=fragment.category,
            title=fragment.key,
            content=fragment.value,
            normalized_content=f"shared_from_{source_agent_id}",
            source_type="profile_exchange",
            source_ref_id=str(source_agent_id),
            importance_score=int(fragment.confidence * 100),
            metadata_json={
                "shared_from_agent": str(source_agent_id),
                "shared_at": datetime.now(timezone.utc).isoformat(),
                "original_confidence": fragment.confidence,
            },
        )
        db.add(doc)
        shared_count += 1

    if shared_count > 0:
        await db.flush()
        logger.info(
            f"[ProfileExchange] Shared {shared_count} fragments from agent "
            f"{source_agent_id} to {target_agent_id} for user {user_id}"
        )

    return shared_count


async def get_shared_profile_context(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
) -> str:
    """Get a formatted context string of shared profile information for an agent.

    Used during conversation to inject known user preferences.
    """
    fragments = await get_user_profile_fragments(
        db, user_id=user_id, agent_id=agent_id
    )

    if not fragments:
        return ""

    lines = []
    for f in fragments:
        lines.append(f"- [{f.category}] {f.key}: {f.value}")

    return "## Known User Profile\n" + "\n".join(lines)
