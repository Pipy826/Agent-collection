"""Static regression tests for OpenCode gateway integration (no DB required)."""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"


def _read_backend(rel: str) -> str:
    return (BACKEND_ROOT / rel).read_text(encoding="utf-8")


def _read_frontend(rel: str) -> str:
    return (FRONTEND_ROOT / rel).read_text(encoding="utf-8")


def test_websocket_opencode_routing():
    source = _read_backend("app/api/websocket.py")
    assert 'if agent_type == "opencode":' in source
    assert 'if agent_type == "openclaw":' not in source


def test_gateway_auth_hashed_only():
    source = _read_backend("app/api/opencode_gateway.py")
    assert "AgentNode.api_key_hash == key_hash" in source
    assert "AgentNode.api_key_hash == api_key" not in source


def test_report_uses_send_to_session():
    source = _read_backend("app/api/opencode_gateway.py")
    report_block = source.split("Push to WebSocket")[1][:500]
    assert "send_to_session" in report_block
    assert "send_message(str(agent.id)" not in report_block


def test_setup_guide_clawith_sync_and_dynamic_url():
    source = _read_backend("app/api/opencode_gateway.py")
    assert "clawith_sync.md" in source
    assert "get_public_base_url" in source
    assert 'base_url = "https://try.opencode.ai"' not in source


def test_frontend_setup_urls():
    source = _read_frontend("src/pages/AgentCreate.tsx")
    assert "/api/opencode/poll" in source
    assert "/api/gateway/poll" not in source


def test_schema_opencode_last_seen():
    source = _read_backend("app/schemas/schemas.py")
    assert "opencode_last_seen:" in source
    assert "openclaw_last_seen:" not in source


def test_heartbeat_skips_opencode():
    source = _read_backend("app/services/heartbeat.py")
    assert 'agent_type", "native") == "opencode"' in source


def test_trigger_daemon_skips_opencode():
    source = _read_backend("app/services/trigger_daemon.py")
    assert 'agent_type", "native") == "opencode"' in source
