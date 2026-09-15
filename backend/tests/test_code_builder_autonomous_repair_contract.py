from __future__ import annotations

from pathlib import Path

import pytest

from backend.code_builder import autonomous_repair
from backend.code_builder.task_service import (
    TaskBuildError,
    TaskCancellationToken,
    TaskExecutionContext,
    TaskRequest,
    TaskService,
    TaskServiceConfiguration,
)


class _Recorder:
    pass


class _DummyService:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def _record_event(self, context, recorder, *, message, details=None, **kwargs):
        self.events.append((message, dict(details or {})))

    def _execute_analysis_stage(self, context, recorder):
        context.analysis = {"ok": True}

    def _execute_planning_stage(self, context, recorder):
        context.plan = {"paths": ["target.py"]}

    def _execute_patch_generation_stage(self, context, recorder):
        context.patch = {"paths": ["target.py"]}

    def _execute_patch_validation_stage(self, context, recorder):
        context.patch_validation = {"success": True}

    def _execute_patch_application_stage(self, context, recorder):
        context.patch_application = {"success": True, "paths": ["target.py"]}
        context.changed_paths = ("target.py",)


def _context(tmp_path: Path, *, attempts: int = 2) -> TaskExecutionContext:
    request = TaskRequest(
        task_id="repair-contract",
        instruction="Repair the controlled target",
        metadata={"max_automatic_repair_attempts": attempts},
    )
    configuration = TaskServiceConfiguration(
        repository_root=tmp_path,
        use_default_build_sequence=False,
    )
    context = TaskExecutionContext(
        request=request,
        configuration=configuration,
        cancellation_token=TaskCancellationToken(task_id=request.task_id),
    )
    context.plan = {"paths": ["target.py"]}
    return context


def test_package_installs_automatic_repair_once():
    assert autonomous_repair.automatic_repair_installed()
    installed = TaskService._execute_build_stage
    autonomous_repair.install_automatic_repair()
    assert TaskService._execute_build_stage is installed


def test_automatic_repair_retries_failed_validation_and_then_succeeds(tmp_path, monkeypatch):
    calls = {"count": 0}

    def controlled_build(service, context, recorder):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TaskBuildError("pytest: controlled failure")
        return None

    monkeypatch.setattr(autonomous_repair, "_ORIGINAL_BUILD_STAGE", controlled_build)

    context = _context(tmp_path)
    service = _DummyService()

    autonomous_repair._execute_build_stage_with_repair(
        service,
        context,
        _Recorder(),
    )

    assert calls["count"] == 2
    assert context.metadata["automatic_repair_attempts"] == 1
    assert context.metadata["automatic_repair_succeeded"] is True
    assert context.request.instruction == "Repair the controlled target"
    assert any("Automatic repair attempt started" in message for message, _ in service.events)
    assert any("validation passed" in message for message, _ in service.events)


def test_automatic_repair_stops_at_retry_limit(tmp_path, monkeypatch):
    calls = {"count": 0}

    def always_failing_build(service, context, recorder):
        calls["count"] += 1
        raise TaskBuildError(f"failure-{calls['count']}")

    monkeypatch.setattr(autonomous_repair, "_ORIGINAL_BUILD_STAGE", always_failing_build)

    context = _context(tmp_path, attempts=2)
    service = _DummyService()

    with pytest.raises(TaskBuildError, match="exhausted after 2 attempt"):
        autonomous_repair._execute_build_stage_with_repair(
            service,
            context,
            _Recorder(),
        )

    # initial build + two bounded repair validations
    assert calls["count"] == 3
    assert context.metadata["automatic_repair_attempts"] == 2


def test_automatic_repair_rejects_scope_expansion(tmp_path, monkeypatch):
    def failing_build(service, context, recorder):
        raise TaskBuildError("controlled validation failure")

    monkeypatch.setattr(autonomous_repair, "_ORIGINAL_BUILD_STAGE", failing_build)

    context = _context(tmp_path, attempts=1)

    class _ScopeExpandingService(_DummyService):
        def _execute_planning_stage(self, context, recorder):
            context.plan = {"paths": ["target.py", "unapproved.py"]}

    with pytest.raises(TaskBuildError, match="exhausted after 1 attempt") as exc_info:
        autonomous_repair._execute_build_stage_with_repair(
            _ScopeExpandingService(),
            context,
            _Recorder(),
        )

    assert "expand the approved file scope" in str(exc_info.value.__cause__)
