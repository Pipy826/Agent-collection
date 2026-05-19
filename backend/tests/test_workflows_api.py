import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import workflows as workflows_api
from app.models.workflow import WorkflowDefinition
from app.schemas.schemas import WorkflowDefinitionCreate, WorkflowDefinitionUpdate


class DummyResult:
    def __init__(self, values=None, scalar_value=None):
        self._values = list(values or [])
        self._scalar_value = scalar_value

    def scalar_one_or_none(self):
        if self._scalar_value is not None:
            return self._scalar_value
        return self._values[0] if self._values else None


class RecordingDB:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.added = []
        self.flushed = False
        self.committed = False
        self.refreshed = []

    async def execute(self, _statement, _params=None):
        if not self.responses:
            raise AssertionError("unexpected execute() call")
        return self.responses.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def refresh(self, value):
        self.refreshed.append(value)


def _valid_definition():
    return {
        "nodes": [
            {"key": "start", "type": "start", "title": "Start"},
            {"key": "finish", "type": "end", "title": "Finish"},
        ],
        "edges": [{"source": "start", "target": "finish"}],
    }


@pytest.mark.asyncio
async def test_create_workflow_rejects_invalid_definition(monkeypatch):
    current_user = SimpleNamespace(id=uuid.uuid4(), role="member")
    agent_id = uuid.uuid4()
    db = RecordingDB()

    async def fake_check_agent_access(_db, _user, _agent_id):
        return SimpleNamespace(id=agent_id, tenant_id=uuid.uuid4()), "manage"

    monkeypatch.setattr(workflows_api, "check_agent_access", fake_check_agent_access)

    with pytest.raises(HTTPException) as excinfo:
        await workflows_api.create_workflow(
            agent_id=agent_id,
            data=WorkflowDefinitionCreate(name="Broken", definition={}, status="draft"),
            current_user=current_user,
            db=db,
        )

    assert excinfo.value.status_code == 400
    assert "at least one node" in excinfo.value.detail


@pytest.mark.asyncio
async def test_update_workflow_definition_bumps_version(monkeypatch):
    current_user = SimpleNamespace(id=uuid.uuid4(), role="member")
    agent_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    row = WorkflowDefinition(
        id=workflow_id,
        agent_id=agent_id,
        tenant_id=uuid.uuid4(),
        created_by=current_user.id,
        name="Weekly summary",
        description="Old description",
        status="draft",
        version=2,
        definition=_valid_definition(),
        canvas_layout={},
        input_schema={},
        output_schema={},
        created_at=now,
        updated_at=now,
    )
    db = RecordingDB(responses=[DummyResult([row])])

    async def fake_check_agent_access(_db, _user, _agent_id):
        return SimpleNamespace(id=agent_id, tenant_id=row.tenant_id), "manage"

    monkeypatch.setattr(workflows_api, "check_agent_access", fake_check_agent_access)

    result = await workflows_api.update_workflow(
        agent_id=agent_id,
        workflow_id=workflow_id,
        data=WorkflowDefinitionUpdate(
            definition=_valid_definition(),
            description="Revised description",
        ),
        current_user=current_user,
        db=db,
    )

    assert row.version == 3
    assert row.description == "Revised description"
    assert db.flushed is True
    assert db.committed is True
    assert result.version == 3
