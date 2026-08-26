"""Run Code Builder planning pipeline E2E test."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/code-builder"


def request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} {path}: {body}", file=sys.stderr)
        raise


def main() -> int:
    create_payload = {
        "instruction": "Add a one-line comment at the top of backend/code_builder/__init__.py describing the package version.",
        "target_paths": ["backend/code_builder/__init__.py"],
        "require_approval": True,
        "auto_start_after_approval": True,
        "build_policy": "disabled",
        "backup_policy": "disabled",
        "dry_run": True,
        "task_timeout_seconds": 1800,
    }
    created = request("POST", "/tasks", create_payload)
    task = created["task"]
    task_id = task["task_id"]
    print(f"created task {task_id} phase={task['phase']}")

    approved = request(
        "POST",
        f"/tasks/{task_id}/approve",
        {"decision": "approve", "start_immediately": True},
    )
    print(f"approved phase={approved['task']['phase']}")

    terminal = {
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "rolled_back",
        "rollback_failed",
    }
    seen: list[str] = []
    deadline = time.time() + 900
    last_detail: dict | None = None

    while time.time() < deadline:
        detail = request("GET", f"/tasks/{task_id}")
        last_detail = detail
        phase = detail["phase"]
        status = detail.get("status") or detail.get("current_status")
        stage = detail.get("stage")
        if phase not in seen:
            seen.append(phase)
            print(f"phase={phase} status={status} stage={stage}")
        if phase in terminal:
            break
        time.sleep(2)

    print("seen phases:", " -> ".join(seen))
    if last_detail:
        print("final:", json.dumps(last_detail, indent=2)[:4000])
        if last_detail.get("phase") == "failed":
            error = last_detail.get("error") or last_detail.get("last_error")
            print("error:", error)
            return 1
    if "generating_patch" in seen or last_detail and last_detail.get("phase") == "completed":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
