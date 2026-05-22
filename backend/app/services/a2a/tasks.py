"""A2A Task Runtime — handles cross-instance task delegation and callbacks."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.a2a import A2AEventLog, A2ATask, RemoteAgentCard, RemoteInstance


async def create_task(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    source_agent_id: uuid.UUID | None,
    target_card_id: uuid.UUID,
    request_payload: dict,
    callback_url: str | None = None,
) -> A2ATask:
    """Create and submit a task to a remote agent."""
    # Load target card and instance
    card_result = await db.execute(
        select(RemoteAgentCard).where(RemoteAgentCard.id == target_card_id)
    )
    card = card_result.scalar_one_or_none()
    if not card:
        raise ValueError(f"Remote agent card {target_card_id} not found")

    instance_result = await db.execute(
        select(RemoteInstance).where(RemoteInstance.id == card.remote_instance_id)
    )
    instance = instance_result.scalar_one_or_none()
    if not instance or instance.status != "active":
        raise ValueError("Remote instance is not available")

    # Generate callback token
    callback_token = secrets.token_urlsafe(32)

    task = A2ATask(
        tenant_id=tenant_id,
        source_agent_id=source_agent_id,
        direction="outbound",
        target_instance_id=instance.id,
        target_agent_ref=card.remote_agent_id,
        request_payload=request_payload,
        status="pending",
        callback_url=callback_url,
        callback_token=callback_token,
    )
    db.add(task)
    await db.flush()

    # Submit to remote
    try:
        await _submit_to_remote(instance, card, task)
        task.status = "submitted"
    except Exception as exc:
        task.status = "failed"
        task.error_message = str(exc)
        logger.warning(f"[A2A] Task submission failed: {exc}")

    db.add(A2AEventLog(
        tenant_id=tenant_id,
        task_id=task.id,
        instance_id=instance.id,
        event_type="task_created" if task.status == "submitted" else "task_failed",
        direction="outbound",
        payload={"target_agent": card.remote_agent_id, "status": task.status},
    ))
    await db.flush()
    return task


async def get_task_status(db: AsyncSession, task_id: uuid.UUID) -> A2ATask | None:
    """Get the current status of an A2A task."""
    result = await db.execute(select(A2ATask).where(A2ATask.id == task_id))
    task = result.scalar_one_or_none()
    if not task or task.direction != "outbound":
        return task

    # If task is still in progress, poll remote for status
    if task.status in ("submitted", "in_progress") and task.target_instance_id:
        instance_result = await db.execute(
            select(RemoteInstance).where(RemoteInstance.id == task.target_instance_id)
        )
        instance = instance_result.scalar_one_or_none()
        if instance and task.external_task_id:
            try:
                updated_status = await _poll_remote_status(instance, task.external_task_id)
                if updated_status and updated_status != task.status:
                    task.status = updated_status
                    if updated_status in ("completed", "failed"):
                        task.finished_at = datetime.now(timezone.utc)
                    await db.flush()
            except Exception as exc:
                logger.debug(f"[A2A] Status poll failed for task {task_id}: {exc}")

    return task


async def handle_callback(
    db: AsyncSession,
    callback_token: str,
    payload: dict,
) -> A2ATask | None:
    """Process an inbound callback from a remote instance."""
    result = await db.execute(
        select(A2ATask).where(A2ATask.callback_token == callback_token)
    )
    task = result.scalar_one_or_none()
    if not task:
        logger.warning(f"[A2A] Callback received for unknown token")
        return None

    status = payload.get("status", "completed")
    task.status = status
    task.response_payload = payload.get("result", {})
    if status in ("completed", "failed"):
        task.finished_at = datetime.now(timezone.utc)
    if status == "failed":
        task.error_message = payload.get("error", "Remote execution failed")

    db.add(A2AEventLog(
        tenant_id=task.tenant_id,
        task_id=task.id,
        instance_id=task.target_instance_id,
        event_type="callback_received",
        direction="inbound",
        payload=payload,
    ))
    await db.flush()

    logger.info(f"[A2A] Callback processed for task {task.id}: status={status}")
    return task


async def cancel_task(db: AsyncSession, task_id: uuid.UUID) -> A2ATask | None:
    """Cancel an outbound A2A task."""
    result = await db.execute(select(A2ATask).where(A2ATask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        return None
    if task.status in ("completed", "failed", "cancelled"):
        return task

    # Try to cancel on remote
    if task.target_instance_id and task.external_task_id:
        instance_result = await db.execute(
            select(RemoteInstance).where(RemoteInstance.id == task.target_instance_id)
        )
        instance = instance_result.scalar_one_or_none()
        if instance:
            try:
                await _cancel_on_remote(instance, task.external_task_id)
            except Exception as exc:
                logger.debug(f"[A2A] Remote cancel failed: {exc}")

    task.status = "cancelled"
    task.finished_at = datetime.now(timezone.utc)

    db.add(A2AEventLog(
        tenant_id=task.tenant_id,
        task_id=task.id,
        instance_id=task.target_instance_id,
        event_type="task_cancelled",
        direction="outbound",
        payload={},
    ))
    await db.flush()
    return task


# ── Internal helpers ──────────────────────────────────────────────


async def _submit_to_remote(
    instance: RemoteInstance, card: RemoteAgentCard, task: A2ATask
) -> None:
    """Submit a task to the remote instance via REST."""
    url = f"{instance.base_url}/api/a2a/tasks/receive"
    headers = _build_auth_headers(instance)
    body = {
        "task_id": str(task.id),
        "target_agent_id": card.remote_agent_id,
        "payload": task.request_payload,
        "callback_url": task.callback_url,
        "callback_token": task.callback_token,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        task.external_task_id = data.get("external_task_id", "")


async def _poll_remote_status(instance: RemoteInstance, external_task_id: str) -> str | None:
    """Poll remote instance for task status."""
    url = f"{instance.base_url}/api/a2a/tasks/{external_task_id}/status"
    headers = _build_auth_headers(instance)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.json().get("status")
    return None


async def _cancel_on_remote(instance: RemoteInstance, external_task_id: str) -> None:
    """Request cancellation on the remote instance."""
    url = f"{instance.base_url}/api/a2a/tasks/{external_task_id}/cancel"
    headers = _build_auth_headers(instance)

    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, headers=headers)


def _build_auth_headers(instance: RemoteInstance) -> dict[str, str]:
    """Build authentication headers for outbound requests."""
    from app.config import get_settings
    from app.core.security import decrypt_data

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if instance.auth_type == "api_key" and instance.auth_credential:
        try:
            settings = get_settings()
            api_key = decrypt_data(instance.auth_credential, settings.SECRET_KEY)
        except Exception:
            api_key = instance.auth_credential
        headers["Authorization"] = f"Bearer {api_key}"
    return headers
