from pathlib import Path

import pytest
from code_builder_v2.autonomous import AutonomousBuildResult
from code_builder_v2.models import ChangePlan, PlannedChange, TaskRequest, TaskStatus
from code_builder_v2.repository import Repository
from code_builder_v2.security import UnsafePathError
from code_builder_v2.service import CodeBuilderService


class FakePlanner:
    def create_plan(self, request: TaskRequest) -> ChangePlan:
        return ChangePlan(
            summary="Create requested file",
            changes=[PlannedChange(path="example.py", operation="create", reason=request.prompt)],
            validation_commands=["python -m pytest -q"],
        )


def test_task_reaches_approval_after_planning():
    service = CodeBuilderService(planner=FakePlanner())
    task = service.create_task(TaskRequest(prompt="Create an example module"))
    planned = service.plan_task(task.id)

    assert planned.status is TaskStatus.awaiting_approval
    assert planned.plan is not None
    assert planned.plan.changes[0].path == "example.py"


def test_cancel_task():
    service = CodeBuilderService(planner=FakePlanner())
    task = service.create_task(TaskRequest(prompt="Create an example module"))

    cancelled = service.cancel_task(task.id)

    assert cancelled.status is TaskStatus.cancelled


def test_repository_rejects_path_escape(tmp_path: Path):
    repo = Repository(tmp_path)

    with pytest.raises(UnsafePathError):
        repo.write_text("../outside.txt", "blocked")


def test_repository_round_trip(tmp_path: Path):
    repo = Repository(tmp_path)
    repo.write_text("src/example.py", "answer = 42\n")

    assert repo.read_text("src/example.py") == "answer = 42\n"


class FakeAutonomousLoop:
    def execute(self, *, repository_root, instruction, progress_persist=None):
        assert Path(repository_root).is_dir()
        assert instruction == "Create an autonomous example"
        return AutonomousBuildResult(
            successful=True,
            attempts=2,
            changed_paths=("example.py",),
            events=(),
            backup_id="verified-backup",
        )


class PipelinePlaceholder:
    applier = None


def test_service_executes_autonomous_task_and_records_attempts(tmp_path: Path):
    service = CodeBuilderService(
        planner=FakePlanner(),
        pipeline=PipelinePlaceholder(),
        autonomous_factory=lambda task, progress_persist=None: FakeAutonomousLoop(),
        repository_root=tmp_path,
    )
    task = service.create_task(
        TaskRequest(
            prompt="Create an autonomous example",
            autonomous=True,
            max_attempts=3,
        )
    )

    completed = service.execute_task(task.id)

    assert completed.status is TaskStatus.completed
    assert completed.execution is not None
    assert completed.execution.autonomous is True
    assert completed.execution.attempts == 2
    assert completed.execution.backup_id == "verified-backup"


def test_autonomous_factory_accepts_progress_persist(tmp_path: Path):
    """
    Regression test for: <lambda>() got an unexpected keyword argument 'progress_persist'

    This test ensures that the autonomous_factory callback accepts the progress_persist
    keyword argument. The production code in server.py uses a lambda that must accept
    this parameter when called from CodeBuilderService.execute_task().
    """
    from code_builder_v2.service import CodeBuilderService

    # This lambda mimics the OLD server.py lambda that only accepts `task`
    # This should fail with TypeError: <lambda>() got an unexpected keyword argument 'progress_persist'
    def old_style_factory(task):
        return FakeAutonomousLoop()

    service = CodeBuilderService(
        planner=FakePlanner(),
        pipeline=PipelinePlaceholder(),
        autonomous_factory=old_style_factory,
        repository_root=tmp_path,
    )
    task = service.create_task(
        TaskRequest(
            prompt="Create an autonomous example",
            autonomous=True,
            max_attempts=3,
        )
    )

    # This should raise TypeError because the factory doesn't accept progress_persist
    # The exception is caught in execute_task and stored in task.error
    completed = service.execute_task(task.id)

    # The task should fail with the TypeError message
    assert completed.status is TaskStatus.failed
    assert "unexpected keyword argument 'progress_persist'" in completed.error
