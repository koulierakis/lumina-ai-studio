"""Route OpenHands preparation tasks through the existing TaskService boundary.

Only the pre-approval dry-run stage is intercepted. Native execution, approval,
backup, patch application, build validation, persistence, and rollback remain
owned by the existing LUMINA Code Builder lifecycle.
"""
from __future__ import annotations

import time
from typing import Any

from .engine_registry import NATIVE_ENGINE, OPENHANDS_ENGINE
from .openhands_preparation_service import OpenHandsPreparationService
from .task_service import (
    TaskCancellationToken,
    TaskEvent,
    TaskEventCallback,
    TaskEventLevel,
    TaskExecutionResult,
    TaskRequest,
    TaskService,
    TaskStage,
    TaskStatus,
    _task_request_from_domain_model,
    _task_result_to_domain_model,
)

_INSTALLED = False
_ORIGINAL_EXECUTE = TaskService.execute


def _requested_engine(request: TaskRequest) -> str:
    value = request.metadata.get("coding_engine", NATIVE_ENGINE)
    return str(value).strip().lower() or NATIVE_ENGINE


def _is_openhands_preparation(request: TaskRequest) -> bool:
    return bool(request.metadata.get("code_builder_preparation")) and _requested_engine(request) == OPENHANDS_ENGINE


def _emit(
    callback: TaskEventCallback | None,
    *,
    sequence: int,
    request: TaskRequest,
    status: TaskStatus,
    stage: TaskStage,
    message: str,
    details: dict[str, Any] | None = None,
) -> TaskEvent:
    event = TaskEvent(
        sequence=sequence,
        task_id=request.task_id,
        timestamp_epoch=time.time(),
        stage=stage,
        status=status,
        level=TaskEventLevel.INFO,
        message=message,
        details=details or {},
    )
    if callback is not None:
        callback(event)
    return event


def execute_openhands_preparation(
    task_service: TaskService,
    request: TaskRequest,
    *,
    event_callback: TaskEventCallback | None = None,
    cancellation_token: TaskCancellationToken | None = None,
    return_domain_model: bool = True,
    preparation_service: OpenHandsPreparationService | None = None,
) -> Any:
    """Run OpenHands only for the approval preparation stage."""
    token = cancellation_token or TaskCancellationToken(task_id=request.task_id)
    if token.task_id != request.task_id:
        raise ValueError("Cancellation token task_id does not match the task request task_id.")
    token.raise_if_cancelled()

    started = time.time()
    events: list[TaskEvent] = []
    events.append(
        _emit(
            event_callback,
            sequence=1,
            request=request,
            status=TaskStatus.ANALYZING,
            stage=TaskStage.ANALYSIS,
            message="OpenHands safe preparation started.",
            details={"coding_engine": OPENHANDS_ENGINE, "safe_copy": True},
        )
    )

    service = preparation_service or OpenHandsPreparationService()
    prepared = service.prepare(
        task_id=request.task_id,
        repository_root=task_service.configuration.repository_root,
        instruction=request.instruction,
    )
    token.raise_if_cancelled()

    changed_paths = tuple(str(path) for path in prepared.get("changed_paths", ()))
    finished = time.time()
    events.append(
        _emit(
            event_callback,
            sequence=2,
            request=request,
            status=TaskStatus.DRY_RUN,
            stage=TaskStage.COMPLETION,
            message="OpenHands safe preparation completed; proposal is awaiting approval.",
            details={
                "coding_engine": OPENHANDS_ENGINE,
                "changed_paths": list(changed_paths),
                "source_repository_unchanged": True,
            },
        )
    )

    result = TaskExecutionResult(
        task_id=request.task_id,
        status=TaskStatus.DRY_RUN,
        instruction=request.instruction,
        repository_root=str(task_service.configuration.repository_root),
        started_at_epoch=started,
        finished_at_epoch=finished,
        duration_seconds=max(0.0, finished - started),
        analysis={
            "engine": OPENHANDS_ENGINE,
            "safe_copy": True,
            "source_repository_unchanged": True,
        },
        plan=prepared.get("plan"),
        patch=prepared.get("patch"),
        patch_validation={"success": True, "review_only": True},
        patch_application={"success": True, "dry_run": True, "changed_paths": list(changed_paths)},
        changed_paths=changed_paths,
        events=tuple(events),
        dry_run=True,
        metadata={
            **dict(request.metadata),
            "coding_engine": OPENHANDS_ENGINE,
            "openhands_review": prepared.get("openhands_review"),
            "source_repository_unchanged": True,
            "requires_approval": True,
            "runtime_validated_for_task": True,
        },
    )
    if not return_domain_model:
        return result
    return _task_result_to_domain_model(result)


def install_task_engine_integration() -> None:
    """Install one idempotent TaskService.execute wrapper."""
    global _INSTALLED
    if _INSTALLED:
        return

    original = TaskService.execute

    def execute(
        self: TaskService,
        task: TaskRequest | Any,
        *,
        event_callback: TaskEventCallback | None = None,
        cancellation_token: TaskCancellationToken | None = None,
        return_domain_model: bool = True,
    ) -> Any:
        request = _task_request_from_domain_model(task)
        if not _is_openhands_preparation(request):
            return original(
                self,
                request,
                event_callback=event_callback,
                cancellation_token=cancellation_token,
                return_domain_model=return_domain_model,
            )
        return execute_openhands_preparation(
            self,
            request,
            event_callback=event_callback,
            cancellation_token=cancellation_token,
            return_domain_model=return_domain_model,
        )

    TaskService.execute = execute
    _INSTALLED = True
