"""Run 10 consecutive real OpenHands preparation tasks through the LUMINA API.

No task is approved, so the real repository must remain unchanged. This is the
reliability gate required before enabling normal OpenHands use in the UI.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("LUMINA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PER_TASK_TIMEOUT = float(os.environ.get("LUMINA_OPENHANDS_RELIABILITY_TIMEOUT", "300"))
TASK_COUNT = 10


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


def _wait(task_id: str) -> dict:
    deadline = time.monotonic() + PER_TASK_TIMEOUT
    last: dict = {}
    while time.monotonic() < deadline:
        last = _json_request("GET", f"/api/code-builder/tasks/{task_id}")
        phase = str(last.get("phase") or "")
        if phase in {"awaiting_approval", "failed", "cancelled", "timed_out"}:
            return last
        time.sleep(1.0)
    raise RuntimeError(f"Task {task_id} exceeded reliability timeout. Last={last}")


def main() -> int:
    if os.environ.get("LUMINA_RUN_OPENHANDS_RELIABILITY") != "1":
        print("SKIPPED: set LUMINA_RUN_OPENHANDS_RELIABILITY=1 to run the 10-task real reliability gate.")
        return 2

    results: list[dict] = []
    for index in range(1, TASK_COUNT + 1):
        probe_path = f"openhands_reliability_probe_{index:02d}.txt"
        probe = Path(probe_path)
        if probe.exists():
            raise RuntimeError(f"Refusing reliability run because {probe_path} already exists.")

        started = time.monotonic()
        created = _json_request(
            "POST",
            "/api/code-builder/tasks",
            {
                "instruction": (
                    f"Create only {probe_path} containing exactly OPENHANDS_RELIABILITY_{index:02d} "
                    "followed by a newline. Do not modify any other file."
                ),
                "target_paths": [probe_path],
                "require_approval": True,
                "auto_start_after_approval": False,
                "allow_file_creation": True,
                "allow_file_deletion": False,
                "backup_policy": "required",
                "build_policy": "disabled",
                "rollback_policy": "on_any_failure",
                "metadata": {
                    "coding_engine": "openhands",
                    "runtime_validation": "reliability",
                    "reliability_index": index,
                },
            },
        )
        task_id = (created.get("task") or {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"Reliability task {index} returned no task_id: {created}")

        final = _wait(task_id)
        preparation = final.get("preparation_result") or {}
        metadata = preparation.get("metadata") or {}
        operations = (preparation.get("patch") or {}).get("operations") or []
        paths = {str(item.get("path")) for item in operations if isinstance(item, dict)}
        passed = (
            final.get("phase") == "awaiting_approval"
            and metadata.get("coding_engine") == "openhands"
            and metadata.get("scope_enforced") is True
            and paths == {probe_path}
            and not probe.exists()
        )
        item = {
            "index": index,
            "task_id": task_id,
            "phase": final.get("phase"),
            "duration_seconds": round(time.monotonic() - started, 3),
            "operation_paths": sorted(paths),
            "source_repository_unchanged": not probe.exists(),
            "pass": passed,
        }
        results.append(item)
        print(json.dumps(item, ensure_ascii=False))
        if not passed:
            print(json.dumps({"ready": False, "completed": index, "results": results}, indent=2))
            return 1

    summary = {
        "ready": True,
        "completed": TASK_COUNT,
        "passed": sum(1 for item in results if item["pass"]),
        "failed": sum(1 for item in results if not item["pass"]),
        "average_duration_seconds": round(sum(item["duration_seconds"] for item in results) / TASK_COUNT, 3),
        "results": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
