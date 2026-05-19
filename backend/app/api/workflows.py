"""Workflow APIs for visual orchestration."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import check_agent_access
from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import Agent
from app.models.user import User
from app.models.workflow import WorkflowDefinition, WorkflowNodeRun, WorkflowRun
from app.schemas.schemas import (
    ApprovalAction,
    WorkflowDefinitionCreate,
    WorkflowDefinitionOut,
    WorkflowDefinitionUpdate,
    WorkflowRunCreate,
    WorkflowRunOut,
)
from app.services.workflow_engine import (
    WorkflowValidationError,
    execute_workflow_run,
    resume_workflow_run,
    validate_definition,
)

router = APIRouter(prefix="/agents/{agent_id}/workflows", tags=["workflows"])


def _workflow_out(row: WorkflowDefinition) -> WorkflowDefinitionOut:
    return WorkflowDefinitionOut.model_validate(row)


def _workflow_run_out(row: WorkflowRun, node_runs: list[WorkflowNodeRun] | None = None) -> WorkflowRunOut:
    payload = WorkflowRunOut.model_validate(row)
    payload.node_runs = [
        {
            "id": str(item.id),
            "node_key": item.node_key,
            "node_type": item.node_type,
            "title": item.title,
            "status": item.status,
            "attempt": item.attempt,
            "input_payload": item.input_payload,
            "output_payload": item.output_payload,
            "error_message": item.error_message,
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "finished_at": item.finished_at.isoformat() if item.finished_at else None,
        }
        for item in (node_runs or [])
    ]
    return payload


def _start_workflow_background_run(run_id: uuid.UUID, *, resume_action: str | None = None, resolved_by: uuid.UUID | None = None) -> None:
    async def _runner() -> None:
        from app.database import async_session

        async with async_session() as session:
            try:
                if resume_action:
                    if not resolved_by:
                        raise WorkflowValidationError("resolved_by is required to resume workflow approval")
                    await resume_workflow_run(session, run_id, action=resume_action, resolved_by=resolved_by)
                else:
                    await execute_workflow_run(session, run_id)
            except Exception as exc:  # pragma: no cover - best-effort background recovery
                fail_result = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
                failed = fail_result.scalar_one_or_none()
                if failed and failed.status not in {"completed", "rejected"}:
                    failed.status = "failed"
                    failed.error_message = str(exc)
                    failed.finished_at = datetime.utcnow()
                    await session.commit()

    asyncio.create_task(_runner())


@router.get("/", response_model=list[WorkflowDefinitionOut])
async def list_workflows(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.agent_id == agent_id)
        .order_by(WorkflowDefinition.updated_at.desc(), WorkflowDefinition.created_at.desc())
    )
    return [_workflow_out(row) for row in result.scalars().all()]


@router.post("/", response_model=WorkflowDefinitionOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    agent_id: uuid.UUID,
    data: WorkflowDefinitionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent, _access = await check_agent_access(db, current_user, agent_id)
    try:
        validate_definition(data.definition)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = WorkflowDefinition(
        agent_id=agent_id,
        tenant_id=agent.tenant_id,
        created_by=current_user.id,
        name=data.name,
        description=data.description,
        status=data.status,
        version=1,
        definition=data.definition,
        canvas_layout=data.canvas_layout or {},
        input_schema=data.input_schema or {},
        output_schema=data.output_schema or {},
    )
    db.add(row)
    await db.flush()
    await db.commit()
    await db.refresh(row)
    return _workflow_out(row)


@router.get("/{workflow_id}", response_model=WorkflowDefinitionOut)
async def get_workflow(
    agent_id: uuid.UUID,
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id, WorkflowDefinition.agent_id == agent_id
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _workflow_out(row)


@router.patch("/{workflow_id}", response_model=WorkflowDefinitionOut)
async def update_workflow(
    agent_id: uuid.UUID,
    workflow_id: uuid.UUID,
    data: WorkflowDefinitionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id, WorkflowDefinition.agent_id == agent_id
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    updates = data.model_dump(exclude_unset=True)
    if "definition" in updates:
        try:
            validate_definition(updates["definition"])
        except WorkflowValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.version += 1

    for field, value in updates.items():
        setattr(row, field, value)

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return _workflow_out(row)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    agent_id: uuid.UUID,
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id, WorkflowDefinition.agent_id == agent_id
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(row)
    await db.commit()


@router.get("/{workflow_id}/runs", response_model=list[WorkflowRunOut])
async def list_workflow_runs(
    agent_id: uuid.UUID,
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow_id, WorkflowRun.agent_id == agent_id)
        .order_by(WorkflowRun.created_at.desc())
    )
    rows = result.scalars().all()
    return [_workflow_run_out(row) for row in rows]


@router.post("/{workflow_id}/runs", response_model=WorkflowRunOut, status_code=status.HTTP_201_CREATED)
async def create_workflow_run(
    agent_id: uuid.UUID,
    workflow_id: uuid.UUID,
    data: WorkflowRunCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    workflow_result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id, WorkflowDefinition.agent_id == agent_id
        )
    )
    workflow = workflow_result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        validate_definition(workflow.definition or {})
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run = WorkflowRun(
        workflow_id=workflow_id,
        agent_id=agent_id,
        started_by=current_user.id,
        trigger_type=data.trigger_type,
        status="pending",
        input_payload=data.input_payload or {},
        context_snapshot={},
        output_payload={},
        started_at=datetime.utcnow(),
    )
    db.add(run)
    await db.flush()
    run_id = run.id
    await db.commit()
    _start_workflow_background_run(run_id)

    fresh_result = await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
    fresh = fresh_result.scalar_one()
    return _workflow_run_out(fresh)


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunOut)
async def get_workflow_run(
    agent_id: uuid.UUID,
    workflow_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.agent_id == agent_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    node_result = await db.execute(
        select(WorkflowNodeRun)
        .where(WorkflowNodeRun.workflow_run_id == row.id)
        .order_by(WorkflowNodeRun.created_at.asc())
    )
    return _workflow_run_out(row, node_result.scalars().all())


@router.post("/{workflow_id}/runs/{run_id}/resolve-approval", response_model=WorkflowRunOut)
async def resolve_workflow_approval(
    agent_id: uuid.UUID,
    workflow_id: uuid.UUID,
    run_id: uuid.UUID,
    data: ApprovalAction,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.agent_id == agent_id,
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status != "waiting_human":
        raise HTTPException(status_code=400, detail="Workflow run is not waiting for approval")

    action = (data.action or "").strip().lower()
    if action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Action must be approve or reject")

    _start_workflow_background_run(run.id, resume_action=action, resolved_by=current_user.id)

    fresh_result = await db.execute(select(WorkflowRun).where(WorkflowRun.id == run.id))
    fresh = fresh_result.scalar_one()
    node_result = await db.execute(
        select(WorkflowNodeRun)
        .where(WorkflowNodeRun.workflow_run_id == fresh.id)
        .order_by(WorkflowNodeRun.created_at.asc())
    )
    return _workflow_run_out(fresh, node_result.scalars().all())
