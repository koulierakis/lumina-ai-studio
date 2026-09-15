from __future__ import annotations

from code_builder.task_service import (
    TaskCancellationToken,
    TaskExecutionContext,
    TaskRequest,
    TaskServiceConfiguration,
    _resolve_build_commands,
)


def _context(tmp_path):
    (tmp_path / "backend").mkdir(exist_ok=True)
    (tmp_path / "frontend").mkdir(exist_ok=True)
    request = TaskRequest(instruction="Validate default build selection")
    configuration = TaskServiceConfiguration(
        repository_root=tmp_path,
        include_ruff=False,
        include_mypy=False,
        include_frontend_tests=False,
        include_frontend_build=False,
    )
    return TaskExecutionContext(
        request=request,
        configuration=configuration,
        cancellation_token=TaskCancellationToken(task_id=request.task_id),
    )


def test_javascript_project_does_not_run_typescript_validation(tmp_path) -> None:
    context = _context(tmp_path)
    commands = _resolve_build_commands(context)
    command_ids = {command.command_id for command in commands}
    assert "frontend-typescript" not in command_ids


def test_typescript_project_keeps_typescript_validation(tmp_path) -> None:
    context = _context(tmp_path)
    (tmp_path / "frontend" / "tsconfig.json").write_text("{}", encoding="utf-8")
    commands = _resolve_build_commands(context)
    command_ids = {command.command_id for command in commands}
    assert "frontend-typescript" in command_ids
