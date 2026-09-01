"""Controlled real-runtime validation of OpenHands approval, apply and rollback.

This script intentionally writes only one temporary validation file inside the
repository, restricts the task to that exact path, verifies backup/apply, then
requires rollback to restore the original content. It cleans the validation
folder when finished.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("LUMINA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("LUMINA_OPENHANDS_APPLY_TIMEOUT", "600"))
SANDBOX_DIR = Path("runtime_validation_sandbox")
PROBE = SANDBOX_DIR / "openhands_apply_probe.txt"
ORIGINAL = "LUMINA_OPENHANDS_ORIGINAL\n"
MODIFIED = "LUMINA_OPENHANDS_APPLIED\n"


def _json_request(method: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc


def _wait(task_id: str, accepted: set[str]) -> dict:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last: dict = {}
    while time.monotonic() < deadline:
        last = _json_request("GET", f"/api/code-builder/tasks/{task_id}")
        phase = str(last.get("phase") or "")
        if phase in accepted or phase in {"failed", "cancelled", "timed_out", "rollback_failed"}:
            return last
        time.sleep(1.0)
    raise RuntimeError(f"Task {task_id} did not reach one of {sorted(accepted)} in time. Last={last}")


def main() -> int:
    if os.environ.get("LUMINA_RUN_OPENHANDS_APPLY_ROLLBACK") != "1":
        print("SKIPPED: set LUMINA_RUN_OPENHANDS_APPLY_ROLLBACK=1 to run the controlled write/rollback validation.")
        return 2

    if SANDBOX_DIR.exists():
        raise RuntimeError(f"Refusing to reuse existing validation directory: {SANDBOX_DIR}")

    SANDBOX_DIR.mkdir(parents=True)
    PROBE.write_text(ORIGINAL, encoding="utf-8")
    task_id = None
    try:
        relative_probe = PROBE.as_posix()
        create_payload = {
            "instruction": (
                f"Modify only {relative_probe}. Replace its complete contents with exactly "
                "LUMINA_OPENHANDS_APPLIED followed by a newline. Do not change any other file."
            ),
            "target_paths": [relative_probe],
            "require_approval": True,
            "auto_start_after_approval": False,
            "allow_file_creation": False,
            "allow_file_deletion": False,
            "backup_policy": "required",
            "build_policy": "disabled",
            "rollback_policy": "on_any_failure",
            "metadata": {"coding_engine": "openhands", "runtime_validation": "apply_rollback"},
        }
        created = _json_request("POST", "/api/code-builder/tasks", create_payload)
        task_id = (created.get("task") or {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"Task creation returned no task_id: {created}")

        prepared = _wait(task_id, {"awaiting_approval"})
        if prepared.get("phase") != "awaiting_approval":
            raise RuntimeError(f"Preparation failed: {prepared}")
        if PROBE.read_text(encoding="utf-8") != ORIGINAL:
            raise RuntimeError("Real repository changed before approval.")

        preparation = prepared.get("preparation_result") or {}
        operations = (preparation.get("patch") or {}).get("operations") or []
        paths = {str(item.get("path")) for item in operations if isinstance(item, dict)}
        if paths != {relative_probe}:
            raise RuntimeError(f"OpenHands proposal escaped validation scope: {sorted(paths)}")

        _json_request(
            "POST",
            f"/api/code-builder/tasks/{task_id}/approve",
            {"decision": "approve", "comment": "Controlled OpenHands apply/rollback runtime validation.", "start_immediately": True},
        )
        applied = _wait(task_id, {"completed"})
        if applied.get("phase") != "completed":
            raise RuntimeError(f"Approved execution failed: {applied}")
        if PROBE.read_text(encoding="utf-8") != MODIFIED:
            raise RuntimeError("Approved OpenHands patch did not produce the expected file content.")

        _json_request(
            "POST",
            f"/api/code-builder/tasks/{task_id}/rollback",
            {"reason": "Controlled OpenHands runtime rollback validation.", "force": False},
        )
        rolled_back = _wait(task_id, {"rolled_back"})
        if rolled_back.get("phase") != "rolled_back":
            raise RuntimeError(f"Rollback failed: {rolled_back}")
        if PROBE.read_text(encoding="utf-8") != ORIGINAL:
            raise RuntimeError("Rollback did not restore the original validation file.")

        print(
            json.dumps(
                {
                    "task_id": task_id,
                    "preparation": "PASS",
                    "approval": "PASS",
                    "backup_apply": "PASS",
                    "rollback": "PASS",
                    "scope": relative_probe,
                    "ready_for_repeated_tasks_gate": True,
                },
                indent=2,
            )
        )
        return 0
    finally:
        shutil.rmtree(SANDBOX_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
