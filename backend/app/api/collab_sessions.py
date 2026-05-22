"""Collaborative Sessions API — multi-agent group conversations.

Allows users to create group conversations with multiple agents,
send messages, and have agents respond to mentions.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.agent import Agent
from app.models.collab_session import CollabMessage, CollabParticipant, CollabSession
from app.models.user import User

router = APIRouter(prefix="/collab-sessions", tags=["collab-sessions"])


# ── Schemas ─────────────────────────────────────────


class SessionCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = ""
    agent_ids: list[uuid.UUID] = Field(..., min_length=1)
    settings: dict = Field(default_factory=dict)


class SessionOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    status: str
    settings: dict
    participant_count: int
    message_count: int
    created_at: datetime
    updated_at: datetime


class ParticipantOut(BaseModel):
    id: uuid.UUID
    participant_type: str
    user_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    display_name: str
    role: str
    is_active: bool
    joined_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(..., max_length=5000)
    mentioned_ids: list[uuid.UUID] = Field(default_factory=list)


class MessageOut(BaseModel):
    id: uuid.UUID
    sender_type: str
    sender_id: uuid.UUID | None
    sender_name: str
    content: str
    message_type: str
    mentioned_ids: list
    created_at: datetime


class AddParticipant(BaseModel):
    agent_id: uuid.UUID


# ── Session CRUD ────────────────────────────────────


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List collaborative sessions the user participates in."""
    stmt = (
        select(CollabSession)
        .join(CollabParticipant)
        .where(
            CollabParticipant.user_id == user.id,
            CollabParticipant.is_active.is_(True),
            CollabSession.status != "archived",
        )
        .order_by(desc(CollabSession.updated_at))
    )
    sessions = (await db.execute(stmt)).scalars().all()

    results = []
    for session in sessions:
        p_count = len([p for p in session.participants if p.is_active])
        m_count = len(session.messages)
        results.append(SessionOut(
            id=session.id,
            title=session.title,
            description=session.description,
            status=session.status,
            settings=session.settings,
            participant_count=p_count,
            message_count=m_count,
            created_at=session.created_at,
            updated_at=session.updated_at,
        ))
    return results


