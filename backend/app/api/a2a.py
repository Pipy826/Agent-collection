"""A2A (Agent-to-Agent) cross-instance collaboration API.

Provides endpoints for:
- Remote instance management (register, sync, list)
- Remote agent discovery (search by skills/labels)
- Cross-instance task delegation (create, status, cancel, callback)
- Local manifest exposure (for other instances to discover our agents)
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.a2a import A2AEventLog, A2ATask, RemoteAgentCard, RemoteInstance
from app.models.agent import Agent, AgentPermission
from app.models.user import User
from app.services.a2a.registry import register_instance, search_remote_agents, sync_instance
from app.services.a2a.tasks import cancel_task, create_task, handle_callback
from app.core.security import encrypt_data, decrypt_data
from app.config import get_settings

router = APIRouter(prefix="/a2a", tags=["a2a"])


# ── Schemas ─────────────────────────────────────────


class InstanceCreate(BaseModel):
    name: str = Field(..., max_length=200)
    base_url: str = Field(..., max_length=500)
    auth_type: str = Field(default="api_key", max_length=32)
    auth_credential: str | None = None
    metadata_json: dict = Field(default_factory=dict)


class InstanceOut(BaseModel):
    id: uuid.UUID
    name: str
    base_url: str
    protocol_version: str
    status: str
    auth_type: str
    is_enabled: bool
    last_seen: datetime | None
    last_sync_at: datetime | None
    agent_count: int = 0
    created_at: datetime


class InstanceUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    auth_type: str | None = None
    auth_credential: str | None = None
    is_enabled: bool | None = None


class AgentCardOut(BaseModel):
    id: uuid.UUID
    remote_instance_id: uuid.UUID
    instance_name: str = ""
    remote_agent_id: str
    name: str
    description: str
    skills: list
    labels: list
    availability_status: str
    supported_task_types: list
    last_synced_at: datetime | None


class AgentSearchQuery(BaseModel):
    skills: list[str] | None = None
    labels: list[str] | None = None
    query: str | None = None
    limit: int = Field(default=20, le=100)


class TaskCreate(BaseModel):
    target_card_id: uuid.UUID
    source_agent_id: uuid.UUID | None = None
    request_payload: dict = Field(default_factory=dict)
    callback_url: str | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    direction: str
    target_agent_ref: str | None
    status: str
    request_payload: dict
    response_payload: dict
    error_message: str | None
    retry_count: int
    created_at: datetime
    finished_at: datetime | None


class CallbackPayload(BaseModel):
    status: str = "completed"
    result: dict = Field(default_factory=dict)
    error: str | None = None


class EventLogOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    instance_id: uuid.UUID | None
    event_type: str
    direction: str
    payload: dict
    created_at: datetime


class ManifestAgentOut(BaseModel):
    id: str
    name: str
    description: str
    skills: list
    labels: list
    capabilities: dict
    status: str
    task_types: list


class ManifestOut(BaseModel):
    instance_name: str
    protocol_version: str = "0.3.0"
    agents: list[ManifestAgentOut]


# ── Instance Management ─────────────────────────────


@router.get("/instances", response_model=list[InstanceOut])
async def list_instances(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all registered remote instances."""
    stmt = select(RemoteInstance).where(RemoteInstance.tenant_id == user.tenant_id).order_by(desc(RemoteInstance.created_at))
    instances = (await db.execute(stmt)).scalars().all()

    # Get agent counts
    count_stmt = (
        select(RemoteAgentCard.remote_instance_id, func.count(RemoteAgentCard.id))
        .group_by(RemoteAgentCard.remote_instance_id)
    )
    counts = {row[0]: row[1] for row in (await db.execute(count_stmt)).all()}

    return [
        InstanceOut(
            id=inst.id,
            name=inst.name,
            base_url=inst.base_url,
            protocol_version=inst.protocol_version,
            status=inst.status,
            auth_type=inst.auth_type,
            is_enabled=inst.is_enabled,
            last_seen=inst.last_seen,
            last_sync_at=inst.last_sync_at,
            agent_count=counts.get(inst.id, 0),
            created_at=inst.created_at,
        )
        for inst in instances
    ]


