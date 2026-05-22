"""A2A Router — intelligent routing to select the best remote agent for a task."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.a2a import A2ATask, RemoteAgentCard, RemoteInstance


async def find_best_agent(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    required_skills: list[str] | None = None,
    required_labels: list[str] | None = None,
    task_type: str | None = None,
    prefer_local: bool = True,
) -> RemoteAgentCard | None:
    """Find the best remote agent for a given task based on weighted scoring.

    Scoring factors:
    - Skill match (40%)
    - Availability (20%)
    - Recent success rate (20%)
    - Instance health (20%)
    """
    stmt = (
        select(RemoteAgentCard)
        .join(RemoteInstance)
        .where(
            RemoteInstance.status == "active",
            RemoteInstance.is_enabled.is_(True),
            RemoteAgentCard.availability_status == "available",
        )
    )
    if tenant_id:
        stmt = stmt.where(RemoteInstance.tenant_id == tenant_id)

    cards = (await db.execute(stmt)).scalars().all()
    if not cards:
        return None

    # Score each candidate
    scored: list[tuple[float, RemoteAgentCard]] = []
    for card in cards:
        score = await _score_candidate(db, card, required_skills, required_labels, task_type)
        if score > 0:
            scored.append((score, card))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


async def _score_candidate(
    db: AsyncSession,
    card: RemoteAgentCard,
    required_skills: list[str] | None,
    required_labels: list[str] | None,
    task_type: str | None,
) -> float:
    """Calculate a routing score for a candidate agent card."""
    score = 0.0

    # Skill match (0.4 weight)
    if required_skills:
        card_skills = set(s.lower() for s in (card.skills or []))
        matched = sum(1 for s in required_skills if s.lower() in card_skills)
        skill_score = matched / len(required_skills) if required_skills else 0
        score += skill_score * 0.4
        if matched == 0:
            return 0.0  # Must match at least one skill
    else:
        score += 0.2  # Partial credit if no skills required

    # Label match (0.1 weight)
    if required_labels:
        card_labels = set(l.lower() for l in (card.labels or []))
        matched = sum(1 for l in required_labels if l.lower() in card_labels)
        score += (matched / len(required_labels)) * 0.1

    # Task type support (0.1 weight)
    if task_type and card.supported_task_types:
        if task_type in card.supported_task_types:
            score += 0.1

    # Availability bonus (0.2 weight)
    if card.availability_status == "available":
        score += 0.2
    elif card.availability_status == "busy":
        score += 0.05

    # Recent success rate (0.2 weight)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent_tasks = await db.execute(
        select(
            func.count(A2ATask.id).label("total"),
            func.sum(func.cast(A2ATask.status == "completed", db.bind.dialect.name == "postgresql")).label("success"),
        )
        .where(
            A2ATask.target_instance_id == card.remote_instance_id,
            A2ATask.created_at >= cutoff,
        )
    )
    row = recent_tasks.first()
    if row and row.total and row.total > 0:
        success_rate = (row.success or 0) / row.total
        score += success_rate * 0.2
    else:
        score += 0.1  # No history, neutral score

    return score
