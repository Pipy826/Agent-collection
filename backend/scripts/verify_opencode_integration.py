#!/usr/bin/env python3
"""Static + optional live verification for OpenCode agent integration.

Run from backend/:  python scripts/verify_opencode_integration.py
Live checks require backend at BASE_URL (default http://127.0.0.1:8000).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent


def _read(rel: str) -> str:
    path = BACKEND_ROOT / rel
    return path.read_text(encoding="utf-8")


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def run_static_checks() -> tuple[int, int]:
    passed = 0
    total = 0

    print("\n=== Static code checks ===\n")

    ws = _read("app/api/websocket.py")
    total += 1
    if check(
        "WebSocket routes opencode (not openclaw)",
        'if agent_type == "opencode":' in ws and 'if agent_type == "openclaw":' not in ws,
    ):
        passed += 1

    gw = _read("app/api/opencode_gateway.py")
    total += 1
    if check(
        "Gateway auth uses hashed keys only",
        "AgentNode.api_key_hash == key_hash" in gw
        and "AgentNode.api_key_hash == api_key" not in gw,
    ):
        passed += 1

    total += 1
    if check(
        "Report uses send_to_session",
        "send_to_session" in gw and 'send_message(str(agent.id)' not in gw.split("Push to WebSocket")[1][:400] if "Push to WebSocket" in gw else "send_to_session" in gw,
    ):
        passed += 1

    total += 1
    if check(
        "Setup guide skill name clawith_sync",
        "clawith_sync.md" in gw,
    ):
        passed += 1

    total += 1
    if check(
        "Setup guide uses platform_service URL",
        "get_public_base_url" in gw and 'base_url = "https://try.opencode.ai"' not in gw,
    ):
        passed += 1

    schema = _read("app/schemas/schemas.py")
    total += 1
    if check(
        "AgentOut exposes opencode_last_seen",
        "opencode_last_seen:" in schema and "openclaw_last_seen:" not in schema,
    ):
        passed += 1

    hb = _read("app/services/heartbeat.py")
    total += 1
    if check(
        "Heartbeat skips opencode agents",
        'agent_type", "native") == "opencode"' in hb,
    ):
        passed += 1

    td = _read("app/services/trigger_daemon.py")
    total += 1
    if check(
        "Trigger daemon skips opencode agents",
        'agent_type", "native") == "opencode"' in td,
    ):
        passed += 1

    fe = REPO_ROOT / "frontend" / "src" / "pages" / "AgentCreate.tsx"
    fe_text = fe.read_text(encoding="utf-8") if fe.exists() else ""
    total += 1
    if check(
        "Frontend setup URLs use /api/opencode/",
        "/api/opencode/poll" in fe_text and "/api/gateway/poll" not in fe_text,
    ):
        passed += 1

    layout = REPO_ROOT / "frontend" / "src" / "pages" / "Layout.tsx"
    layout_text = layout.read_text(encoding="utf-8") if layout.exists() else ""
    total += 1
    if check(
        "Layout offline check uses opencode_last_seen",
        "agent.opencode_last_seen" in layout_text
        and "agent.status === 'running' && agent.opencode_last_seen" not in layout_text,
    ):
        passed += 1

    detail = REPO_ROOT / "frontend" / "src" / "pages" / "AgentDetail.tsx"
    detail_text = detail.read_text(encoding="utf-8") if detail.exists() else ""
    total += 1
    if check(
        "AgentDetail offline check uses opencode_last_seen",
        "opencode_last_seen" in detail_text
        and "agent.status === 'running' && (agent as any).opencode_last_seen" not in detail_text,
    ):
        passed += 1

    nginx = REPO_ROOT / "frontend" / "nginx.conf"
    nginx_text = nginx.read_text(encoding="utf-8") if nginx.exists() else ""
    total += 1
    if check(
        "Nginx proxies /api/ to backend",
        "location /api/" in nginx_text and "proxy_pass http://backend:8000" in nginx_text,
    ):
        passed += 1

    bootstrap = _read("app/scripts/bootstrap_db.py")
    total += 1
    if check(
        "Bootstrap imports agent_node model",
        "import app.models.agent_node" in bootstrap,
    ):
        passed += 1

    main_py = _read("app/main.py")
    total += 1
    if check(
        "OpenCode gateway router registered",
        "opencode_gateway_router" in main_py,
    ):
        passed += 1

    agents = _read("app/api/agents.py")
    total += 1
    if check(
        "Agent create uses selectinload for nodes",
        "selectinload(Agent.nodes)" in agents,
    ):
        passed += 1

    return passed, total


def run_live_checks(base_url: str) -> tuple[int, int]:
    import urllib.error
    import urllib.request

    passed = 0
    total = 0
    base = base_url.rstrip("/")

    print(f"\n=== Live API checks ({base}) ===\n")

    total += 1
    try:
        req = urllib.request.Request(f"{base}/api/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode())
        ok = resp.status == 200 and body.get("status") in ("ok", "healthy", True, "up")
        if check("Health endpoint", ok, str(body)[:80]):
            passed += 1
    except Exception as e:
        check("Health endpoint", False, str(e))

    total += 1
    try:
        req = urllib.request.Request(f"{base}/api/opencode/poll")
        urllib.request.urlopen(req, timeout=5)
        check("Poll rejects missing API key", False, "expected error")
    except urllib.error.HTTPError as e:
        ok = e.code in (401, 403, 422)
        if check("Poll rejects missing API key", ok, f"HTTP {e.code}"):
            passed += 1
    except Exception as e:
        check("Poll rejects missing API key", False, str(e))

    total += 1
    try:
        req = urllib.request.Request(
            f"{base}/api/opencode/heartbeat",
            method="POST",
            data=b"",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
        check("Heartbeat rejects missing API key", False, "expected error")
    except urllib.error.HTTPError as e:
        ok = e.code in (401, 403, 422)
        if check("Heartbeat rejects missing API key", ok, f"HTTP {e.code}"):
            passed += 1
    except Exception as e:
        check("Heartbeat rejects missing API key", False, str(e))

    total += 1
    try:
        req = urllib.request.Request(f"{base}/api/gateway/poll")
        urllib.request.urlopen(req, timeout=5)
        check("Legacy /api/gateway/poll is not mounted", False, "unexpected 200")
    except urllib.error.HTTPError as e:
        ok = e.code == 404
        if check("Legacy /api/gateway/poll is not mounted", ok, f"HTTP {e.code}"):
            passed += 1
    except Exception as e:
        check("Legacy /api/gateway/poll is not mounted", False, str(e))

    return passed, total


def main() -> int:
    print("OpenCode integration verification")
    print(f"Backend: {BACKEND_ROOT}")

    sp, st = run_static_checks()
    print(f"\nStatic: {sp}/{st} passed")

    base_url = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:8000")
    lp, lt = run_live_checks(base_url)

    print(f"\nLive:   {lp}/{lt} passed")
    total_pass = sp + lp
    total = st + lt
    print(f"\nOverall: {total_pass}/{total} passed")

    return 0 if total_pass == total else 1


if __name__ == "__main__":
    sys.exit(main())