@router.post("/instances", response_model=InstanceOut)
async def create_instance(
    body: InstanceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new remote instance."""
    settings = get_settings()
    # Encrypt the auth credential before storing
    encrypted_cred = None
    if body.auth_credential:
        encrypted_cred = encrypt_data(body.auth_credential, settings.SECRET_KEY)

    instance = await register_instance(
        db,
        tenant_id=user.tenant_id,
        name=body.name,
        base_url=body.base_url,
        auth_type=body.auth_type,
        auth_credential=encrypted_cred,
        metadata_json=body.metadata_json,
    )
    return InstanceOut(
        id=instance.id,
        name=instance.name,
        base_url=instance.base_url,
        protocol_version=instance.protocol_version,
        status=instance.status,
        auth_type=instance.auth_type,
        is_enabled=instance.is_enabled,
        last_seen=instance.last_seen,
        last_sync_at=instance.last_sync_at,
        agent_count=0,
        created_at=instance.created_at,
    )


@router.patch("/instances/{instance_id}", response_model=InstanceOut)
async def update_instance(
    instance_id: uuid.UUID,
    body: InstanceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a remote instance configuration."""
    result = await db.execute(
        select(RemoteInstance).where(
            RemoteInstance.id == instance_id,
            RemoteInstance.tenant_id == user.tenant_id,
        )
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(404, "Instance not found")

    if body.name is not None:
        instance.name = body.name
    if body.base_url is not None:
        instance.base_url = body.base_url.rstrip("/")
    if body.auth_type is not None:
        instance.auth_type = body.auth_type
    if body.auth_credential is not None:
        instance.auth_credential = body.auth_credential
    if body.is_enabled is not None:
        instance.is_enabled = body.is_enabled

    await db.flush()
    return InstanceOut(
        id=instance.id,
        name=instance.name,
        base_url=instance.base_url,
        protocol_version=instance.protocol_version,
        status=instance.status,
        auth_type=instance.auth_type,
        is_enabled=instance.is_enabled,
        last_seen=instance.last_seen,
        last_sync_at=instance.last_sync_at,
        agent_count=0,
        created_at=instance.created_at,
    )


@router.post("/instances/{instance_id}/sync")
async def sync_instance_endpoint(
    instance_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a sync of agent cards from a remote instance."""
    result = await db.execute(
        select(RemoteInstance).where(
            RemoteInstance.id == instance_id,
            RemoteInstance.tenant_id == user.tenant_id,
        )
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(404, "Instance not found")

    try:
        updated = await sync_instance(db, instance_id)
        return {"status": "ok", "agents_synced": len(updated.agent_cards)}
    except Exception as exc:
        raise HTTPException(502, f"Sync failed: {exc}")


# ── Agent Discovery ─────────────────────────────────


@router.post("/agents/search", response_model=list[AgentCardOut])
async def search_agents(
    body: AgentSearchQuery,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search for remote agents by skills, labels, or free text."""
    cards = await search_remote_agents(
        db,
        tenant_id=user.tenant_id,
        skills=body.skills,
        labels=body.labels,
        query=body.query,
        limit=body.limit,
    )

    # Enrich with instance names
    instance_ids = {c.remote_instance_id for c in cards}
    instances = {}
    if instance_ids:
        inst_result = await db.execute(
            select(RemoteInstance).where(RemoteInstance.id.in_(instance_ids))
        )
        instances = {i.id: i.name for i in inst_result.scalars().all()}

    return [
        AgentCardOut(
            id=card.id,
            remote_instance_id=card.remote_instance_id,
            instance_name=instances.get(card.remote_instance_id, ""),
            remote_agent_id=card.remote_agent_id,
            name=card.name,
            description=card.description,
            skills=card.skills,
            labels=card.labels,
            availability_status=card.availability_status,
            supported_task_types=card.supported_task_types,
            last_synced_at=card.last_synced_at,
        )
        for card in cards
    ]


@router.get("/agents/{card_id}", response_model=AgentCardOut)
async def get_agent_card(
    card_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific remote agent card."""
    result = await db.execute(select(RemoteAgentCard).where(RemoteAgentCard.id == card_id))
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(404, "Agent card not found")

    inst_result = await db.execute(
        select(RemoteInstance).where(RemoteInstance.id == card.remote_instance_id)
    )
    instance = inst_result.scalar_one_or_none()

    return AgentCardOut(
        id=card.id,
        remote_instance_id=card.remote_instance_id,
        instance_name=instance.name if instance else "",
        remote_agent_id=card.remote_agent_id,
        name=card.name,
        description=card.description,
        skills=card.skills,
        labels=card.labels,
        availability_status=card.availability_status,
        supported_task_types=card.supported_task_types,
        last_synced_at=card.last_synced_at,
    )


# ── Task Management ─────────────────────────────────


@router.post("/tasks", response_model=TaskOut)
async def create_a2a_task(
    body: TaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create and submit a task to a remote agent."""
    try:
        task = await create_task(
            db,
            tenant_id=user.tenant_id,
            source_agent_id=body.source_agent_id,
            target_card_id=body.target_card_id,
            request_payload=body.request_payload,
            callback_url=body.callback_url,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return _task_to_out(task)


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_a2a_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the status of an A2A task."""
    from app.services.a2a.tasks import get_task_status
    task = await get_task_status(db, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return _task_to_out(task)


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_a2a_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an A2A task."""
    task = await cancel_task(db, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return _task_to_out(task)


@router.post("/callback/{token}")
async def receive_callback(
    token: str,
    body: CallbackPayload,
    db: AsyncSession = Depends(get_db),
):
    """Receive a callback from a remote instance (no auth required — token is the secret)."""
    task = await handle_callback(db, token, body.model_dump())
    if not task:
        raise HTTPException(404, "Invalid callback token")
    return {"status": "ok", "task_status": task.status}


# ── Manifest (exposed to other instances) ───────────


@router.get("/manifest", response_model=ManifestOut)
async def get_manifest(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Expose this instance's agent capabilities for remote discovery.

    This endpoint is called by other instances during sync.
    Authentication is handled via the Authorization header (API key).
    """
    from app.config import get_settings
    settings = get_settings()

    # Get all agents that are marked as discoverable (public scope)
    stmt = (
        select(Agent)
        .join(AgentPermission)
        .where(
            AgentPermission.scope_type == "org",
            Agent.status == "active",
        )
        .distinct()
    )
    agents = (await db.execute(stmt)).scalars().all()

    manifest_agents = []
    for agent in agents:
        manifest_agents.append(ManifestAgentOut(
            id=str(agent.id),
            name=agent.name,
            description=agent.description or "",
            skills=[s for s in (agent.skills_summary or "").split(",") if s.strip()],
            labels=[agent.role] if agent.role else [],
            capabilities={"tools": True, "chat": True},
            status="available" if agent.status == "active" else "offline",
            task_types=["chat", "execute"],
        ))

    return ManifestOut(
        instance_name=settings.APP_NAME,
        protocol_version="0.3.0",
        agents=manifest_agents,
    )


# ── Inbound Task Reception ──────────────────────────


class InboundTaskPayload(BaseModel):
    task_id: str
    target_agent_id: str
    payload: dict = Field(default_factory=dict)
    callback_url: str | None = None
    callback_token: str | None = None


@router.post("/tasks/receive")
async def receive_task(
    body: InboundTaskPayload,
    db: AsyncSession = Depends(get_db),
):
    """Receive a task from a remote instance (inbound)."""
    # Find the target agent locally
    try:
        agent_uuid = uuid.UUID(body.target_agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid target_agent_id")

    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Target agent not found on this instance")

    # Create inbound task record
    task = A2ATask(
        tenant_id=agent.tenant_id,
        source_agent_id=None,
        direction="inbound",
        target_agent_ref=body.target_agent_id,
        request_payload=body.payload,
        status="in_progress",
        callback_url=body.callback_url,
        callback_token=body.callback_token,
        external_task_id=body.task_id,
    )
    db.add(task)

    db.add(A2AEventLog(
        tenant_id=agent.tenant_id,
        task_id=task.id,
        event_type="task_received",
        direction="inbound",
        payload={"source_task_id": body.task_id, "target_agent": body.target_agent_id},
    ))
    await db.flush()

    # TODO: Actually dispatch to the agent's execution pipeline
    # For Phase 1, we acknowledge receipt and the task will be processed asynchronously

    return {"status": "accepted", "external_task_id": str(task.id)}


# ── Audit Log ───────────────────────────────────────


@router.get("/audit", response_model=list[EventLogOut])
async def list_audit_logs(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List A2A audit events."""
    stmt = (
        select(A2AEventLog)
        .where(A2AEventLog.tenant_id == user.tenant_id)
        .order_by(desc(A2AEventLog.created_at))
        .limit(limit)
        .offset(offset)
    )
    logs = (await db.execute(stmt)).scalars().all()
    return [
        EventLogOut(
            id=log.id,
            task_id=log.task_id,
            instance_id=log.instance_id,
            event_type=log.event_type,
            direction=log.direction,
            payload=log.payload,
            created_at=log.created_at,
        )
        for log in logs
    ]


# ── Helpers ─────────────────────────────────────────


def _task_to_out(task: A2ATask) -> TaskOut:
    return TaskOut(
        id=task.id,
        direction=task.direction,
        target_agent_ref=task.target_agent_ref,
        status=task.status,
        request_payload=task.request_payload,
        response_payload=task.response_payload,
        error_message=task.error_message,
        retry_count=task.retry_count,
        created_at=task.created_at,
        finished_at=task.finished_at,
    )
