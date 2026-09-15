from __future__ import annotations

import time

from backend.code_builder import task_service
from backend.code_builder.task_service import (
    TaskCancellationToken,
    TaskExecutionContext,
    TaskRequest,
    TaskServiceConfiguration,
    TaskStatus,
)


class _UnusedBackupService:
    pass


class _SuccessfulPatchRollback:
    def __init__(self) -> None:
        self.seen_token = None
        self.seen_timeout = None

    def rollback(
        self,
        *,
        cancellation_token,
        timeout_seconds,
        **_kwargs,
    ):
        self.seen_token = cancellation_token
        self.seen_timeout = timeout_seconds
        assert cancellation_token.is_cancelled() is False
        return {"success": True, "rolled_back": True}


def _expired_cancelled_context(tmp_path) -> TaskExecutionContext:
    request = TaskRequest(
        task_id="interruption-rollback",
        instruction="Modify a file and validate it",
        task_timeout_seconds=0.01,
    )
    configuration = TaskServiceConfiguration(
        repository_root=tmp_path,
        rollback_timeout_seconds=7.5,
    )
    original_token = TaskCancellationToken(task_id=request.task_id)
    original_token.cancel("user cancelled")
    context = TaskExecutionContext(
        request=request,
        configuration=configuration,
        cancellation_token=original_token,
        started_monotonic=time.monotonic() - 10.0,
    )
    context.status = TaskStatus.ROLLING_BACK
    context.backup = {"backup_id": "backup-1"}
    context.patch = {"files": ["example.py"]}
    return context


def test_rollback_uses_fresh_cleanup_token_after_cancellation_and_timeout(tmp_path):
    context = _expired_cancelled_context(tmp_path)
    original_token = context.cancellation_token
    patch_service = _SuccessfulPatchRollback()

    result = task_service._rollback(
        context,
        backup_service=_UnusedBackupService(),
        patch_service=patch_service,
    )

    assert result["success"] is True
    assert context.rollback_attempted is True
    assert context.rollback_succeeded is True
    assert patch_service.seen_token is not original_token
    assert patch_service.seen_token.is_cancelled() is False
    assert patch_service.seen_timeout == 7.5
    assert context.cancellation_token is original_token
    assert context.cancellation_token.is_cancelled() is True


def test_non_rollback_stage_still_honors_cancelled_token(tmp_path):
    context = _expired_cancelled_context(tmp_path)
    context.status = TaskStatus.BUILDING

    try:
        task_service._remaining_stage_timeout(context, 5.0)
    except task_service.TaskCancellationError:
        pass
    else:
        raise AssertionError("normal stages must remain cancellation-aware")
