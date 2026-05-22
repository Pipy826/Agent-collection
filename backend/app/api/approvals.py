"""Approval Center API — manage dangerous operation approvals.

Provides endpoints for:
- Listing pending approvals for the current user
- Approving or rejecting requests
- Creating approval requests (called by agent execution pipeline)
- Viewing approval history
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.audit import ApprovalRequest
from app.models.agent import Agent
from app.models.user import User

router = APIRouter(prefix="/approvals", tags=["approvals"])


# ── Schemas ─────────────────────────────────────────


class ApprovalRequestCreate(BaseModel):
    agent_id: uuid.UUID
    action_type: str = Field(..., max_length=64)
    action_description: str = Field(..., max_length=1000)
    action_details: dict = Field(default_factory=dict)
    risk_level: str = Field(default="medium")


class ApprovalOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str = ""
    action_type: str
    action_description: str
    details: dict
    risk_level: str
    status: str
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None = None
    created_at: datetime


class ApprovalResolve(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    note: str | None = None


# ── Endpoints ───────────────────────────────────────


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    status_filter: str | None = Query(default="pending", alias="status"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List approval requests for the current user's tenant."""
    conditions = [ApprovalRequest.status == status_filter] if status_filter else []

    stmt = (
        select(ApprovalRequest)
        .where(and_(*conditions) if conditions else True)
        .order_by(desc(ApprovalRequest.created_at))
        .limit(limit)
    )
    approvals = (await db.execute(stmt)).scalars().all()

    # Get agent names
    agent_ids = {a.agent_id for a in approvals}
    agent_names = {}
    if agent_ids:
        agents_result = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        agent_names = {a.id: a.name for a in agents_result.scalars().all()}

    return [
        ApprovalOut(
            id=a.id,
            agent_id=a.agent_id,
            agent_name=agent_names.get(a.agent_id, "Unknown"),
            action_type=a.action_type,
            action_description=a.action_type,
            details=a.details or {},
            risk_level=a.details.get("risk_level", "medium") if a.details else "medium",
            status=a.status,
            resolved_by=a.resolved_by,
            resolved_at=a.resolved_at,
            created_at=a.created_at,
        )
        for a in approvals
    ]


@router.post("", response_model=ApprovalOut)
async def create_approval(
    body: ApprovalRequestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new approval request (typically called by agent execution pipeline)."""
    # Verify agent exists
    result = await db.execute(select(Agent).where(Agent.id == body.agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    approval = ApprovalRequest(
        agent_id=body.agent_id,
        action_type=body.action_type,
        details={
            "description": body.action_description,
            "risk_level": body.risk_level,
            **body.action_details,
        },
    )
    db.add(approval)
    await db.flush()

    logger.info(
        f"[Approval] Created request {approval.id} for agent {agent.name}: "
        f"{body.action_type} ({body.risk_level})"
    )

    return ApprovalOut(
        id=approval.id,
        agent_id=approval.agent_id,
        agent_name=agent.name,
        action_type=approval.action_type,
        action_description=body.action_description,
        details=approval.details or {},
        risk_level=body.risk_level,
        status=approval.status,
        resolved_by=None,
        resolved_at=None,
        created_at=approval.created_at,
    )


@router.post("/{approval_id}/resolve", response_model=ApprovalOut)
async def resolve_approval(
    approval_id: uuid.UUID,
    body: ApprovalResolve,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject an approval request."""
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(404, "Approval request not found")

    if approval.status != "pending":
        raise HTTPException(400, f"Approval is already {approval.status}")

    # Resolve
    approval.status = "approved" if body.action == "approve" else "rejected"
    approval.resolved_by = user.id
    approval.resolved_at = datetime.now(timezone.utc)
    await db.flush()

    # Get agent name
    agent_result = await db.execute(select(Agent).where(Agent.id == approval.agent_id))
    agent = agent_result.scalar_one_or_none()

    logger.info(
        f"[Approval] Request {approval_id} {approval.status} by {user.email}: "
        f"{approval.action_type}"
    )

    return ApprovalOut(
        id=approval.id,
        agent_id=approval.agent_id,
        agent_name=agent.name if agent else "Unknown",
        action_type=approval.action_type,
        action_description=approval.action_type,
        details=approval.details or {},
        risk_level=(approval.details or {}).get("risk_level", "medium"),
        status=approval.status,
        resolved_by=approval.resolved_by,
        resolved_at=approval.resolved_at,
        resolution_note=body.note,
        created_at=approval.created_at,
    )


@router.get("/stats")
async def approval_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get approval statistics for the dashboard."""
    from sqlalchemy import func as sa_func

    # Count by status
    stmt = (
        select(ApprovalRequest.status, sa_func.count(ApprovalRequest.id))
        .group_by(ApprovalRequest.status)
    )
    status_counts = {row[0]: row[1] for row in (await db.execute(stmt)).all()}

    return {
        "pending": status_counts.get("pending", 0),
        "approved": status_counts.get("approved", 0),
        "rejected": status_counts.get("rejected", 0),
    }
