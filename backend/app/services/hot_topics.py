"""Hot Topic Analysis — detect frequently asked questions with knowledge gaps.

Analyzes conversation patterns to identify:
1. High-frequency questions across the team
2. Questions that agents fail to answer well (low feedback scores)
3. Knowledge base gaps that should be filled

Results are surfaced to admins as actionable suggestions.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import AnswerFeedback, GoldenExample


class HotTopic:
    """A detected hot topic / knowledge gap."""

    def __init__(
        self,
        topic: str,
        frequency: int,
        negative_feedback_count: int,
        sample_questions: list[str],
        has_golden_example: bool = False,
        suggested_action: str = "add_to_kb",
    ):
        self.topic = topic
        self.frequency = frequency
        self.negative_feedback_count = negative_feedback_count
        self.sample_questions = sample_questions
        self.has_golden_example = has_golden_example
        self.suggested_action = suggested_action

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "frequency": self.frequency,
            "negative_feedback_count": self.negative_feedback_count,
            "sample_questions": self.sample_questions[:5],
            "has_golden_example": self.has_golden_example,
            "suggested_action": self.suggested_action,
        }


async def analyze_hot_topics(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    days: int = 30,
    min_frequency: int = 3,
    limit: int = 20,
) -> list[HotTopic]:
    """Analyze recent conversations to find hot topics and knowledge gaps.

    Algorithm:
    1. Collect all negative feedback (thumbs down) from the period
    2. Normalize and cluster questions by similarity
    3. Count frequency of similar questions
    4. Check if golden examples exist for these topics
    5. Rank by frequency * negative_ratio
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Get negative feedback
    conditions = [
        AnswerFeedback.feedback_type == "negative",
        AnswerFeedback.created_at >= cutoff,
    ]
    if tenant_id:
        conditions.append(AnswerFeedback.tenant_id == tenant_id)
    if agent_id:
        conditions.append(AnswerFeedback.agent_id == agent_id)

    stmt = select(AnswerFeedback).where(and_(*conditions))
    feedbacks = (await db.execute(stmt)).scalars().all()

    if not feedbacks:
        return []

    # Cluster questions by normalized form
    clusters: dict[str, list[str]] = defaultdict(list)
    for fb in feedbacks:
        question = fb.question_snapshot or ""
        if not question.strip():
            continue
        normalized = _normalize_question(question)
        if normalized:
            clusters[normalized].append(question)

    # Check existing golden examples
    golden_topics: set[str] = set()
    golden_result = await db.execute(
        select(GoldenExample.normalized_question).where(
            GoldenExample.status == "approved"
        )
    )
    for row in golden_result.scalars().all():
        golden_topics.add(row)

    # Build hot topics
    topics: list[HotTopic] = []
    for normalized, questions in clusters.items():
        if len(questions) < min_frequency:
            continue

        has_golden = normalized in golden_topics
        suggested_action = "review_existing" if has_golden else "add_to_kb"

        topics.append(HotTopic(
            topic=_extract_topic_label(questions),
            frequency=len(questions),
            negative_feedback_count=len(questions),
            sample_questions=questions[:5],
            has_golden_example=has_golden,
            suggested_action=suggested_action,
        ))

    # Sort by frequency (descending)
    topics.sort(key=lambda t: t.frequency, reverse=True)
    return topics[:limit]


async def get_knowledge_gap_summary(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    days: int = 30,
) -> dict:
    """Get a summary of knowledge gaps for admin dashboard.

    Returns:
    - total_negative_feedback: Total thumbs-down in period
    - uncovered_topics: Topics without golden examples
    - coverage_rate: Percentage of topics with golden examples
    - top_gaps: Top 10 uncovered topics
    """
    topics = await analyze_hot_topics(
        db, tenant_id=tenant_id, days=days, min_frequency=2, limit=50
    )

    total_negative = sum(t.frequency for t in topics)
    uncovered = [t for t in topics if not t.has_golden_example]
    covered = [t for t in topics if t.has_golden_example]

    coverage_rate = len(covered) / len(topics) * 100 if topics else 100.0

    return {
        "period_days": days,
        "total_negative_feedback": total_negative,
        "total_topics_detected": len(topics),
        "uncovered_topics_count": len(uncovered),
        "coverage_rate": round(coverage_rate, 1),
        "top_gaps": [t.to_dict() for t in uncovered[:10]],
        "top_covered": [t.to_dict() for t in covered[:5]],
    }


# ── Helpers ─────────────────────────────────────────


def _normalize_question(question: str) -> str:
    """Normalize a question for clustering."""
    text = question.lower().strip()
    # Remove punctuation
    text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove very short results
    if len(text) < 5:
        return ""
    return text


def _extract_topic_label(questions: list[str]) -> str:
    """Extract a representative label from a cluster of similar questions."""
    if not questions:
        return "Unknown"
    # Use the shortest question as the label (usually most concise)
    sorted_by_len = sorted(questions, key=len)
    label = sorted_by_len[0].strip()
    # Truncate if too long
    if len(label) > 100:
        label = label[:97] + "..."
    return label
