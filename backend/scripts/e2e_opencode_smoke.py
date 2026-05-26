#!/usr/bin/env python3
"""End-to-end smoke test for OpenCode gateway (requires running stack)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:3008").rstrip("/")
EMAIL = f"oc-test-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "TestPass123!"
USERNAME = f"octest_{uuid.uuid4().hex[:8]}"


def req(method: str, path: str, body: dict | None = None, headers: dict | None = None):
    data = None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode()
    request = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return e.code, payload


def main() -> int:
    print(f"OpenCode E2E smoke @ {BASE}\n")
    failed = 0

    code, reg = req("POST", "/api/auth/register", {
        "username": USERNAME,
        "email": EMAIL,
        "password": PASSWORD,
        "display_name": "OC Tester",
    })
    if code not in (201, 200):
        print(f"[FAIL] register HTTP {code}: {reg}")
        return 1
    token = reg.get("access_token") or reg.get("token")
    if not token and isinstance(reg.get("data"), dict):
        token = reg["data"].get("access_token")
    if not token:
        code, login = req("POST", "/api/auth/login", {"username": USERNAME, "password": PASSWORD})
        if code == 200:
            token = login.get("access_token")
    if not token:
        print(f"[FAIL] no token from register: {reg}")
        return 1
    print("[PASS] register/login")
    auth = {"Authorization": f"Bearer {token}"}

    code, agent = req("POST", "/api/agents/", {
        "name": f"OC Smoke {uuid.uuid4().hex[:6]}",
        "agent_type": "opencode",
        "role_description": "E2E smoke test agent",
        "permission_scope_type": "user",
        "permission_access_level": "manage",
    }, auth)
    if code not in (201, 200):
        print(f"[FAIL] create agent HTTP {code}: {agent}")
        return 1
    api_key = agent.get("api_key")
    agent_id = agent.get("id")
    if not api_key or not agent_id:
        print(f"[FAIL] missing api_key or id: {agent}")
        return 1
    print(f"[PASS] create opencode agent id={agent_id}")

    code, hb = req("POST", "/api/opencode/heartbeat", headers={"X-Api-Key": api_key})
    if code != 200 or hb.get("status") != "ok":
        print(f"[FAIL] heartbeat HTTP {code}: {hb}")
        failed += 1
    else:
        print("[PASS] heartbeat")

    code, poll = req("GET", "/api/opencode/poll", headers={"X-Api-Key": api_key})
    if code != 200 or "messages" not in poll:
        print(f"[FAIL] poll HTTP {code}: {poll}")
        failed += 1
    else:
        print(f"[PASS] poll (messages={len(poll.get('messages', []))})")

    code, guide = req("GET", f"/api/opencode/setup-guide/{agent_id}", headers={"X-Api-Key": api_key})
    if code != 200 or guide.get("skill_filename") != "clawith_sync.md":
        print(f"[FAIL] setup-guide HTTP {code}: {guide}")
        failed += 1
    else:
        print("[PASS] setup-guide")

    code, _ = req("GET", "/api/opencode/poll", headers={"X-Api-Key": "code-invalid"})
    if code != 401:
        print(f"[FAIL] invalid key should 401, got {code}")
        failed += 1
    else:
        print("[PASS] invalid key rejected")

    print(f"\nE2E result: {'ALL PASSED' if failed == 0 else f'{failed} FAILED'}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
