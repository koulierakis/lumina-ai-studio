from __future__ import annotations

import asyncio
import sys

import developer_center
import pytest
from developer_center import (
    TASKS,
    DeveloperTaskManager,
    repository_status,
    sanitize_text,
    task_command,
)


def test_task_allowlist_rejects_arbitrary_commands():
    assert "rm -rf" not in TASKS
    assert task_command("rm -rf") is None
    command, _ = task_command("python_compile")
    assert command[0] == sys.executable


def test_log_sanitization_removes_credentials():
    text = sanitize_text("GEMINI_API_KEY=secret-value Authorization: Bearer abc.def.ghi")
    assert "secret-value" not in text
    assert "abc.def.ghi" not in text
    assert "<redacted>" in text


@pytest.mark.anyio
async def test_task_lifecycle_and_history(tmp_path, monkeypatch):
    manager = DeveloperTaskManager(tmp_path / "history.json")
    monkeypatch.setattr(developer_center, "task_command", lambda _kind: ([sys.executable, "-c", "print('safe task')"], tmp_path))
    task = await manager.start("python_compile")
    assert task["status"] == "queued"
    for _ in range(50):
        current = manager.tasks[task["id"]]
        if current["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.02)
    assert manager.tasks[task["id"]]["status"] == "completed"
    assert "safe task" in manager.tasks[task["id"]]["output_summary"]
    assert (tmp_path / "history.json").exists()


@pytest.mark.anyio
async def test_event_stream_emits_snapshot(tmp_path):
    manager = DeveloperTaskManager(tmp_path / "history.json")
    stream = manager.events()
    first = await anext(stream)
    await stream.aclose()
    assert first.startswith("event: snapshot")


@pytest.mark.anyio
async def test_running_task_can_be_cancelled(tmp_path, monkeypatch):
    manager = DeveloperTaskManager(tmp_path / "history.json")
    monkeypatch.setattr(developer_center, "task_command", lambda _kind: ([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path))
    task = await manager.start("python_compile")
    for _ in range(50):
        if manager.tasks[task["id"]]["status"] == "running":
            break
        await asyncio.sleep(0.02)
    await manager.cancel(task["id"])
    for _ in range(50):
        if manager.tasks[task["id"]]["finished_at"]:
            break
        await asyncio.sleep(0.02)
    assert manager.tasks[task["id"]]["status"] == "cancelled"


@pytest.mark.anyio
async def test_repository_status_returns_safe_summary():
    status = await repository_status()
    assert "branch" in status
    assert "changed_files" in status


@pytest.mark.anyio
async def test_repository_status_is_safe_when_git_is_unavailable(monkeypatch):
    async def unavailable(*_args, **_kwargs):
        return 1, "Local command is unavailable."
    monkeypatch.setattr(developer_center, "_command_output", unavailable)
    status = await repository_status()
    assert status["branch"] == "Unavailable"
    assert status["changed_files"] == []


def test_local_system_metrics_handles_unavailable_disk(monkeypatch):
    monkeypatch.setattr(developer_center.shutil, "disk_usage", lambda _path: (_ for _ in ()).throw(OSError("offline")))
    metrics = developer_center.local_system_metrics()
    assert metrics["disk"]["available"] is False
