"""Real runtime validation for the OpenHands preparation path through FastAPI.

Run with LUMINA backend already started. This test never approves or applies the
proposal; it must stop at awaiting_approval and the real repository must remain
unchanged.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("LUMINA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("LUMINA_OPENHANDS_RUNTIME_TIMEOUT", "300"))
PROBE_PATH = "openhands_runtime_probe.txt"


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


def main() -> int:
    probe = Path(PROBE_PATH)
    if probe.exists():
        raise RuntimeError(f"Refusing runtime validation because {PROBE_PATH} already exists.")

    create_payload = {
        "instruction": (
            f"Create a new text file named {PROBE_PATH} containing exactly "
            "LUMINA_OPENHANDS_RUNTIME_OK followed by a newline. Do not modify any other file."
        ),
        "target_paths": [PROBE_PATH],
        "require_approval": True,
        "auto_start_after_approval": False,
        "allow_file_creation": True,
        "allow_file_deletion": False,
        "backup_policy": "required",
        "build_policy": "disabled",
        "rollback_policy": "on_any_failure",
        "metadata": {"coding_engine": "openhands", "runtime_validation": True},
    }

    created = _json_request("POST", "/api/code-builder/tasks", create_payload)
    task = created.get("task") or {}
    task_id = task.get("task_id")
    if not task_id:
        raise RuntimeError(f"Task creation returned no task_id: {created}")

    deadline = time.monotonic() + TIMEOUT_SECONDS
    final = task
    while time.monotonic() < deadline:
        final = _json_request("GET", f"/api/code-builder/tasks/{task_id}")
        phase = str(final.get("phase") or "")
        if phase in {"awaiting_approval", "failed", "cancelled", "timed_out"}:
            break
        time.sleep(1.0)
    else:
        raise RuntimeError(f"Task {task_id} did not reach a terminal preparation phase in time.")

    phase = str(final.get("phase") or "")
    preparation = final.get("preparation_result") or {}
    patch = preparation.get("patch") or {}
    operations = patch.get("operations") or []
    metadata = preparation.get("metadata") or {}
    operation_paths = [str(item.get("path")) for item in operations if isinstance(item, dict)]

    result = {
        "task_id": task_id,
        "phase": phase,
        "engine": metadata.get("coding_engine"),
        "runtime_validated_for_task": metadata.get("runtime_validated_for_task"),
        "scope_enforced": metadata.get("scope_enforced"),
        "operation_count": len(operations),
        "operation_paths": operation_paths,
        "source_repository_unchanged": not probe.exists(),
        "ready": (
            phase == "awaiting_approval"
            and metadata.get("coding_engine") == "openhands"
            and metadata.get("runtime_validated_for_task") is True
            and metadata.get("scope_enforced") is True
            and len(operations) >= 1
            and set(operation_paths) == {PROBE_PATH}
            and not probe.exists()
        ),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
