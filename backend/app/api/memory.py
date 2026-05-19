"""Long-term memory and self-learning loop APIs."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.permissions import check_agent_access
from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import Agent
from app.models.audit import ChatMessage
from app.models.memory import AnswerFeedback, GoldenExample, MemoryDocument
from app.models.user import User
from app.schemas.schemas import (
    AnswerFeedbackCreate,
    AnswerFeedbackOut,
    GoldenExampleOut,
    GoldenExampleReview,
    KnowledgeGapOut,
    MemoryDocumentCreate,
    MemoryDocumentOut,
    MemoryRebuildOut,
    MemorySearchItem,
    MemorySearchRequest,
    MemorySearchResponse,
)

router = APIRouter(tags=["memory"])
settings = get_settings()
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".log", ".html", ".htm"}


def _normalize_text(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(value: str) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()
    return {token for token in normalized.split(" ") if len(token) > 1}


def _score_text(query: str, candidate: str) -> float:
    query_norm = _normalize_text(query)
    candidate_norm = _normalize_text(candidate)
    if not query_norm or not candidate_norm:
        return 0.0

    query_tokens = _tokenize(query_norm)
    candidate_tokens = _tokenize(candidate_norm)
    overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
    contains_bonus = 0.25 if query_norm in candidate_norm else 0.0
    reverse_contains_bonus = 0.15 if candidate_norm in query_norm else 0.0
    seq_ratio = SequenceMatcher(None, query_norm, candidate_norm).ratio()
    return overlap * 0.5 + seq_ratio * 0.35 + contains_bonus + reverse_contains_bonus


def _memory_out(row: MemoryDocument) -> MemoryDocumentOut:
    return MemoryDocumentOut.model_validate(row)


def _feedback_out(row: AnswerFeedback) -> AnswerFeedbackOut:
    return AnswerFeedbackOut.model_validate(row)


def _golden_out(row: GoldenExample) -> GoldenExampleOut:
    return GoldenExampleOut.model_validate(row)


def _enterprise_info_dir(tenant_id: str) -> Path:
    return Path(settings.AGENT_DATA_DIR) / f"enterprise_info_{tenant_id}"


async def _find_prior_user_question(
    db: AsyncSession, *, conversation_id: str, before: datetime, agent_id: uuid.UUID
) -> str | None:
    result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.agent_id == agent_id,
            ChatMessage.role == "user",
            ChatMessage.created_at < before,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row.content if row else None


def _extract_preference_candidates(text: str) -> list[tuple[str, str]]:
    patterns = [
        ("preference", r"(?:我喜欢|我偏好|我更喜欢|please use|prefer)\s*(.+)"),
        ("preference", r"(?:不要|别|请不要)\s*(.+)"),
        ("fact", r"(?:记住|请记住)\s*(.+)"),
    ]
    matches: list[tuple[str, str]] = []
    for memory_type, pattern in patterns:
        found = re.findall(pattern, text, flags=re.IGNORECASE)
        for item in found:
            content = item.strip(" .。!！?？")
            if len(content) >= 4:
                matches.append((memory_type, content))
    return matches


async def _search_enterprise_kb(tenant_id: uuid.UUID | None, query: str, limit: int) -> list[MemorySearchItem]:
    if not tenant_id:
        return []
    root = _enterprise_info_dir(str(tenant_id))
    if not root.exists():
        return []

    results: list[MemorySearchItem] = []
    scanned = 0
    for path in root.rglob("*"):
        if scanned >= 40:
            break
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        scanned += 1
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        score = _score_text(query, f"{path.name}\n{content[:2500]}")
        if score < 0.18:
            continue
        snippet = content.strip().replace("\n", " ")
        if len(snippet) > 240:
            snippet = f"{snippet[:237]}..."
        results.append(
            MemorySearchItem(
                source="enterprise_kb",
                score=round(score, 4),
                title=path.name,
                content=snippet,
                metadata={"path": str(path.relative_to(root))},
            )
        )
    results.sort(key=lambda item: item.score, reverse=True)
    return results[:limit]


async def _upsert_memory_document(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    created_by: uuid.UUID | None,
    scope: str,
    memory_type: str,
    title: str,
    content: str,
    source_type: str,
    source_ref_id: str | None = None,
    importance_score: int = 50,
    visibility: str = "private",
    is_verified: bool = False,
    metadata_json: dict | None = None,
) -> MemoryDocument:
    normalized = _normalize_text(content)
    existing = await db.execute(
        select(MemoryDocument)
        .where(
            MemoryDocument.agent_id == agent_id,
            MemoryDocument.user_id == user_id,
            MemoryDocument.scope == scope,
            MemoryDocument.memory_type == memory_type,
            MemoryDocument.normalized_content == normalized,
        )
        .limit(1)
    )
    row = existing.scalar_one_or_none()
    if row:
        row.title = title
        row.content = content
        row.source_type = source_type
        row.source_ref_id = source_ref_id
        row.importance_score = max(row.importance_score, importance_score)
        row.visibility = visibility
        row.is_verified = row.is_verified or is_verified
        row.metadata_json = {**(row.metadata_json or {}), **(metadata_json or {})}
        return row

    row = MemoryDocument(
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        created_by=created_by,
        scope=scope,
        memory_type=memory_type,
        title=title,
        content=content,
        normalized_content=normalized,
        source_type=source_type,
        source_ref_id=source_ref_id,
        importance_score=importance_score,
        visibility=visibility,
        is_verified=is_verified,
        metadata_json=metadata_json or {},
    )
    db.add(row)
    return row


@router.get("/agents/{agent_id}/memory", response_model=list[MemoryDocumentOut])
async def list_agent_memory(
    agent_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent, _ = await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(MemoryDocument)
        .where(
            MemoryDocument.agent_id == agent_id,
            MemoryDocument.tenant_id == agent.tenant_id,
        )
        .order_by(MemoryDocument.importance_score.desc(), MemoryDocument.updated_at.desc())
        .limit(limit)
    )
    return [_memory_out(row) for row in result.scalars().all()]


@router.post("/agents/{agent_id}/memory", response_model=MemoryDocumentOut, status_code=status.HTTP_201_CREATED)
async def create_agent_memory(
    agent_id: uuid.UUID,
    body: MemoryDocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent, access_level = await check_agent_access(db, current_user, agent_id)
    if access_level != "manage" and current_user.role not in ("platform_admin", "org_admin"):
        raise HTTPException(status_code=403, detail="Only managers can create memory entries")

    row = await _upsert_memory_document(
        db,
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        user_id=body.user_id,
        created_by=current_user.id,
        scope=body.scope,
        memory_type=body.memory_type,
        title=body.title,
        content=body.content,
        source_type=body.source_type,
        source_ref_id=body.source_ref_id,
        importance_score=body.importance_score,
        visibility=body.visibility,
        is_verified=body.is_verified,
        metadata_json=body.metadata_json,
    )
    await db.commit()
    await db.refresh(row)
    return _memory_out(row)


@router.post("/agents/{agent_id}/memory/search", response_model=MemorySearchResponse)
async def search_agent_memory(
    agent_id: uuid.UUID,
    body: MemorySearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent, _ = await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(MemoryDocument).where(
            MemoryDocument.tenant_id == agent.tenant_id,
            (MemoryDocument.agent_id == agent_id)
            | (MemoryDocument.scope == "tenant")
            | ((MemoryDocument.user_id == current_user.id) & (MemoryDocument.scope == "user")),
        )
    )

    items: list[MemorySearchItem] = []
    for row in result.scalars().all():
        score = _score_text(body.query, f"{row.title}\n{row.content}")
        if score < 0.18:
            continue
        items.append(
            MemorySearchItem(
                source="memory",
                score=round(score + min(row.importance_score / 200.0, 0.25), 4),
                title=row.title,
                content=row.content,
                memory_id=row.id,
                metadata={
                    "scope": row.scope,
                    "memory_type": row.memory_type,
                    "source_type": row.source_type,
                    "visibility": row.visibility,
                },
            )
        )

    golden_result = await db.execute(
        select(GoldenExample).where(
            GoldenExample.tenant_id == agent.tenant_id,
            GoldenExample.status.in_(["approved", "active"]),
            (GoldenExample.agent_id.is_(None)) | (GoldenExample.agent_id == agent_id),
        )
    )
    for row in golden_result.scalars().all():
        score = _score_text(body.query, row.question)
        if score < 0.2:
            continue
        items.append(
            MemorySearchItem(
                source="golden_example",
                score=round(score + 0.3, 4),
                title="Reviewed correction",
                content=row.correct_answer,
                golden_example_id=row.id,
                metadata={"question": row.question, "status": row.status},
            )
        )

    items.extend(await _search_enterprise_kb(agent.tenant_id, body.query, body.limit))
    items.sort(key=lambda item: item.score, reverse=True)
    return MemorySearchResponse(items=items[: body.limit], total=len(items))


@router.post("/agents/{agent_id}/memory/rebuild", response_model=MemoryRebuildOut)
async def rebuild_agent_memory(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent, access_level = await check_agent_access(db, current_user, agent_id)
    if access_level != "manage" and current_user.role not in ("platform_admin", "org_admin"):
        raise HTTPException(status_code=403, detail="Only managers can rebuild memory")

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.agent_id == agent_id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.desc())
        .limit(200)
    )
    created = 0
    scanned = 0
    for msg in result.scalars().all():
        scanned += 1
        for memory_type, content in _extract_preference_candidates(msg.content or ""):
            before = await db.execute(
                select(MemoryDocument).where(
                    MemoryDocument.agent_id == agent_id,
                    MemoryDocument.user_id == msg.user_id,
                    MemoryDocument.normalized_content == _normalize_text(content),
                )
            )
            existed = before.scalar_one_or_none()
            row = await _upsert_memory_document(
                db,
                tenant_id=agent.tenant_id,
                agent_id=agent_id,
                user_id=msg.user_id,
                created_by=current_user.id,
                scope="user",
                memory_type=memory_type,
                title=f"Preference from chat ({memory_type})",
                content=content,
                source_type="chat_history",
                source_ref_id=str(msg.id),
                importance_score=70,
                visibility="private",
                metadata_json={"conversation_id": msg.conversation_id},
            )
            if not existed and row:
                created += 1

    await db.commit()
    return MemoryRebuildOut(scanned_messages=scanned, created_memories=created, status="ok")


@router.post("/messages/{message_id}/feedback", response_model=AnswerFeedbackOut)
async def submit_message_feedback(
    message_id: uuid.UUID,
    body: AnswerFeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg_result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    message = msg_result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.role != "assistant":
        raise HTTPException(status_code=400, detail="Feedback only applies to assistant messages")

    agent_result = await db.execute(select(Agent).where(Agent.id == message.agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await check_agent_access(db, current_user, message.agent_id)

    prior_question = await _find_prior_user_question(
        db,
        conversation_id=message.conversation_id,
        before=message.created_at or datetime.now(timezone.utc),
        agent_id=message.agent_id,
    )

    existing_result = await db.execute(
        select(AnswerFeedback).where(
            AnswerFeedback.message_id == message_id,
            AnswerFeedback.user_id == current_user.id,
        )
    )
    feedback = existing_result.scalar_one_or_none()
    if not feedback:
        feedback = AnswerFeedback(
            tenant_id=agent.tenant_id,
            message_id=message_id,
            agent_id=message.agent_id,
            user_id=current_user.id,
            feedback_type=body.feedback_type,
        )
        db.add(feedback)

    feedback.feedback_type = body.feedback_type
    feedback.comment = body.comment
    feedback.corrected_answer = body.corrected_answer
    feedback.question_snapshot = prior_question
    feedback.normalized_question = _normalize_text(prior_question or "")
    await db.flush()

    if body.feedback_type == "downvote" and body.corrected_answer and prior_question:
        golden_result = await db.execute(
            select(GoldenExample).where(GoldenExample.source_feedback_id == feedback.id)
        )
        golden = golden_result.scalar_one_or_none()
        if not golden:
            golden = GoldenExample(
                tenant_id=agent.tenant_id,
                agent_id=agent.id,
                source_feedback_id=feedback.id,
                question=prior_question,
                normalized_question=_normalize_text(prior_question),
                correct_answer=body.corrected_answer,
                status="pending_review",
                tags=[],
            )
            db.add(golden)
        else:
            golden.question = prior_question
            golden.normalized_question = _normalize_text(prior_question)
            golden.correct_answer = body.corrected_answer
            if golden.status == "rejected":
                golden.status = "pending_review"

        await _upsert_memory_document(
            db,
            tenant_id=agent.tenant_id,
            agent_id=agent.id,
            user_id=current_user.id,
            created_by=current_user.id,
            scope="agent",
            memory_type="correction",
            title="Corrected answer from user feedback",
            content=body.corrected_answer,
            source_type="feedback",
            source_ref_id=str(feedback.id),
            importance_score=85,
            visibility="team",
            is_verified=False,
            metadata_json={"question": prior_question},
        )

    await db.commit()
    await db.refresh(feedback)
    return _feedback_out(feedback)


@router.get("/agents/{agent_id}/feedback", response_model=list[AnswerFeedbackOut])
async def list_agent_feedback(
    agent_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(AnswerFeedback)
        .where(AnswerFeedback.agent_id == agent_id)
        .order_by(AnswerFeedback.created_at.desc())
        .limit(limit)
    )
    return [_feedback_out(row) for row in result.scalars().all()]


@router.get("/enterprise/golden-examples", response_model=list[GoldenExampleOut])
async def list_golden_examples(
    status_filter: str | None = Query(default=None, alias="status"),
    agent_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.tenant_id:
        return []
    stmt = select(GoldenExample).where(GoldenExample.tenant_id == current_user.tenant_id)
    if status_filter:
        stmt = stmt.where(GoldenExample.status == status_filter)
    if agent_id:
        stmt = stmt.where(GoldenExample.agent_id == agent_id)
    stmt = stmt.order_by(GoldenExample.created_at.desc())
    result = await db.execute(stmt)
    return [_golden_out(row) for row in result.scalars().all()]


@router.post("/enterprise/golden-examples/{example_id}/review", response_model=GoldenExampleOut)
async def review_golden_example(
    example_id: uuid.UUID,
    body: GoldenExampleReview,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ("platform_admin", "org_admin"):
        raise HTTPException(status_code=403, detail="Only admins can review golden examples")
    result = await db.execute(select(GoldenExample).where(GoldenExample.id == example_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Golden example not found")
    if row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="No access to this golden example")

    row.status = body.status
    row.review_note = body.review_note
    row.reviewed_by = current_user.id
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _golden_out(row)


@router.get("/enterprise/knowledge-gaps", response_model=list[KnowledgeGapOut])
async def list_knowledge_gaps(
    agent_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.tenant_id:
        return []

    result = await db.execute(
        select(AnswerFeedback).where(
            AnswerFeedback.tenant_id == current_user.tenant_id,
            AnswerFeedback.feedback_type == "downvote",
        )
    )
    grouped: dict[str, dict] = {}
    for row in result.scalars().all():
        if agent_id and row.agent_id != agent_id:
            continue
        normalized = row.normalized_question or _normalize_text(row.question_snapshot or "")
        if not normalized:
            continue
        item = grouped.setdefault(
            normalized,
            {
                "question_cluster": row.question_snapshot or normalized,
                "frequency": 0,
                "affected_agent_ids": set(),
                "sample_questions": [],
                "pending_feedback_count": 0,
            },
        )
        item["frequency"] += 1
        item["affected_agent_ids"].add(str(row.agent_id))
        item["pending_feedback_count"] += 1
        if row.question_snapshot and row.question_snapshot not in item["sample_questions"]:
            item["sample_questions"].append(row.question_snapshot)

    golden_result = await db.execute(
        select(GoldenExample).where(GoldenExample.tenant_id == current_user.tenant_id)
    )
    active_by_question: dict[str, int] = {}
    for row in golden_result.scalars().all():
        if row.status in ("approved", "active"):
            active_by_question[row.normalized_question] = active_by_question.get(row.normalized_question, 0) + 1

    items: list[KnowledgeGapOut] = []
    for normalized, data in grouped.items():
        active_count = active_by_question.get(normalized, 0)
        items.append(
            KnowledgeGapOut(
                question_cluster=data["question_cluster"],
                frequency=data["frequency"],
                affected_agent_ids=sorted(data["affected_agent_ids"]),
                active_example_count=active_count,
                pending_feedback_count=data["pending_feedback_count"],
                suggested_action="Review corrected answers and promote one to active knowledge"
                if active_count == 0
                else "Refine the existing golden answer and expand enterprise knowledge coverage",
                sample_questions=data["sample_questions"][:3],
            )
        )

    items.sort(key=lambda item: (item.frequency, item.pending_feedback_count), reverse=True)
    return items[:limit]
