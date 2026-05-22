"""A2A Registry — manages remote instance registration and agent card sync."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.a2a import A2AEventLog, RemoteAgentCard, RemoteInstance


async def register_instance(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    name: str,
    base_url: str,
    auth_type: str = "api_key",
    auth_credential: str | None = None,
    metadata_json: dict | None = None,
) -> RemoteInstance:
    """Register a new remote instance."""
    instance = RemoteInstance(
        tenant_id=tenant_id,
        name=name,
        base_url=base_url.rstrip("/"),
        auth_type=auth_type,
        auth_credential=auth_credential,
        metadata_json=metadata_json or {},
        status="pending",
    )
    db.add(instance)
    await db.flush()

    # Log the registration event
    db.add(A2AEventLog(
        tenant_id=tenant_id,
        instance_id=instance.id,
        event_type="instance_registered",
        direction="outbound",
        payload={"name": name, "base_url": base_url},
    ))
    await db.flush()

    logger.info(f"[A2A] Registered remote instance: {name} ({base_url})")
    return instance


async def sync_instance(db: AsyncSession, instance_id: uuid.UUID) -> RemoteInstance:
    """Sync agent cards from a remote instance by fetching its capability manifest."""
    result = await db.execute(select(RemoteInstance).where(RemoteInstance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise ValueError(f"Remote instance {instance_id} not found")

    url = f"{instance.base_url}/api/a2a/manifest"
    headers = _build_auth_headers(instance)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            manifest = resp.json()
    except Exception as exc:
        instance.status = "unreachable"
        instance.last_seen = datetime.now(timezone.utc)
        db.add(A2AEventLog(
            tenant_id=instance.tenant_id,
            instance_id=instance.id,
            event_type="sync_failed",
            direction="outbound",
            payload={"error": str(exc)},
        ))
        await db.flush()
        logger.warning(f"[A2A] Failed to sync instance {instance.name}: {exc}")
        raise

    # Update instance metadata
    instance.status = "active"
    instance.last_seen = datetime.now(timezone.utc)
    instance.last_sync_at = datetime.now(timezone.utc)
    instance.protocol_version = manifest.get("protocol_version", "0.3.0")

    # Sync agent cards
    remote_agents = manifest.get("agents", [])
    existing_cards = await db.execute(
        select(RemoteAgentCard).where(RemoteAgentCard.remote_instance_id == instance.id)
    )
    existing_map = {card.remote_agent_id: card for card in existing_cards.scalars().all()}

    seen_ids: set[str] = set()
    for agent_data in remote_agents:
        remote_id = str(agent_data.get("id", ""))
        if not remote_id:
            continue
        seen_ids.add(remote_id)

        if remote_id in existing_map:
            card = existing_map[remote_id]
            card.name = agent_data.get("name", card.name)
            card.description = agent_data.get("description", "")
            card.capabilities = agent_data.get("capabilities", {})
            card.skills = agent_data.get("skills", [])
            card.labels = agent_data.get("labels", [])
            card.availability_status = agent_data.get("status", "available")
            card.supported_task_types = agent_data.get("task_types", [])
            card.last_synced_at = datetime.now(timezone.utc)
        else:
            card = RemoteAgentCard(
                remote_instance_id=instance.id,
                remote_agent_id=remote_id,
                name=agent_data.get("name", "Unknown"),
                description=agent_data.get("description", ""),
                capabilities=agent_data.get("capabilities", {}),
                skills=agent_data.get("skills", []),
                labels=agent_data.get("labels", []),
                availability_status=agent_data.get("status", "available"),
                supported_task_types=agent_data.get("task_types", []),
                last_synced_at=datetime.now(timezone.utc),
            )
            db.add(card)

    # Remove cards for agents no longer advertised
    for remote_id, card in existing_map.items():
        if remote_id not in seen_ids:
            await db.delete(card)

    db.add(A2AEventLog(
        tenant_id=instance.tenant_id,
        instance_id=instance.id,
        event_type="instance_synced",
        direction="outbound",
        payload={"agents_count": len(remote_agents)},
    ))
    await db.flush()

    logger.info(f"[A2A] Synced instance {instance.name}: {len(remote_agents)} agents")
    return instance


async def search_remote_agents(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    skills: list[str] | None = None,
    labels: list[str] | None = None,
    query: str | None = None,
    limit: int = 20,
) -> list[RemoteAgentCard]:
    """Search remote agent cards by skills, labels, or free text."""
    stmt = (
        select(RemoteAgentCard)
        .join(RemoteInstance)
        .where(RemoteInstance.status == "active", RemoteInstance.is_enabled.is_(True))
    )
    if tenant_id:
        stmt = stmt.where(RemoteInstance.tenant_id == tenant_id)

    cards = (await db.execute(stmt)).scalars().all()

    # In-memory filtering (for Phase 1; can move to DB JSON queries later)
    results = []
    for card in cards:
        score = 0.0
        if skills:
            card_skills = set(s.lower() for s in (card.skills or []))
            match_count = sum(1 for s in skills if s.lower() in card_skills)
            if match_count > 0:
                score += match_count / len(skills)
            else:
                continue
        if labels:
            card_labels = set(l.lower() for l in (card.labels or []))
            match_count = sum(1 for l in labels if l.lower() in card_labels)
            if match_count > 0:
                score += match_count / len(labels) * 0.5
        if query:
            q = query.lower()
            if q in card.name.lower() or q in card.description.lower():
                score += 0.3
            elif not skills and not labels:
                continue
        if not skills and not labels and not query:
            score = 1.0  # Return all if no filter
        results.append((score, card))

    results.sort(key=lambda x: x[0], reverse=True)
    return [card for _, card in results[:limit]]


def _build_auth_headers(instance: RemoteInstance) -> dict[str, str]:
    """Build authentication headers for outbound requests."""
    from app.config import get_settings
    from app.core.security import decrypt_data

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if instance.auth_type == "api_key" and instance.auth_credential:
        try:
            settings = get_settings()
            api_key = decrypt_data(instance.auth_credential, settings.SECRET_KEY)
        except Exception:
            # Fallback to raw value (legacy or unencrypted)
            api_key = instance.auth_credential
        headers["Authorization"] = f"Bearer {api_key}"
    return headers
