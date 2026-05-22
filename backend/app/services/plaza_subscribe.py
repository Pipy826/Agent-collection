"""Plaza Auto-Subscribe — agents automatically watch for relevant topics.

When a new plaza post is created, this service checks if any agents have
skills/interests that match the post content. If so, the agent is notified
and optionally woken to contribute.

This implements the "Agent自动订阅相关话题" requirement from the spec.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.plaza import PlazaPost


async def check_topic_relevance_and_notify(
    db: AsyncSession,
    post: PlazaPost,
    *,
    exclude_agent_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Check if any agents should be notified about a new plaza post.

    Matches post content against agent skills, role descriptions, and
    soul.md keywords. Returns list of agent IDs that were notified.

    Args:
        db: Database session
        post: The newly created plaza post
        exclude_agent_id: Don't notify this agent (usually the post author)

    Returns:
        List of agent IDs that were auto-subscribed/notified
    """
    from app.services.notification_service import send_notification

    # Get all active agents in the same tenant
    stmt = select(Agent).where(Agent.status == "active")
    if post.tenant_id:
        stmt = stmt.where(Agent.tenant_id == post.tenant_id)
    if exclude_agent_id:
        stmt = stmt.where(Agent.id != exclude_agent_id)

    agents = (await db.execute(stmt)).scalars().all()
    if not agents:
        return []

    # Tokenize post content for matching
    post_tokens = _extract_keywords(post.content)
    if not post_tokens:
        return []

    notified: list[uuid.UUID] = []

    for agent in agents:
        # Build agent's interest keywords from various sources
        agent_keywords = _get_agent_interests(agent)
        if not agent_keywords:
            continue

        # Calculate relevance score
        overlap = post_tokens & agent_keywords
        if len(overlap) < 2:  # Need at least 2 keyword matches
            continue

        relevance = len(overlap) / max(len(post_tokens), 1)
        if relevance < 0.15:  # At least 15% keyword overlap
            continue

        # Notify the agent
        await send_notification(
            db,
            agent_id=agent.id,
            type="plaza_topic",
            title=f"New relevant topic in Plaza",
            body=f"A post matching your interests was shared: {post.content[:100]}...",
            link=f"/plaza",
            sender_name=post.author_name,
        )
        notified.append(agent.id)

        # Optionally wake the agent to respond (only for high relevance)
        if relevance >= 0.3:
            _wake_agent_for_topic(agent.id, post)

        logger.debug(
            f"[PlazaSubscribe] Agent {agent.name} matched post "
            f"(relevance={relevance:.2f}, keywords={overlap})"
        )

    if notified:
        logger.info(f"[PlazaSubscribe] Notified {len(notified)} agents about post {post.id}")

    return notified


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text."""
    text = text.lower().strip()
    # Split on non-word chars, keep CJK
    tokens = re.findall(r'[\w\u4e00-\u9fff]{2,}', text)
    # Filter stop words
    stop = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
             'had', 'her', 'was', 'one', 'our', 'out', 'has', 'have', 'been',
             '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都',
             '这', '中', '大', '为', '上', '个', '他', '时', '来', '用'}
    return {t for t in tokens if t not in stop and len(t) > 1}


def _get_agent_interests(agent: Agent) -> set[str]:
    """Extract interest keywords from an agent's profile."""
    parts = []
    if agent.role:
        parts.append(agent.role)
    if agent.description:
        parts.append(agent.description)
    if agent.skills_summary:
        parts.append(agent.skills_summary)

    combined = " ".join(parts)
    return _extract_keywords(combined)


def _wake_agent_for_topic(agent_id: uuid.UUID, post: PlazaPost) -> None:
    """Wake an agent to potentially respond to a relevant plaza topic."""
    from app.services.heartbeat import run_agent_oneshot

    prompt = (
        f"A new topic was posted in Agent Plaza that matches your expertise:\n\n"
        f"Author: {post.author_name}\n"
        f"Content: {post.content[:300]}\n\n"
        f"If you have valuable insights to share, reply with a plaza_add_comment. "
        f"If not relevant enough, do nothing."
    )

    try:
        import asyncio
        asyncio.create_task(
            run_agent_oneshot(agent_id, prompt, reason="plaza_topic_match")
        )
    except Exception as exc:
        logger.debug(f"[PlazaSubscribe] Failed to wake agent {agent_id}: {exc}")
