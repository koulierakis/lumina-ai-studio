from pathlib import Path

from code_builder_v2.applier import AtomicChangeApplier, ProposedFileChange
from code_builder_v2.backup import BackupService
from code_builder_v2.executor import CommandResult
from code_builder_v2.models import ChangePlan, PlannedChange, TaskRequest, TaskStatus
from code_builder_v2.pipeline import ExecutionPipeline
from code_builder_v2.repository import Repository
from code_builder_v2.service import CodeBuilderService
from code_builder_v2.validation import ValidationRunner


class Planner:
    def create_plan(self, request):
        return ChangePlan(summary="create", changes=[PlannedChange(path="a.py", operation="create", reason="requested")], validation_commands=["pytest -q"])


class Generator:
    def generate(self, request, plan, file_context):
        return [ProposedFileChange("a.py", "create", "x = 1\n")]


class Executor:
    def run(self, command, timeout_seconds):
        return CommandResult(command, 0, "ok", "")


def test_service_executes_approved_plan(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    repository = Repository(root)
    pipeline = ExecutionPipeline(repository, Generator(), AtomicChangeApplier(repository, BackupService(root, tmp_path / "backups")), ValidationRunner(Executor()))
    service = CodeBuilderService(Planner(), pipeline=pipeline)

    task = service.create_task(TaskRequest(prompt="create a.py"))
    assert task.status is TaskStatus.awaiting_approval

    completed = service.execute_task(task.id)
    assert completed.status is TaskStatus.completed
    assert completed.execution is not None
    assert completed.execution.changed_paths == ["a.py"]
    assert (root / "a.py").exists()


def test_auto_apply_runs_pipeline(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    repository = Repository(root)
    pipeline = ExecutionPipeline(repository, Generator(), AtomicChangeApplier(repository, BackupService(root, tmp_path / "backups")), ValidationRunner(Executor()))
    service = CodeBuilderService(Planner(), pipeline=pipeline)

    task = service.create_task(TaskRequest(prompt="create a.py", auto_apply=True))
    assert task.status is TaskStatus.completed
