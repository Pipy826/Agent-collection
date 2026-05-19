"""Memory retrieval helpers for chat-time context injection."""

from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.memory import GoldenExample, MemoryDocument

settings = get_settings()
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".log", ".html", ".htm"}


def normalize_text(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize_text(value: str) -> set[str]:
    normalized = normalize_text(value)
    if not normalized:
        return set()
    return {token for token in normalized.split(" ") if len(token) > 1}


def score_text(query: str, candidate: str) -> float:
    query_norm = normalize_text(query)
    candidate_norm = normalize_text(candidate)
    if not query_norm or not candidate_norm:
        return 0.0

    query_tokens = tokenize_text(query_norm)
    candidate_tokens = tokenize_text(candidate_norm)
    overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
    contains_bonus = 0.25 if query_norm in candidate_norm else 0.0
    reverse_contains_bonus = 0.15 if candidate_norm in query_norm else 0.0
    seq_ratio = SequenceMatcher(None, query_norm, candidate_norm).ratio()
    return overlap * 0.5 + seq_ratio * 0.35 + contains_bonus + reverse_contains_bonus


def _enterprise_info_dir(tenant_id: str) -> Path:
    return Path(settings.AGENT_DATA_DIR) / f"enterprise_info_{tenant_id}"


async def build_memory_context(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    limit: int = 8,
) -> str:
    """Build a compact retrieval block for the current user turn."""
    if not query.strip():
        return ""

    sections: list[str] = []
    scored_memory: list[tuple[float, MemoryDocument]] = []
    memory_result = await db.execute(
        select(MemoryDocument).where(
            MemoryDocument.tenant_id == tenant_id,
            (MemoryDocument.agent_id == agent_id)
            | (MemoryDocument.scope == "tenant")
            | ((MemoryDocument.user_id == user_id) & (MemoryDocument.scope == "user")),
        )
    )
    for row in memory_result.scalars().all():
        score = score_text(query, f"{row.title}\n{row.content}")
        if score >= 0.2:
            boosted = score + min((row.importance_score or 0) / 200.0, 0.25)
            scored_memory.append((boosted, row))
    scored_memory.sort(key=lambda item: item[0], reverse=True)
    top_memory = scored_memory[: min(limit, 4)]
    if top_memory:
        lines = ["## Retrieved Memory"]
        for score, row in top_memory:
            lines.append(
                f"- [{row.scope}/{row.memory_type}] {row.title}: {row.content[:280]}"
                f" (score={score:.2f})"
            )
        sections.append("\n".join(lines))

    scored_golden: list[tuple[float, GoldenExample]] = []
    golden_result = await db.execute(
        select(GoldenExample).where(
            GoldenExample.tenant_id == tenant_id,
            GoldenExample.status.in_(["approved", "active"]),
            (GoldenExample.agent_id.is_(None)) | (GoldenExample.agent_id == agent_id),
        )
    )
    for row in golden_result.scalars().all():
        score = score_text(query, row.question)
        if score >= 0.22:
            scored_golden.append((score + 0.3, row))
    scored_golden.sort(key=lambda item: item[0], reverse=True)
    top_golden = scored_golden[: min(limit, 3)]
    if top_golden:
        lines = ["## Reviewed Corrections"]
        for score, row in top_golden:
            lines.append(
                f"- Similar question: {row.question[:180]}\n"
                f"  Preferred answer: {row.correct_answer[:320]}\n"
                f"  Confidence hint: {score:.2f}"
            )
        sections.append("\n".join(lines))

    kb_lines = await _search_enterprise_kb(tenant_id, query, limit=min(limit, 3))
    if kb_lines:
        sections.append("## Enterprise Knowledge\n" + "\n".join(kb_lines))

    if not sections:
        return ""

    guidance = (
        "## Retrieval Guidance\n"
        "- Use the following retrieved context when it clearly applies.\n"
        "- Prefer reviewed corrections over conflicting informal memory.\n"
        "- Do not quote internal retrieval metadata to the user."
    )
    return "\n\n".join([guidance, *sections])


async def _search_enterprise_kb(
    tenant_id: uuid.UUID | None,
    query: str,
    limit: int,
) -> list[str]:
    if not tenant_id:
        return []
    root = _enterprise_info_dir(str(tenant_id))
    if not root.exists():
        return []

    scored: list[tuple[float, str]] = []
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
        score = score_text(query, f"{path.name}\n{content[:2500]}")
        if score < 0.2:
            continue
        snippet = content.strip().replace("\n", " ")
        if len(snippet) > 260:
            snippet = f"{snippet[:257]}..."
        scored.append((score, f"- {path.name} ({path.relative_to(root)}): {snippet}"))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [line for _score, line in scored[:limit]]
