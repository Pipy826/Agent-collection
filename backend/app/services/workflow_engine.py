"""Lightweight workflow execution runtime."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.task import Task, TaskLog
from app.models.workflow import WorkflowDefinition, WorkflowNodeRun, WorkflowRun


class WorkflowValidationError(ValueError):
    """Raised when a workflow definition is structurally invalid."""


_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def validate_definition(definition: dict) -> None:
    nodes = definition.get("nodes") or []
    edges = definition.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        raise WorkflowValidationError("Workflow must contain at least one node")
    if not isinstance(edges, list):
        raise WorkflowValidationError("Workflow edges must be a list")

    keys = set()
    start_count = 0
    for node in nodes:
        key = str(node.get("key") or "").strip()
        if not key:
            raise WorkflowValidationError("Each node must have a key")
        if key in keys:
            raise WorkflowValidationError(f"Duplicate node key: {key}")
        keys.add(key)
        if (node.get("type") or "") == "start":
            start_count += 1
    if start_count != 1:
        raise WorkflowValidationError("Workflow must contain exactly one start node")

    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            raise WorkflowValidationError("Each edge must define source and target")
        if source not in keys or target not in keys:
            raise WorkflowValidationError("Edge references an unknown node")


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        key = part.strip()
        if not key:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _render_string(value: str, context: dict[str, Any]) -> Any:
    matches = list(_TEMPLATE_PATTERN.finditer(value))
    if not matches:
        return value

    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        resolved = _resolve_path(context, matches[0].group(1))
        return resolved if resolved is not None else value

    def _replacement(match: re.Match[str]) -> str:
        resolved = _resolve_path(context, match.group(1))
        if resolved is None:
            return ""
        if isinstance(resolved, (dict, list)):
            return str(resolved)
        return str(resolved)

    return _TEMPLATE_PATTERN.sub(_replacement, value)


def _render_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_string(value, context)
    if isinstance(value, list):
        return [_render_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render_value(item, context) for key, item in value.items()}
    return value


def _build_render_context(run: WorkflowRun, node_outputs: dict[str, Any], current_node: dict[str, Any]) -> dict[str, Any]:
    return {
        "input": run.input_payload or {},
        "workflow": {
            "id": str(run.workflow_id),
            "run_id": str(run.id),
            "agent_id": str(run.agent_id),
            "trigger_type": run.trigger_type,
            "status": run.status,
        },
        "node": current_node,
        "node_outputs": node_outputs,
    }


def _update_run_context(run: WorkflowRun, *, node_key: str, node_output: dict[str, Any] | None = None, visited: bool = False) -> None:
    snapshot = dict(run.context_snapshot or {})
    node_outputs = dict(snapshot.get("node_outputs") or {})
    visited_nodes = list(snapshot.get("visited") or [])
    if node_output is not None:
        node_outputs[node_key] = node_output
    if visited and node_key not in visited_nodes:
        visited_nodes.append(node_key)
    snapshot["input"] = run.input_payload or {}
    snapshot["node_outputs"] = node_outputs
    snapshot["visited"] = visited_nodes
    run.context_snapshot = snapshot


def _finalize_run(
    run: WorkflowRun,
    *,
    status: str,
    error_message: str | None = None,
    current_node_key: str | None = None,
) -> None:
    run.status = status
    run.error_message = error_message
    run.current_node_key = current_node_key
    if status in {"completed", "failed", "rejected"}:
        run.finished_at = datetime.now(timezone.utc)
    run.output_payload = {
        "visited": (run.context_snapshot or {}).get("visited", []),
        "node_outputs": (run.context_snapshot or {}).get("node_outputs", {}),
    }


async def _load_agent(db: AsyncSession, agent_id: uuid.UUID) -> Agent | None:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def _execute_tool_node(
    db: AsyncSession,
    run: WorkflowRun,
    workflow: WorkflowDefinition,
    node: dict[str, Any],
    node_outputs: dict[str, Any],
) -> dict[str, Any]:
    from app.services.agent_tools import execute_tool

    raw_config = node.get("config") or {}
    render_context = _build_render_context(run, node_outputs, node)
    config = _render_value(raw_config, render_context) or {}
    tool_name = str(config.get("toolName") or config.get("tool_name") or "").strip()
    if not tool_name:
        raise WorkflowValidationError(f"Tool node {node['key']} is missing toolName")

    target_agent_id = config.get("agentId") or config.get("agent_id") or workflow.agent_id
    try:
        target_agent_uuid = uuid.UUID(str(target_agent_id))
    except Exception as exc:
        raise WorkflowValidationError(f"Tool node {node['key']} has invalid agentId") from exc

    args = config.get("arguments") or config.get("args") or {}
    if not isinstance(args, dict):
        raise WorkflowValidationError(f"Tool node {node['key']} arguments must be an object")

    result = await execute_tool(
        tool_name=tool_name,
        arguments=args,
        agent_id=target_agent_uuid,
        user_id=run.started_by,
        session_id=str(run.id),
    )
    return {
        "message": f"Tool {tool_name} completed",
        "tool_name": tool_name,
        "arguments": args,
        "result": result,
        "agent_id": str(target_agent_uuid),
    }


async def _execute_agent_prompt(
    db: AsyncSession,
    agent_id: uuid.UUID,
    prompt: str,
    *,
    max_rounds: int = 24,
    system_addendum: str = "",
    session_id: str = "",
) -> str:
    from app.services.agent_context import build_agent_context
    from app.services.llm import call_agent_llm_with_tools

    agent = await _load_agent(db, agent_id)
    if not agent:
        raise WorkflowValidationError(f"Agent {agent_id} not found")

    static_prompt, dynamic_prompt = await build_agent_context(agent_id, agent.name, agent.role_description or "")
    system_prompt = f"{static_prompt}\n\n{dynamic_prompt}"
    if system_addendum.strip():
        system_prompt = f"{system_prompt}\n\n{system_addendum.strip()}"

    return await call_agent_llm_with_tools(
        db=db,
        agent_id=agent_id,
        system_prompt=system_prompt,
        user_prompt=prompt,
        max_rounds=max_rounds,
        session_id=session_id,
    )


async def _execute_agent_node(
    db: AsyncSession,
    run: WorkflowRun,
    workflow: WorkflowDefinition,
    node: dict[str, Any],
    node_outputs: dict[str, Any],
) -> dict[str, Any]:
    raw_config = node.get("config") or {}
    render_context = _build_render_context(run, node_outputs, node)
    config = _render_value(raw_config, render_context) or {}

    target_agent_id = config.get("agentId") or config.get("agent_id") or workflow.agent_id
    try:
        target_agent_uuid = uuid.UUID(str(target_agent_id))
    except Exception as exc:
        raise WorkflowValidationError(f"Agent node {node['key']} has invalid agentId") from exc

    prompt = str(config.get("prompt") or config.get("message") or "").strip()
    if not prompt:
        raise WorkflowValidationError(f"Agent node {node['key']} is missing prompt")

    max_rounds = int(config.get("maxRounds") or config.get("max_rounds") or 24)
    system_addendum = str(config.get("systemPrompt") or config.get("system_prompt") or "").strip()
    reply = await _execute_agent_prompt(
        db,
        target_agent_uuid,
        prompt,
        max_rounds=max_rounds,
        system_addendum=system_addendum,
        session_id=str(run.id),
    )
    return {
        "message": "Agent node completed",
        "agent_id": str(target_agent_uuid),
        "prompt": prompt,
        "reply": reply,
    }


async def _execute_task_node(
    db: AsyncSession,
    run: WorkflowRun,
    workflow: WorkflowDefinition,
    node: dict[str, Any],
    node_outputs: dict[str, Any],
) -> dict[str, Any]:
    from app.services.task_executor import execute_task

    raw_config = node.get("config") or {}
    render_context = _build_render_context(run, node_outputs, node)
    config = _render_value(raw_config, render_context) or {}

    target_agent_id = config.get("agentId") or config.get("agent_id") or workflow.agent_id
    try:
        target_agent_uuid = uuid.UUID(str(target_agent_id))
    except Exception as exc:
        raise WorkflowValidationError(f"Task node {node['key']} has invalid agentId") from exc

    title = str(config.get("title") or node.get("title") or "").strip()
    if not title:
        raise WorkflowValidationError(f"Task node {node['key']} is missing title")
    description = str(config.get("description") or config.get("prompt") or "").strip() or None
    priority = str(config.get("priority") or "medium")
    task_type = str(config.get("taskType") or config.get("task_type") or "todo")
    wait_for_completion = bool(config.get("waitForCompletion", config.get("wait_for_completion", True)))

    task = Task(
        agent_id=target_agent_uuid,
        title=title,
        description=description,
        type=task_type,
        status="pending",
        priority=priority,
        assignee="self",
        created_by=run.started_by,
    )
    db.add(task)
    await db.flush()
    db.add(TaskLog(task_id=task.id, content=f"Workflow run {run.id} created this task from node {node['key']}."))
    await db.commit()

    if not wait_for_completion:
        asyncio.create_task(execute_task(task.id, target_agent_uuid))
        return {
            "message": "Task created and scheduled",
            "task_id": str(task.id),
            "agent_id": str(target_agent_uuid),
            "status": "pending",
        }

    await execute_task(task.id, target_agent_uuid)
    await db.refresh(task)
    log_result = await db.execute(
        select(TaskLog).where(TaskLog.task_id == task.id).order_by(TaskLog.created_at.asc())
    )
    logs = [
        {
            "id": str(item.id),
            "content": item.content,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in log_result.scalars().all()
    ]
    return {
        "message": "Task executed",
        "task_id": str(task.id),
        "agent_id": str(target_agent_uuid),
        "status": task.status,
        "logs": logs,
    }


def _select_condition_target(
    node: dict[str, Any],
    outgoing_edges: list[dict[str, Any]],
    node_outputs: dict[str, Any],
    run: WorkflowRun,
) -> list[str]:
    config = node.get("config") or {}
    render_context = _build_render_context(run, node_outputs, node)
    config = _render_value(config, render_context) or {}

    selected = config.get("defaultTarget")
    if selected:
        return [str(selected)]

    equals = config.get("equals")
    if isinstance(equals, dict):
        left = equals.get("left")
        right = equals.get("right")
        true_target = equals.get("trueTarget")
        false_target = equals.get("falseTarget")
        if left == right and true_target:
            return [str(true_target)]
        if left != right and false_target:
            return [str(false_target)]

    if outgoing_edges:
        return [str(outgoing_edges[0]["target"])]
    return []


async def _execute_node(
    db: AsyncSession,
    run: WorkflowRun,
    workflow: WorkflowDefinition,
    node: dict[str, Any],
    outgoing_edges: list[dict[str, Any]],
    node_outputs: dict[str, Any],
) -> tuple[dict[str, Any], list[str], str]:
    node_type = str(node.get("type") or "task")

    if node_type == "approval":
        output = {
            "message": "Manual approval required",
            "node_key": node["key"],
        }
        return output, [], "waiting_human"

    if node_type == "condition":
        next_keys = _select_condition_target(node, outgoing_edges, node_outputs, run)
        output = {
            "message": "Condition evaluated",
            "node_key": node["key"],
            "next": next_keys,
        }
        return output, next_keys, "completed"

    if node_type == "parallel":
        next_keys = [str(edge["target"]) for edge in outgoing_edges]
        output = {
            "message": "Parallel branches scheduled",
            "node_key": node["key"],
            "next": next_keys,
        }
        return output, next_keys, "completed"

    if node_type == "tool":
        output = await _execute_tool_node(db, run, workflow, node, node_outputs)
    elif node_type == "agent":
        output = await _execute_agent_node(db, run, workflow, node, node_outputs)
    elif node_type == "task":
        output = await _execute_task_node(db, run, workflow, node, node_outputs)
    else:
        output = {
            "message": f"{node_type} node completed",
            "node_key": node["key"],
        }

    next_keys = [str(edge["target"]) for edge in outgoing_edges]
    output["node_key"] = node["key"]
    output["next"] = next_keys
    return output, next_keys, "completed"


async def _load_workflow_state(
    db: AsyncSession,
    run_id: uuid.UUID,
) -> tuple[WorkflowRun, WorkflowDefinition, list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    run_result = await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
    run = run_result.scalar_one_or_none()
    if not run:
        raise WorkflowValidationError("Workflow run not found")

    workflow_result = await db.execute(select(WorkflowDefinition).where(WorkflowDefinition.id == run.workflow_id))
    workflow = workflow_result.scalar_one_or_none()
    if not workflow:
        raise WorkflowValidationError("Workflow definition not found")

    definition = workflow.definition or {}
    validate_definition(definition)
    nodes = definition.get("nodes") or []
    edges = definition.get("edges") or []
    nodes_by_key = {str(node["key"]): node for node in nodes}
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        outgoing[source].append(edge)
        incoming[target].append(edge)
    return run, workflow, nodes, nodes_by_key, outgoing, incoming


async def _process_workflow_queue(
    db: AsyncSession,
    run: WorkflowRun,
    workflow: WorkflowDefinition,
    nodes_by_key: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
    queue: deque[str],
    visited: set[str],
    completed: set[str],
) -> WorkflowRun:
    while queue:
        node_key = queue.popleft()
        if node_key in visited:
            continue
        prerequisites = [str(edge["source"]) for edge in incoming.get(node_key, [])]
        if prerequisites and any(source not in completed for source in prerequisites):
            queue.append(node_key)
            continue

        visited.add(node_key)
        node = nodes_by_key[node_key]
        node_type = str(node.get("type") or "task")
        node_title = str(node.get("title") or node_key)
        node_run = WorkflowNodeRun(
            workflow_run_id=run.id,
            node_key=node_key,
            node_type=node_type,
            title=node_title,
            status="running",
            input_payload={
                "input": run.input_payload or {},
                "node_outputs": run.context_snapshot.get("node_outputs", {}),
            },
            started_at=datetime.now(timezone.utc),
        )
        db.add(node_run)
        await db.flush()

        run.current_node_key = node_key
        await db.commit()

        try:
            output_payload, next_keys, final_status = await _execute_node(
                db,
                run,
                workflow,
                node,
                outgoing.get(node_key, []),
                run.context_snapshot.get("node_outputs", {}),
            )
            node_run.status = final_status
            node_run.output_payload = output_payload
            node_run.finished_at = datetime.now(timezone.utc)
            _update_run_context(run, node_key=node_key, node_output=output_payload, visited=True)

            if final_status == "waiting_human":
                run.status = "waiting_human"
                await db.commit()
                return run
        except Exception as exc:
            node_run.status = "failed"
            node_run.error_message = str(exc)
            node_run.finished_at = datetime.now(timezone.utc)
            _update_run_context(run, node_key=node_key, visited=True)
            _finalize_run(run, status="failed", error_message=str(exc), current_node_key=node_key)
            await db.commit()
            raise

        completed.add(node_key)

        if node_type == "end":
            break

        for next_key in next_keys:
            if next_key not in completed:
                queue.append(next_key)

        await db.commit()

    _finalize_run(run, status="completed", current_node_key=None)
    await db.commit()
    await db.refresh(run)
    return run


async def execute_workflow_run(db: AsyncSession, run_id: uuid.UUID) -> WorkflowRun:
    """Execute a workflow run in-process using a minimal orchestration engine."""
    run, workflow, nodes, nodes_by_key, outgoing, incoming = await _load_workflow_state(db, run_id)

    start_node = next(node for node in nodes if node.get("type") == "start")
    queue: deque[str] = deque([str(start_node["key"])])
    visited: set[str] = set()
    completed: set[str] = set()

    now = datetime.now(timezone.utc)
    run.status = "running"
    run.started_at = run.started_at or now
    run.current_node_key = str(start_node["key"])
    run.error_message = None
    run.finished_at = None
    run.context_snapshot = {
        "input": run.input_payload or {},
        "node_outputs": {},
        "visited": [],
    }
    await db.commit()

    return await _process_workflow_queue(db, run, workflow, nodes_by_key, outgoing, incoming, queue, visited, completed)


async def resume_workflow_run(
    db: AsyncSession,
    run_id: uuid.UUID,
    *,
    action: str,
    resolved_by: uuid.UUID,
) -> WorkflowRun:
    run, workflow, _nodes, nodes_by_key, outgoing, incoming = await _load_workflow_state(db, run_id)
    if run.status != "waiting_human" or not run.current_node_key:
        raise WorkflowValidationError("Workflow run is not waiting for approval")

    node_key = run.current_node_key
    node = nodes_by_key.get(node_key)
    if not node or str(node.get("type") or "") != "approval":
        raise WorkflowValidationError("Current workflow node is not an approval node")

    node_run_result = await db.execute(
        select(WorkflowNodeRun)
        .where(WorkflowNodeRun.workflow_run_id == run.id, WorkflowNodeRun.node_key == node_key)
        .order_by(WorkflowNodeRun.created_at.desc())
    )
    node_run = node_run_result.scalars().first()
    if not node_run or node_run.status != "waiting_human":
        raise WorkflowValidationError("Approval node run is not waiting")

    action_normalized = action.strip().lower()
    if action_normalized not in {"approve", "reject"}:
        raise WorkflowValidationError("Action must be approve or reject")

    resolution_payload = {
        "message": "Manual approval approved" if action_normalized == "approve" else "Manual approval rejected",
        "node_key": node_key,
        "resolved_by": str(resolved_by),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "action": action_normalized,
    }
    next_keys = [str(edge["target"]) for edge in outgoing.get(node_key, [])] if action_normalized == "approve" else []
    resolution_payload["next"] = next_keys

    node_run.status = "completed" if action_normalized == "approve" else "rejected"
    node_run.output_payload = resolution_payload
    node_run.finished_at = datetime.now(timezone.utc)
    _update_run_context(run, node_key=node_key, node_output=resolution_payload, visited=True)

    if action_normalized == "reject":
        _finalize_run(run, status="rejected", current_node_key=None)
        await db.commit()
        await db.refresh(run)
        return run

    run.status = "running"
    run.error_message = None
    run.finished_at = None
    run.current_node_key = next_keys[0] if next_keys else None
    await db.commit()

    visited = set((run.context_snapshot or {}).get("visited", []))
    completed = set((run.context_snapshot or {}).get("visited", []))
    queue: deque[str] = deque(next_keys)
    return await _process_workflow_queue(db, run, workflow, nodes_by_key, outgoing, incoming, queue, visited, completed)
