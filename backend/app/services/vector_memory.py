"""Vector-based semantic memory for long-term agent recall.

Provides embedding-based similarity search for agent memories, enabling
cross-session recall and semantic matching beyond keyword overlap.

Phase 1 uses a lightweight local approach with sentence-level TF-IDF vectors
stored in SQLite/PostgreSQL JSON columns. This can be upgraded to a dedicated
vector DB (FAISS, ChromaDB, Qdrant) in Phase 2.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryDocument


# ── Lightweight TF-IDF Vector Engine ────────────────────────────────


_STOP_WORDS = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "but", "and", "or", "if", "while", "about",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "这", "中", "大", "为", "上", "个", "国", "他", "时", "来", "用", "们",
    "生", "到", "作", "地", "于", "出", "会", "可", "也", "你", "对", "要",
])


def _tokenize(text: str) -> list[str]:
    """Tokenize text into meaningful terms."""
    text = text.lower().strip()
    # Split on non-word characters, keep CJK characters as individual tokens
    tokens = re.findall(r'[\w\u4e00-\u9fff]+', text)
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    """Compute term frequency vector."""
    counter = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {term: count / total for term, count in counter.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors."""
    if not vec_a or not vec_b:
        return 0.0

    # Dot product
    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    dot = sum(vec_a[k] * vec_b[k] for k in common_keys)

    # Magnitudes
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def compute_text_vector(text: str) -> dict[str, float]:
    """Compute a TF vector for a text string."""
    tokens = _tokenize(text)
    return _compute_tf(tokens)


def compute_content_hash(content: str) -> str:
    """Compute a content hash for deduplication."""
    return hashlib.sha256(content.strip().lower().encode()).hexdigest()[:16]


# ── Memory Storage & Retrieval ──────────────────────────────────────


async def store_memory(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    scope: str = "agent",
    memory_type: str = "fact",
    title: str,
    content: str,
    source_type: str = "auto",
    importance_score: int = 50,
    metadata: dict | None = None,
) -> MemoryDocument:
    """Store a new memory with vector representation.

    Deduplicates by content hash within the same scope.
    """
    content_hash = compute_content_hash(content)
    vector = compute_text_vector(f"{title} {content}")

    # Check for duplicate
    existing = await db.execute(
        select(MemoryDocument).where(
            MemoryDocument.agent_id == agent_id,
            MemoryDocument.normalized_content == content_hash,
        )
    )
    if existing.scalar_one_or_none():
        logger.debug(f"[VectorMemory] Duplicate memory skipped: {title[:50]}")
        return existing.scalar_one_or_none()

    doc = MemoryDocument(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        scope=scope,
        memory_type=memory_type,
        title=title,
        content=content,
        normalized_content=content_hash,
        source_type=source_type,
        importance_score=importance_score,
        metadata_json={
            **(metadata or {}),
            "_vector": vector,
            "_stored_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(doc)
    await db.flush()

    logger.debug(f"[VectorMemory] Stored memory: {title[:50]} (scope={scope})")
    return doc


async def search_memories(
    db: AsyncSession,
    query: str,
    *,
    agent_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    scope: str | None = None,
    memory_type: str | None = None,
    limit: int = 10,
    min_score: float = 0.1,
) -> list[tuple[MemoryDocument, float]]:
    """Search memories using semantic similarity.

    Returns a list of (document, similarity_score) tuples sorted by relevance.
    """
    query_vector = compute_text_vector(query)
    if not query_vector:
        return []

    # Build filter conditions
    conditions = []
    if agent_id:
        conditions.append(MemoryDocument.agent_id == agent_id)
    if user_id:
        conditions.append(MemoryDocument.user_id == user_id)
    if tenant_id:
        conditions.append(MemoryDocument.tenant_id == tenant_id)
    if scope:
        conditions.append(MemoryDocument.scope == scope)
    if memory_type:
        conditions.append(MemoryDocument.memory_type == memory_type)

    stmt = select(MemoryDocument)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    results = (await db.execute(stmt)).scalars().all()

    # Score each document
    scored: list[tuple[MemoryDocument, float]] = []
    for doc in results:
        doc_vector = (doc.metadata_json or {}).get("_vector", {})
        if not doc_vector:
            # Fallback: compute vector from content
            doc_vector = compute_text_vector(f"{doc.title} {doc.content}")

        similarity = _cosine_similarity(query_vector, doc_vector)

        # Boost by importance score
        importance_boost = (doc.importance_score or 50) / 100.0
        final_score = similarity * 0.8 + importance_boost * 0.2

        if final_score >= min_score:
            scored.append((doc, final_score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


async def get_cross_session_context(
    db: AsyncSession,
    query: str,
    *,
    agent_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    limit: int = 5,
) -> str:
    """Retrieve cross-session memory context for an agent conversation.

    Searches both agent-specific and user-specific memories to provide
    relevant context from previous interactions.
    """
    sections: list[str] = []

    # Search agent memories
    agent_memories = await search_memories(
        db, query, agent_id=agent_id, limit=limit
    )
    if agent_memories:
        lines = []
        for doc, score in agent_memories:
            lines.append(f"- [{doc.memory_type}] {doc.title}: {doc.content[:200]}")
        sections.append("## Agent Memory\n" + "\n".join(lines))

    # Search user-specific memories (cross-session preferences)
    if user_id:
        user_memories = await search_memories(
            db, query, user_id=user_id, scope="user", limit=3
        )
        if user_memories:
            lines = []
            for doc, score in user_memories:
                lines.append(f"- {doc.title}: {doc.content[:200]}")
            sections.append("## User Preferences\n" + "\n".join(lines))

    return "\n\n".join(sections) if sections else ""


async def extract_and_store_from_conversation(
    db: AsyncSession,
    *,
    agent_id: uuid.UUID,
    user_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None,
    user_message: str,
    assistant_response: str,
) -> list[MemoryDocument]:
    """Extract memorable facts from a conversation turn and store them.

    Looks for:
    - User preferences ("I prefer...", "I like...", "My name is...")
    - Important facts mentioned by the user
    - Decisions made during the conversation
    """
    stored: list[MemoryDocument] = []

    # Simple heuristic extraction (can be enhanced with LLM in Phase 2)
    preference_patterns = [
        (r"(?:i prefer|i like|i want|i need|我喜欢|我偏好|我需要)\s+(.{5,100})", "preference"),
        (r"(?:my name is|i am|i'm|我叫|我是)\s+(.{2,50})", "identity"),
        (r"(?:remember that|please note|注意|记住)\s+(.{5,200})", "instruction"),
    ]

    for pattern, mem_type in preference_patterns:
        matches = re.findall(pattern, user_message, re.IGNORECASE)
        for match in matches:
            doc = await store_memory(
                db,
                agent_id=agent_id,
                user_id=user_id,
                tenant_id=tenant_id,
                scope="user" if user_id else "agent",
                memory_type=mem_type,
                title=f"User {mem_type}: {match[:50]}",
                content=match.strip(),
                source_type="conversation",
                importance_score=60,
            )
            if doc:
                stored.append(doc)

    return stored
