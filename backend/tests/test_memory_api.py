import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api import memory as memory_api
from app.schemas.schemas import MemorySearchRequest


class DummyResult:
    def __init__(self, values=None, scalar_value=None):
        self._values = list(values or [])
        self._scalar_value = scalar_value

    def scalar_one_or_none(self):
        if self._scalar_value is not None:
            return self._scalar_value
        return self._values[0] if self._values else None

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class RecordingDB:
    def __init__(self, responses=None):
        self.responses = list(responses or [])

    async def execute(self, _statement, _params=None):
        if not self.responses:
            raise AssertionError("unexpected execute() call")
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_search_agent_memory_merges_memory_golden_and_kb(monkeypatch):
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    current_user = SimpleNamespace(id=user_id, tenant_id=tenant_id, role="member")
    agent = SimpleNamespace(id=agent_id, tenant_id=tenant_id)

    memory_row = SimpleNamespace(
        id=uuid.uuid4(),
        title="Preferred response style",
        content="Please use concise bullet points in weekly summaries.",
        scope="user",
        memory_type="preference",
        source_type="manual",
        visibility="private",
        importance_score=90,
        updated_at=now,
    )
    golden_row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        question="How should the weekly summary be formatted?",
        normalized_question="how should the weekly summary be formatted",
        correct_answer="Use concise bullet points with clear owners and due dates.",
        status="approved",
    )

    db = RecordingDB(
        responses=[
            DummyResult([memory_row]),
            DummyResult([golden_row]),
        ]
    )

    async def fake_check_agent_access(_db, _user, _agent_id):
        return agent, "use"

    async def fake_search_enterprise_kb(_tenant_id, _query, _limit):
        return [
            memory_api.MemorySearchItem(
                source="enterprise_kb",
                score=0.42,
                title="summary-guidelines.md",
                content="Weekly summaries should stay concise and action-oriented.",
                metadata={"path": "guides/summary-guidelines.md"},
            )
        ]

    monkeypatch.setattr(memory_api, "check_agent_access", fake_check_agent_access)
    monkeypatch.setattr(memory_api, "_search_enterprise_kb", fake_search_enterprise_kb)

    result = await memory_api.search_agent_memory(
        agent_id=agent_id,
        body=MemorySearchRequest(query="weekly summary concise bullet points", limit=5),
        current_user=current_user,
        db=db,
    )

    assert result.total == 3
    assert [item.source for item in result.items] == ["memory", "golden_example", "enterprise_kb"]
    assert result.items[0].memory_id == memory_row.id
    assert result.items[1].golden_example_id == golden_row.id

