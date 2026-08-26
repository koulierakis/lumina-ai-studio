"""Bounded automatic repair and interruption-safe rollback for Code Builder.

This module installs narrow wrappers around TaskService.  The build wrapper
feeds mandatory validation failures back into the existing
analysis/planning/patch pipeline, applies a targeted corrective patch, and
re-runs validation.  Repair is bounded, cancellation-aware, and restricted to
the paths in the already-approved implementation plan.

The rollback wrapper isolates cleanup from the interruption that caused the
failure.  Once task changes exist, cancellation or expiry of the main task
must not prevent the bounded rollback stage from restoring the repository.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from . import task_service as _task_service
from .task_service import (
    TaskBuildError,
    TaskCancellationError,
    TaskCancellationToken,
    TaskEventLevel,
    TaskExecutionContext,
    TaskService,
    TaskServiceError,
    TaskStage,
    TaskStatus,
    TaskTimeoutError,
    _EventRecorder,
    _extract_paths,
)

DEFAULT_MAX_AUTOMATIC_REPAIR_ATTEMPTS: Final[int] = 2
MAX_AUTOMATIC_REPAIR_ATTEMPTS: Final[int] = 5

_ORIGINAL_BUILD_STAGE = TaskService._execute_build_stage
_ORIGINAL_ROLLBACK = _task_service._rollback
_ORIGINAL_REMAINING_STAGE_TIMEOUT = _task_service._remaining_stage_timeout
_INSTALLED = False


def _bounded_repair_attempts(context: TaskExecutionContext) -> int:
    raw_value = context.request.metadata.get(
        "max_automatic_repair_attempts",
        DEFAULT_MAX_AUTOMATIC_REPAIR_ATTEMPTS,
    )
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_AUTOMATIC_REPAIR_ATTEMPTS
    return max(0, min(value, MAX_AUTOMATIC_REPAIR_ATTEMPTS))


def _repair_context_text(
    existing: str | None,
    *,
    failure: BaseException,
    attempt: int,
) -> str:
    prefix = (existing or "").rstrip()
    diagnostic = str(failure).strip() or failure.__class__.__name__
    repair_block = (
        "AUTOMATIC REPAIR CONTEXT\n"
        "========================\n"
        f"Repair attempt: {attempt}\n"
        "The previous implementation was applied but mandatory validation "
        "failed. Diagnose the failure and produce the smallest corrective "
        "change that fixes the real error without expanding scope.\n"
        f"Validation failure:\n{diagnostic}"
    )
    return f"{prefix}\n\n{repair_block}" if prefix else repair_block


def _repair_request(context: TaskExecutionContext, failure: BaseException, attempt: int):
    metadata = dict(context.request.metadata)
    # A repair must be freshly generated from the failure, not replay the
    # prepared patch that already failed validation.
    metadata.pop("patch_operations", None)
    metadata.pop("execution_patch_operations", None)
    metadata.pop("approved_patch_operations", None)
    metadata.pop("approved_preparation_plan", None)
    metadata.update(
        {
            "automatic_repair": True,
            "automatic_repair_attempt": attempt,
            "automatic_repair_failure": str(failure),
        }
    )
    return context.request.model_copy(
        update={
            "context": _repair_context_text(
                context.request.context,
                failure=failure,
                attempt=attempt,
            ),
            "metadata": metadata,
        }
    )


def _approved_paths(context: TaskExecutionContext) -> frozenset[str]:
    raw = context.metadata.get("automatic_repair_approved_paths")
    if raw is None:
        raw = _extract_paths(context.plan)
        context.metadata["automatic_repair_approved_paths"] = tuple(raw)
    return frozenset(str(path) for path in raw or ())


def _assert_repair_scope(
    context: TaskExecutionContext,
    approved_paths: frozenset[str],
) -> None:
    if not approved_paths:
        return
    repair_paths = frozenset(str(path) for path in _extract_paths(context.plan))
    unexpected = sorted(repair_paths - approved_paths)
    if unexpected:
        raise TaskBuildError(
            "Automatic repair attempted to expand the approved file scope: "
            + ", ".join(unexpected)
        )


def _record(
    service: TaskService,
    context: TaskExecutionContext,
    recorder: _EventRecorder,
    *,
    level: TaskEventLevel,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    service._record_event(
        context,
        recorder,
        stage=TaskStage.BUILD,
        status=TaskStatus.BUILDING,
        level=level,
        message=message,
        details=details,
    )


def _execute_build_stage_with_repair(
    self: TaskService,
    context: TaskExecutionContext,
    recorder: _EventRecorder,
) -> None:
    try:
        _ORIGINAL_BUILD_STAGE(self, context, recorder)
        return
    except TaskBuildError as initial_failure:
        failure: BaseException = initial_failure

    maximum_attempts = _bounded_repair_attempts(context)
    if maximum_attempts <= 0 or context.request.dry_run:
        raise failure

    approved_paths = _approved_paths(context)
    original_request = context.request
    context.metadata["automatic_repair_attempts"] = 0

    for attempt in range(1, maximum_attempts + 1):
        context.raise_if_interrupted()
        context.metadata["automatic_repair_attempts"] = attempt

        _record(
            self,
            context,
            recorder,
            level=TaskEventLevel.WARNING,
            message="Automatic repair attempt started after validation failure.",
            details={
                "repair_attempt": attempt,
                "maximum_repair_attempts": maximum_attempts,
                "failure_type": failure.__class__.__name__,
                "failure_message": str(failure),
            },
        )

        try:
            context.request = _repair_request(
                context,
                failure,
                attempt,
            )
            # Re-analyse the repository in its current post-failure state, then
            # generate a corrective plan and patch through the existing safe
            # services.  Backup is intentionally not repeated: the original
            # task backup remains the single rollback point.
            self._execute_analysis_stage(context, recorder)
            self._execute_planning_stage(context, recorder)
            _assert_repair_scope(context, approved_paths)
            self._execute_patch_generation_stage(context, recorder)
            self._execute_patch_validation_stage(context, recorder)
            self._execute_patch_application_stage(context, recorder)
            _ORIGINAL_BUILD_STAGE(self, context, recorder)
        except (TaskCancellationError, TaskTimeoutError):
            # Interruption is a terminal control signal, not a repair failure.
            # Never consume it as another repair attempt.
            context.request = original_request
            raise
        except TaskServiceError as repair_failure:
            failure = repair_failure
            _record(
                self,
                context,
                recorder,
                level=TaskEventLevel.WARNING,
                message="Automatic repair attempt did not pass validation.",
                details={
                    "repair_attempt": attempt,
                    "failure_type": repair_failure.__class__.__name__,
                    "failure_message": str(repair_failure),
                },
            )
            if attempt >= maximum_attempts:
                context.request = original_request
                raise TaskBuildError(
                    "Automatic repair exhausted after "
                    f"{maximum_attempts} attempt(s). Last failure: {repair_failure}"
                ) from repair_failure
            continue
        except BaseException:
            context.request = original_request
            raise
        else:
            context.request = original_request
            context.metadata["automatic_repair_succeeded"] = True
            _record(
                self,
                context,
                recorder,
                level=TaskEventLevel.INFO,
                message="Automatic repair completed and validation passed.",
                details={
                    "repair_attempt": attempt,
                    "maximum_repair_attempts": maximum_attempts,
                    "changed_paths": list(context.changed_paths),
                },
            )
            return

    context.request = original_request
    raise TaskBuildError(str(failure))


def _remaining_stage_timeout_with_cleanup(
    context: TaskExecutionContext,
    configured_timeout: float,
) -> float:
    """Give rollback its own bounded cleanup budget after interruption."""
    if context.status is TaskStatus.ROLLING_BACK:
        return configured_timeout
    return _ORIGINAL_REMAINING_STAGE_TIMEOUT(context, configured_timeout)


def _rollback_during_interruption(
    context: TaskExecutionContext,
    *,
    backup_service: Any,
    patch_service: Any,
) -> Any:
    """Run rollback with a fresh token while preserving the task token.

    The main task token may already be cancelled and the overall task deadline
    may already be exhausted.  Those are reasons to stop normal work, not
    reasons to skip repository recovery.  Rollback remains bounded by the
    configured rollback timeout passed to the underlying rollback service.
    """
    original_token = context.cancellation_token
    cleanup_token = TaskCancellationToken(task_id=context.request.task_id)
    context.cancellation_token = cleanup_token
    try:
        return _ORIGINAL_ROLLBACK(
            context,
            backup_service=backup_service,
            patch_service=patch_service,
        )
    finally:
        context.cancellation_token = original_token


def install_automatic_repair() -> None:
    """Install the repair and rollback wrappers exactly once per process."""
    global _INSTALLED
    if _INSTALLED:
        return
    TaskService._execute_build_stage = _execute_build_stage_with_repair
    _task_service._remaining_stage_timeout = _remaining_stage_timeout_with_cleanup
    _task_service._rollback = _rollback_during_interruption
    _INSTALLED = True


def automatic_repair_installed() -> bool:
    return bool(
        _INSTALLED
        and TaskService._execute_build_stage is _execute_build_stage_with_repair
        and _task_service._remaining_stage_timeout is _remaining_stage_timeout_with_cleanup
        and _task_service._rollback is _rollback_during_interruption
    )
