from __future__ import annotations

from pathlib import Path

from code_builder.persistent_task_store import PersistentTaskStore
from code_builder.router import CodeBuilderTaskPhase, StoredTask, TaskCreateRequest
from code_builder.task_service import TaskCancellationToken, TaskRequest, TaskStatus


def _task(*, task_id: str, phase: CodeBuilderTaskPhase) -> StoredTask:
    api = TaskCreateRequest(
        instruction="Persist this Code Builder task",
        require_approval=True,
        auto_start_after_approval=True,
    )
    request = TaskRequest(
        task_id=task_id,
        instruction=api.instruction,
        context=api.context,
        target_paths=api.target_paths,
        excluded_paths=api.excluded_paths,
        build_commands=api.build_commands,
        task_timeout_seconds=api.task_timeout_seconds,
        dry_run=api.dry_run,
        allow_file_creation=api.allow_file_creation,
        allow_file_deletion=api.allow_file_deletion,
        require_clean_repository=api.require_clean_repository,
        stop_build_on_first_failure=api.stop_build_on_first_failure,
        backup_policy=api.backup_policy,
        build_policy=api.build_policy,
        rollback_policy=api.rollback_policy,
        metadata=api.metadata,
    )
    return StoredTask(
        request=request,
        api_request=api,
        phase=phase,
        created_at_epoch=100.0,
        updated_at_epoch=100.0,
        require_approval=True,
        auto_start_after_approval=True,
        cancellation_token=TaskCancellationToken(task_id=task_id),
    )


def _restart(path: Path) -> PersistentTaskStore:
    return PersistentTaskStore(path=path, retention_seconds=10_000_000_000.0)


def test_completed_task_survives_store_restart(tmp_path: Path) -> None:
    path = tmp_path / "lumina.db"
    first = _restart(path)
    task = first.create(_task(task_id="completed-1", phase=CodeBuilderTaskPhase.COMPLETED))
    task.result = {
        "task_id": task.request.task_id,
        "status": TaskStatus.SUCCEEDED.value,
        "success": True,
        "changed_paths": ["README.md"],
    }
    task.finished_at_epoch = 150.0
    task.touch()

    second = _restart(path)
    restored = second.get("completed-1")

    assert restored.phase is CodeBuilderTaskPhase.COMPLETED
    assert restored.result["success"] is True
    assert restored.result["changed_paths"] == ["README.md"]


def test_awaiting_approval_survives_restart_with_review_and_preparation(tmp_path: Path) -> None:
    path = tmp_path / "lumina.db"
    first = _restart(path)
    task = first.create(_task(task_id="approval-1", phase=CodeBuilderTaskPhase.AWAITING_APPROVAL))
    task.preparation_result = {
        "status": "succeeded",
        "plan": {"title": "Prepared change"},
        "patch": {"files": ["frontend/src/App.js"]},
        "patch_validation": {"valid": True},
    }
    task.review_result = {"status": "completed", "verdict": "pass", "summary": "Safe"}
    task.touch()

    second = _restart(path)
    restored = second.get("approval-1")

    assert restored.phase is CodeBuilderTaskPhase.AWAITING_APPROVAL
    assert restored.preparation_result["plan"]["title"] == "Prepared change"
    assert restored.review_result["verdict"] == "pass"


def test_prewrite_interruption_is_requeued_for_safe_preparation(tmp_path: Path) -> None:
    path = tmp_path / "lumina.db"
    first = _restart(path)
    task = first.create(_task(task_id="analysis-1", phase=CodeBuilderTaskPhase.ANALYZING))
    task.metadata["checkpoint"] = "analysis"
    task.touch()

    second = _restart(path)
    restored = second.get("analysis-1")

    assert restored.phase is CodeBuilderTaskPhase.QUEUED
    assert restored.metadata["recovery_state"] == "restart_resume_preparation"
    assert restored.metadata["interrupted_phase"] == "analyzing"
    assert restored.finished_at_epoch is None


def test_applying_interruption_never_auto_replays_patch(tmp_path: Path) -> None:
    path = tmp_path / "lumina.db"
    first = _restart(path)
    task = first.create(_task(task_id="apply-1", phase=CodeBuilderTaskPhase.APPLYING))
    task.metadata["checkpoint"] = "patch_application"
    task.touch()

    second = _restart(path)
    restored = second.get("apply-1")

    assert restored.phase is CodeBuilderTaskPhase.FAILED
    assert restored.metadata["recovery_state"] == "interrupted_requires_manual_review"
    assert restored.metadata["safe_to_auto_resume"] is False
    assert restored.result["error_type"] == "BackendRestartInterruption"


def test_idempotency_key_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "lumina.db"
    first = _restart(path)
    original = first.create(
        _task(task_id="idem-1", phase=CodeBuilderTaskPhase.AWAITING_APPROVAL),
        idempotency_key="same-request",
    )

    second = _restart(path)
    duplicate = second.create(
        _task(task_id="idem-2", phase=CodeBuilderTaskPhase.AWAITING_APPROVAL),
        idempotency_key="same-request",
    )

    assert duplicate.request.task_id == original.request.task_id
    assert second.count() == 1