@router.post("", response_model=SessionOut)
async def create_session(
    body: SessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new collaborative session with multiple agents."""
    # Validate agents exist and user has access
    agents = []
    for agent_id in body.agent_ids:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(404, f"Agent {agent_id} not found")
        agents.append(agent)

    session = CollabSession(
        tenant_id=user.tenant_id,
        created_by=user.id,
        title=body.title,
        description=body.description,
        settings=body.settings,
    )
    db.add(session)
    await db.flush()

    # Add the user as owner
    db.add(CollabParticipant(
        session_id=session.id,
        participant_type="human",
        user_id=user.id,
        display_name=user.nickname or user.email,
        role="owner",
    ))

    # Add agents as participants
    for agent in agents:
        db.add(CollabParticipant(
            session_id=session.id,
            participant_type="agent",
            agent_id=agent.id,
            display_name=agent.name,
            role="member",
        ))

    # System message announcing session creation
    agent_names = ", ".join(a.name for a in agents)
    db.add(CollabMessage(
        session_id=session.id,
        sender_type="system",
        sender_name="System",
        content=f"Collaborative session created. Participants: {user.nickname or user.email}, {agent_names}",
        message_type="system_event",
    ))

    await db.flush()

    return SessionOut(
        id=session.id,
        title=session.title,
        description=session.description,
        status=session.status,
        settings=session.settings,
        participant_count=1 + len(agents),
        message_count=1,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get details of a collaborative session."""
    session = await _get_session_for_user(db, session_id, user.id)
    p_count = len([p for p in session.participants if p.is_active])
    m_count = len(session.messages)
    return SessionOut(
        id=session.id,
        title=session.title,
        description=session.description,
        status=session.status,
        settings=session.settings,
        participant_count=p_count,
        message_count=m_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("/{session_id}/participants", response_model=list[ParticipantOut])
async def list_participants(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List participants in a collaborative session."""
    session = await _get_session_for_user(db, session_id, user.id)
    return [
        ParticipantOut(
            id=p.id,
            participant_type=p.participant_type,
            user_id=p.user_id,
            agent_id=p.agent_id,
            display_name=p.display_name,
            role=p.role,
            is_active=p.is_active,
            joined_at=p.joined_at,
        )
        for p in session.participants
    ]


@router.post("/{session_id}/participants")
async def add_participant(
    session_id: uuid.UUID,
    body: AddParticipant,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an agent to a collaborative session."""
    session = await _get_session_for_user(db, session_id, user.id)

    # Check agent exists
    result = await db.execute(select(Agent).where(Agent.id == body.agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # Check not already a participant
    existing = [p for p in session.participants if p.agent_id == body.agent_id and p.is_active]
    if existing:
        raise HTTPException(400, "Agent is already a participant")

    db.add(CollabParticipant(
        session_id=session.id,
        participant_type="agent",
        agent_id=agent.id,
        display_name=agent.name,
        role="member",
    ))

    db.add(CollabMessage(
        session_id=session.id,
        sender_type="system",
        sender_name="System",
        content=f"{agent.name} joined the conversation.",
        message_type="system_event",
    ))
    await db.flush()
    return {"status": "ok"}


@router.delete("/{session_id}/participants/{agent_id}")
async def remove_participant(
    session_id: uuid.UUID,
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an agent from a collaborative session."""
    session = await _get_session_for_user(db, session_id, user.id)

    participant = next(
        (p for p in session.participants if p.agent_id == agent_id and p.is_active),
        None,
    )
    if not participant:
        raise HTTPException(404, "Participant not found")

    participant.is_active = False

    db.add(CollabMessage(
        session_id=session.id,
        sender_type="system",
        sender_name="System",
        content=f"{participant.display_name} left the conversation.",
        message_type="system_event",
    ))
    await db.flush()
    return {"status": "ok"}


# ── Messages ────────────────────────────────────────


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List messages in a collaborative session."""
    await _get_session_for_user(db, session_id, user.id)

    stmt = (
        select(CollabMessage)
        .where(CollabMessage.session_id == session_id)
        .order_by(desc(CollabMessage.created_at))
        .limit(limit)
        .offset(offset)
    )
    messages = (await db.execute(stmt)).scalars().all()
    messages.reverse()  # Return in chronological order

    return [
        MessageOut(
            id=m.id,
            sender_type=m.sender_type,
            sender_id=m.sender_id,
            sender_name=m.sender_name,
            content=m.content,
            message_type=m.message_type,
            mentioned_ids=m.mentioned_ids,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/{session_id}/messages", response_model=MessageOut)
async def send_message(
    session_id: uuid.UUID,
    body: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message in a collaborative session.

    If agents are @mentioned, they will be triggered to respond.
    """
    session = await _get_session_for_user(db, session_id, user.id)

    message = CollabMessage(
        session_id=session.id,
        sender_type="human",
        sender_id=user.id,
        sender_name=user.nickname or user.email,
        content=body.content,
        message_type="text",
        mentioned_ids=[str(mid) for mid in body.mentioned_ids],
    )
    db.add(message)
    await db.flush()

    # Trigger mentioned agents to respond (async, non-blocking)
    if body.mentioned_ids:
        await _trigger_agent_responses(db, session, message, body.mentioned_ids)
    elif session.settings.get("auto_respond"):
        # If auto_respond is enabled, trigger all agents
        agent_ids = [p.agent_id for p in session.participants if p.participant_type == "agent" and p.is_active and p.agent_id]
        if agent_ids:
            await _trigger_agent_responses(db, session, message, agent_ids)

    # Broadcast via WebSocket
    import asyncio
    asyncio.create_task(broadcast_collab_message(str(session_id), {
        "id": str(message.id),
        "sender_type": message.sender_type,
        "sender_id": str(message.sender_id) if message.sender_id else None,
        "sender_name": message.sender_name,
        "content": message.content,
        "message_type": message.message_type,
        "created_at": message.created_at,
    }))

    return MessageOut(
        id=message.id,
        sender_type=message.sender_type,
        sender_id=message.sender_id,
        sender_name=message.sender_name,
        content=message.content,
        message_type=message.message_type,
        mentioned_ids=message.mentioned_ids,
        created_at=message.created_at,
    )


# ── Helpers ─────────────────────────────────────────


async def _get_session_for_user(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> CollabSession:
    """Load a session and verify user is a participant."""
    result = await db.execute(
        select(CollabSession).where(CollabSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Session not found")

    is_participant = any(
        p.user_id == user_id and p.is_active for p in session.participants
    )
    if not is_participant:
        raise HTTPException(403, "Not a participant in this session")

    return session


async def _trigger_agent_responses(
    db: AsyncSession,
    session: CollabSession,
    message: CollabMessage,
    agent_ids: list[uuid.UUID],
) -> None:
    """Trigger agents to respond to a message in the collaborative session.

    Uses the agent's configured LLM to generate a response based on
    the conversation history in this collaborative session.
    """
    import asyncio
    from app.database import async_session
    from app.models.collab_session import CollabMessage as CM

    for agent_id in agent_ids:
        # Verify agent is a participant
        participant = next(
            (p for p in session.participants if p.agent_id == agent_id and p.is_active),
            None,
        )
        if not participant:
            continue

        # Load agent
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            continue

        # Dispatch async so we don't block the response
        asyncio.create_task(_generate_agent_reply(session.id, agent.id, agent.name, message.content))
        logger.info(
            f"[Collab] Agent {agent.name} triggered in session {session.id} "
            f"by message from {message.sender_name}"
        )


async def _generate_agent_reply(session_id: uuid.UUID, agent_id: uuid.UUID, agent_name: str, user_message: str) -> None:
    """Background task: generate an agent reply in a collaborative session."""
    from app.database import async_session
    from app.models.collab_session import CollabMessage as CM
    from app.services.llm import call_llm_with_failover
    from app.models.agent import Agent
    from app.models.llm import LLMModel
    from sqlalchemy import select, desc

    try:
        async with async_session() as db:
            # Load agent and model
            agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
            agent = agent_result.scalar_one_or_none()
            if not agent or not agent.primary_model_id:
                return

            model_result = await db.execute(select(LLMModel).where(LLMModel.id == agent.primary_model_id))
            llm_model = model_result.scalar_one_or_none()
            if not llm_model or not llm_model.enabled:
                return

            # Build conversation context from recent messages
            msgs_result = await db.execute(
                select(CM)
                .where(CM.session_id == session_id)
                .order_by(desc(CM.created_at))
                .limit(20)
            )
            recent_msgs = list(reversed(msgs_result.scalars().all()))

            # Build LLM messages
            system_prompt = (
                f"You are {agent_name}, participating in a group collaboration session. "
                f"Multiple agents and humans are in this conversation. "
                f"Respond helpfully and concisely to the latest message. "
                f"Your role: {agent.role or 'assistant'}. "
                f"Description: {agent.description or ''}"
            )

            llm_messages = [{"role": "system", "content": system_prompt}]
            for msg in recent_msgs:
                if msg.sender_type == "system":
                    continue
                role = "assistant" if msg.sender_type == "agent" and str(msg.sender_id) == str(agent_id) else "user"
                prefix = f"[{msg.sender_name}]: " if role == "user" else ""
                llm_messages.append({"role": role, "content": f"{prefix}{msg.content}"})

            # Call LLM
            response = await call_llm_with_failover(
                provider=llm_model.provider,
                api_key=llm_model.api_key,
                model=llm_model.model,
                messages=llm_messages,
                base_url=llm_model.base_url,
            )

            reply_content = response.get("content", "").strip()
            if not reply_content:
                return

            # Save reply as a collab message
            reply = CM(
                session_id=session_id,
                sender_type="agent",
                sender_id=agent_id,
                sender_name=agent_name,
                content=reply_content,
                message_type="text",
            )
            db.add(reply)
            await db.commit()
            logger.info(f"[Collab] Agent {agent_name} replied in session {session_id}")

    except Exception as exc:
        logger.warning(f"[Collab] Agent {agent_name} failed to reply: {exc}")


# ── WebSocket for real-time collab messages ─────────

from fastapi import WebSocket, WebSocketDisconnect

# In-memory connection registry (per session)
_ws_connections: dict[str, list[WebSocket]] = {}


@router.websocket("/{session_id}/ws")
async def collab_ws(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time collaborative session messages.

    Clients connect here instead of polling. New messages are broadcast
    to all connected participants.
    """
    await websocket.accept()

    # Register connection
    if session_id not in _ws_connections:
        _ws_connections[session_id] = []
    _ws_connections[session_id].append(websocket)

    try:
        while True:
            # Keep connection alive; messages are pushed via broadcast_collab_message
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_connections[session_id].remove(websocket)
        if not _ws_connections[session_id]:
            del _ws_connections[session_id]


async def broadcast_collab_message(session_id: str, message_data: dict) -> None:
    """Broadcast a new message to all WebSocket connections for a session."""
    import json
    connections = _ws_connections.get(session_id, [])
    dead: list[WebSocket] = []
    payload = json.dumps(message_data, default=str)
    for ws in connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connections.remove(ws)
