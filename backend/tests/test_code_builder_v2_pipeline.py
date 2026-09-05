from pathlib import Path

import pytest

from code_builder_v2.applier import AtomicChangeApplier, ProposedFileChange
from code_builder_v2.backup import BackupService
from code_builder_v2.executor import CommandResult
from code_builder_v2.models import ChangePlan, PlannedChange, TaskRequest
from code_builder_v2.pipeline import ExecutionPipeline, PipelineError
from code_builder_v2.repository import Repository
from code_builder_v2.validation import ValidationRunner


class FakeGenerator:
    def __init__(self, changes):
        self.changes = changes

    def generate(self, request, plan, file_context):
        return self.changes


class FakeExecutor:
    def __init__(self, returncode=0):
        self.returncode = returncode

    def run(self, command, timeout_seconds):
        return CommandResult(command, self.returncode, "ok" if self.returncode == 0 else "", "boom" if self.returncode else "")


def make_pipeline(tmp_path: Path, changes, returncode=0):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repository = Repository(repo_root)
    backup = BackupService(repo_root, tmp_path / "backups")
    applier = AtomicChangeApplier(repository, backup)
    return repo_root, ExecutionPipeline(repository, FakeGenerator(changes), applier, ValidationRunner(FakeExecutor(returncode)))


def test_pipeline_applies_complete_transaction_and_validates(tmp_path: Path):
    changes = [ProposedFileChange("hello.py", "create", "VALUE = 1\n")]
    repo_root, pipeline = make_pipeline(tmp_path, changes)
    plan = ChangePlan(summary="create", changes=[PlannedChange(path="hello.py", operation="create", reason="test")], validation_commands=["python -m pytest -q"])

    result = pipeline.execute(TaskRequest(prompt="create hello.py"), plan)

    assert (repo_root / "hello.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert result.changed_paths == ("hello.py",)


def test_pipeline_rolls_back_when_validation_fails(tmp_path: Path):
    changes = [ProposedFileChange("hello.py", "modify", "VALUE = 2\n")]
    repo_root, pipeline = make_pipeline(tmp_path, changes, returncode=1)
    (repo_root / "hello.py").write_text("VALUE = 1\n", encoding="utf-8")
    plan = ChangePlan(summary="modify", changes=[PlannedChange(path="hello.py", operation="modify", reason="test")], validation_commands=["pytest -q"])

    with pytest.raises(PipelineError):
        pipeline.execute(TaskRequest(prompt="change hello.py"), plan)

    assert (repo_root / "hello.py").read_text(encoding="utf-8") == "VALUE = 1\n"
