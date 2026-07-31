"""Owner-only local developer monitoring and safe task execution."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = Path(os.environ.get("DEVELOPER_CENTER_HISTORY", REPO_ROOT / ".lumina-developer-history.json"))
MAX_HISTORY = 100
MAX_OUTPUT = 12_000
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|password|secret|token|authorization)\s*([:=])\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._-]+"),
)

TASKS: dict[str, dict[str, Any]] = {
    "backend_tests": {"label": "Run backend tests", "scope": "backend"},
    "frontend_tests": {"label": "Run frontend tests", "scope": "frontend"},
    "frontend_build": {"label": "Build frontend", "scope": "frontend"},
    "python_compile": {"label": "Check Python code", "scope": "backend"},
    "backend_health": {"label": "Check backend health", "scope": "backend"},
    "frontend_health": {"label": "Check frontend health", "scope": "frontend"},
    "repository_status": {"label": "Refresh repository status", "scope": "repository"},
    "runtime_scan": {"label": "Scan AI Runtime", "scope": "runtime"},
    "runtime_validate_providers": {"label": "Validate Runtime providers", "scope": "runtime"},
    "runtime_repair": {"label": "Repair Runtime configuration", "scope": "runtime"},
    "runtime_missing_models": {"label": "Detect missing Runtime models", "scope": "runtime"},
    "runtime_dependencies": {"label": "Verify Runtime dependencies", "scope": "runtime"},
    "runtime_diagnostics": {"label": "Run Runtime diagnostics", "scope": "runtime"},
    "runtime_report": {"label": "Generate Runtime report", "scope": "runtime"},
    "talking_portrait_scan": {"label": "Scan Talking Portrait Studio", "scope": "runtime"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_text(value: str | None) -> str:
    text = value or ""
    # Redact bearer tokens before generic key/value patterns so an
    # Authorization header cannot leave its value visible.
    patterns = (SENSITIVE_PATTERNS[1], SENSITIVE_PATTERNS[0])
    for pattern in patterns:
        text = pattern.sub(lambda match: f"{match.group(1) if match.lastindex and match.lastindex > 1 else 'Sensitive value'}=<redacted>", text)
    return text[:MAX_OUTPUT]


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def task_command(task_type: str) -> tuple[list[str], Path] | None:
    if task_type == "backend_tests":
        return ([sys.executable, "-m", "pytest", "tests", "-n", "0"], REPO_ROOT / "backend")
    if task_type == "frontend_tests":
        return ([_npm_command(), "test", "--", "--watchAll=false", "--runInBand"], REPO_ROOT / "frontend")
    if task_type == "frontend_build":
        return ([_npm_command(), "run", "build"], REPO_ROOT / "frontend")
    if task_type == "python_compile":
        return ([sys.executable, "-m", "compileall", "-q", "."], REPO_ROOT / "backend")
    if task_type == "repository_status":
        return (["git", "status", "--short"], REPO_ROOT)
    if task_type in {"runtime_scan", "runtime_validate_providers", "runtime_repair", "runtime_missing_models", "runtime_dependencies", "runtime_diagnostics", "runtime_report"}:
        return ([sys.executable, "-m", "ai_runtime.admin", task_type], REPO_ROOT / "backend")
    if task_type == "talking_portrait_scan":
        return ([sys.executable, "-c", "from talking_portrait_providers import talking_portrait_catalog; import json; print(json.dumps(talking_portrait_catalog(), indent=2))"], REPO_ROOT / "backend")
    return None


async def _command_output(command: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(*command, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except OSError:
        return 1, "Local command is unavailable."
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, sanitize_text(output.decode("utf-8", errors="replace"))
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 1, "Task exceeded its safe execution time limit."


async def repository_status() -> dict[str, Any]:
    branch_code, branch = await _command_output(["git", "branch", "--show-current"], REPO_ROOT, 15)
    status_code, status = await _command_output(["git", "status", "--short"], REPO_ROOT, 15)
    _, commits = await _command_output(["git", "log", "--oneline", "-5"], REPO_ROOT, 15)
    changes = []
    if status_code == 0:
        for line in status.splitlines():
            if len(line) >= 4:
                changes.append({"status": line[:2].strip() or "modified", "path": line[3:]})
    return {
        "branch": branch.strip() if branch_code == 0 else "Unavailable",
        "clean": status_code == 0 and not changes,
        "changed_files": changes[:100],
        "uncommitted_count": len(changes),
        "recent_commits": [line for line in commits.splitlines() if line][:5],
        "last_commit": next((line for line in commits.splitlines() if line), "No commits found"),
    }


def local_system_metrics() -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(REPO_ROOT)
        disk = {"free_bytes": usage.free, "total_bytes": usage.total, "used_percent": round((usage.used / usage.total) * 100, 1) if usage.total else 0}
    except OSError:
        disk = {"available": False, "message": "Local disk information is unavailable."}
    return {
        "disk": disk,
        "cpu": {"available": False, "message": "Available from the local operating system when supported."},
        "memory": {"available": False, "message": "Available from the local operating system when supported."},
    }


class DeveloperTaskManager:
    def __init__(self, history_file: Path = HISTORY_FILE) -> None:
        self.history_file = history_file
        self.tasks: dict[str, dict[str, Any]] = {}
        self.logs: deque[dict[str, str]] = deque(maxlen=300)
        self.lock = asyncio.Lock()
        self.subscribers: set[asyncio.Queue] = set()
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self._load_history()

    def _load_history(self) -> None:
        try:
            records = json.loads(self.history_file.read_text(encoding="utf-8"))
            for record in records[-MAX_HISTORY:]:
                if isinstance(record, dict) and record.get("id"):
                    self.tasks[record["id"]] = record
        except (OSError, json.JSONDecodeError):
            pass

    def _persist(self) -> None:
        try:
            self.history_file.write_text(json.dumps(list(self.tasks.values())[-MAX_HISTORY:], ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        message = {"event": event, "data": payload}
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.subscribers.discard(queue)

    def _log(self, severity: str, source: str, message: str) -> None:
        entry = {"timestamp": utc_now(), "severity": severity, "source": source, "message": sanitize_text(message)}
        self.logs.appendleft(entry)
        self._emit("log", entry)

    def list_tasks(self) -> list[dict[str, Any]]:
        return sorted(self.tasks.values(), key=lambda item: item.get("started_at") or item.get("created_at", ""), reverse=True)[:MAX_HISTORY]

    def list_logs(self, severity: str = "", source: str = "") -> list[dict[str, str]]:
        return [item for item in self.logs if (not severity or item["severity"] == severity) and (not source or item["source"] == source)]

    async def start(self, task_type: str) -> dict[str, Any]:
        if task_type not in TASKS:
            raise ValueError("This action is not available.")
        task = {"id": uuid4().hex, "task_type": task_type, "label": TASKS[task_type]["label"], "status": "queued", "created_at": utc_now(), "started_at": None, "finished_at": None, "duration_seconds": None, "output_summary": "Queued locally.", "error_summary": None, "exit_code": None}
        self.tasks[task["id"]] = task
        self._persist(); self._emit("task", task); self._log("info", "tasks", f"Queued: {task['label']}")
        asyncio.create_task(self._run(task["id"]))
        return task

    async def cancel(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError(task_id)
        if task["status"] == "queued":
            task.update({"status": "cancelled", "finished_at": utc_now(), "output_summary": "Cancelled before starting."})
        elif task["status"] == "running":
            task["status"] = "cancelled"
            process = self.processes.get(task_id)
            if process:
                process.terminate()
        else:
            raise ValueError("This task can no longer be cancelled.")
        self._persist(); self._emit("task", task); self._log("warning", "tasks", f"Cancelled: {task['label']}")
        return task

    async def _run(self, task_id: str) -> None:
        async with self.lock:
            task = self.tasks.get(task_id)
            if not task or task["status"] == "cancelled": return
            task.update({"status": "running", "started_at": utc_now(), "output_summary": "Running locally."})
            started = time.monotonic(); self._persist(); self._emit("task", task); self._log("info", "tasks", f"Started: {task['label']}")
            try:
                if task["task_type"] in {"backend_health", "frontend_health"}:
                    url = "http://127.0.0.1:8000/api/health" if task["task_type"] == "backend_health" else "http://127.0.0.1:3000"
                    await asyncio.to_thread(urllib.request.urlopen, url, timeout=5)
                    code, output = 0, "Local service responded successfully."
                else:
                    command = task_command(task["task_type"])
                    if not command: raise ValueError("This action is not available.")
                    process = await asyncio.create_subprocess_exec(*command[0], cwd=str(command[1]), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                    self.processes[task_id] = process
                    output_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=600)
                    code, output = process.returncode or 0, sanitize_text(output_bytes.decode("utf-8", errors="replace"))
                if task["status"] == "cancelled": return
                task.update({"status": "completed" if code == 0 else "failed", "exit_code": code, "output_summary": output[-MAX_OUTPUT:], "error_summary": output[-1500:] if code else None})
                self._log("info" if code == 0 else "error", "tasks", f"{task['label']}: {'completed' if code == 0 else 'failed'}")
            except asyncio.CancelledError:
                task.update({"status": "cancelled", "output_summary": "Cancelled."})
            except Exception as exc:
                task.update({"status": "failed", "exit_code": 1, "error_summary": sanitize_text(str(exc)), "output_summary": "Task could not be completed."})
                self._log("error", "tasks", f"{task['label']}: {exc}")
            finally:
                self.processes.pop(task_id, None)
                task["finished_at"] = utc_now(); task["duration_seconds"] = round(time.monotonic() - started, 2)
                self._persist(); self._emit("task", task)

    async def events(self) -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.subscribers.add(queue)
        try:
            yield f"event: snapshot\ndata: {json.dumps({'tasks': self.list_tasks(), 'logs': self.list_logs()}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            self.subscribers.discard(queue)


manager = DeveloperTaskManager()
