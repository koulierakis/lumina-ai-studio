from __future__ import annotations

from pathlib import Path

from code_builder.persistent_task_store import PersistentTaskStore
from code_builder.router import (
    CodeBuilderTaskPhase,
    StoredTask,
    TaskCreateRequest,
)
from code_builder.task_service import TaskCancellationToken, TaskRequest


def _stored_task(task_id: str, phase: CodeBuilderTaskPhase) -> StoredTask:
    request = TaskRequest(
        task_id=task_id,
        instruction="Add a focused regression test.",
        target_paths=("tests/test_regression.py",),
        metadata={"patch_operations": []},
    )
    api_request = TaskCreateRequest(
        instruction=request.instruction,
        target_paths=request.target_paths,
        require_approval=True,
        auto_start_after_approval=False,
    )
    return StoredTask(
        request=request,
        api_request=api_request,
        phase=phase,
        created_at_epoch=1.0,
        updated_at_epoch=1.0,
        require_approval=True,
        auto_start_after_approval=False,
        cancellation_token=TaskCancellationToken(task_id=task_id),
        metadata={"test": True},
    )


def test_task_store_round_trips_events_and_idempotency(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime" / "lumina.db"
    first = PersistentTaskStore(path=database_path)
    task = first.create(
        _stored_task("persisted-task", CodeBuilderTaskPhase.AWAITING_APPROVAL),
        idempotency_key="request-1",
    )
    first.append_event(task.request.task_id, {"sequence": 1, "message": "ready"})

    second = PersistentTaskStore(path=database_path)
    restored = second.get("persisted-task")
    duplicate = second.create(
        _stored_task("different-task", CodeBuilderTaskPhase.QUEUED),
        idempotency_key="request-1",
    )

    assert restored.phase is CodeBuilderTaskPhase.AWAITING_APPROVAL
    assert restored.events[0]["message"] == "ready"
    assert duplicate.request.task_id == "persisted-task"


def test_restart_marks_pre_mutation_work_for_single_resume(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime" / "lumina.db"
    first = PersistentTaskStore(path=database_path)
    first.create(_stored_task("queued-task", CodeBuilderTaskPhase.ANALYZING))

    second = PersistentTaskStore(path=database_path)
    restored = second.get("queued-task")

    assert restored.phase is CodeBuilderTaskPhase.QUEUED
    assert restored.metadata["recovery_state"] == "restart_resume_preparation"
    assert len(second.tasks_for_automatic_resume()) == 1

    restored.metadata["recovery_state"] = "restart_resume_scheduled"
    restored.touch()
    assert second.tasks_for_automatic_resume() == ()


def test_restart_blocks_replay_after_execution_started(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime" / "lumina.db"
    first = PersistentTaskStore(path=database_path)
    first.create(_stored_task("mutating-task", CodeBuilderTaskPhase.EXECUTING))

    second = PersistentTaskStore(path=database_path)
    restored = second.get("mutating-task")

    assert restored.phase is CodeBuilderTaskPhase.FAILED
    assert restored.metadata["safe_to_auto_resume"] is False
    assert restored.result["error_type"] == "BackendRestartInterruption"
    assert second.tasks_for_automatic_resume() == ()
