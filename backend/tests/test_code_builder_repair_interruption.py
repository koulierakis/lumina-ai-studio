from __future__ import annotations

import pytest

from backend.code_builder import autonomous_repair
from backend.code_builder.task_service import (
    TaskBuildError,
    TaskCancellationError,
    TaskCancellationToken,
    TaskExecutionContext,
    TaskRequest,
    TaskServiceConfiguration,
    TaskTimeoutError,
)


class _InterruptingService:
    def __init__(self, interruption: BaseException) -> None:
        self.interruption = interruption
        self.analysis_calls = 0

    def _record_event(self, *_args, **_kwargs):
        return None

    def _execute_analysis_stage(self, *_args, **_kwargs):
        self.analysis_calls += 1
        raise self.interruption

    def _execute_planning_stage(self, *_args, **_kwargs):
        raise AssertionError("planning must not run after interruption")

    def _execute_patch_generation_stage(self, *_args, **_kwargs):
        raise AssertionError("patch generation must not run after interruption")

    def _execute_patch_validation_stage(self, *_args, **_kwargs):
        raise AssertionError("patch validation must not run after interruption")

    def _execute_patch_application_stage(self, *_args, **_kwargs):
        raise AssertionError("patch application must not run after interruption")


def _context(tmp_path) -> TaskExecutionContext:
    request = TaskRequest(
        task_id="repair-interruption",
        instruction="Repair the approved target.",
        metadata={"max_automatic_repair_attempts": 3},
    )
    context = TaskExecutionContext(
        request=request,
        configuration=TaskServiceConfiguration(repository_root=tmp_path),
        cancellation_token=TaskCancellationToken(task_id=request.task_id),
    )
    context.plan = {"files": [{"path": "target.py"}]}
    return context


@pytest.mark.parametrize(
    "interruption",
    [
        TaskCancellationError("cancel during repair", task_id="repair-interruption"),
        TaskTimeoutError(
            "timeout during repair",
            timeout_seconds=1.0,
            task_id="repair-interruption",
        ),
    ],
)
def test_repair_does_not_swallow_terminal_interruption(
    tmp_path,
    monkeypatch,
    interruption,
):
    context = _context(tmp_path)
    original_request = context.request
    service = _InterruptingService(interruption)
    original_build_calls = 0

    def fail_initial_build(*_args, **_kwargs):
        nonlocal original_build_calls
        original_build_calls += 1
        raise TaskBuildError("initial validation failure")

    monkeypatch.setattr(autonomous_repair, "_ORIGINAL_BUILD_STAGE", fail_initial_build)

    with pytest.raises(type(interruption)) as caught:
        autonomous_repair._execute_build_stage_with_repair(
            service,
            context,
            object(),
        )

    assert str(caught.value) == str(interruption)
    assert original_build_calls == 1
    assert service.analysis_calls == 1
    assert context.metadata["automatic_repair_attempts"] == 1
    assert context.request is original_request
