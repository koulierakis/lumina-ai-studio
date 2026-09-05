from pathlib import Path

import pytest

from code_builder_v2.applier import ApplyError, AtomicChangeApplier, ProposedFileChange
from code_builder_v2.backup import BackupService
from code_builder_v2.models import ChangePlan, PlannedChange
from code_builder_v2.repository import Repository
from code_builder_v2.transaction import TransactionValidationError


def make_applier(tmp_path: Path):
    repo_root = tmp_path / "repo"
    backup_root = tmp_path / "backups"
    repo_root.mkdir()
    repository = Repository(repo_root)
    return repository, AtomicChangeApplier(
        repository=repository,
        backup_service=BackupService(repo_root, backup_root),
    )


def test_atomic_apply_changes_all_planned_files(tmp_path: Path):
    repository, applier = make_applier(tmp_path)
    repository.write_text("greeting.py", "old greeting\n")
    repository.write_text("settings.json", '{"mode":"old"}\n')
    plan = ChangePlan(
        summary="Three-file change",
        changes=[
            PlannedChange(path="greeting.py", operation="modify", reason="Update greeting"),
            PlannedChange(path="settings.json", operation="modify", reason="Update settings"),
            PlannedChange(path="test_greeting.py", operation="create", reason="Add test"),
        ],
    )

    result = applier.apply(
        plan,
        [
            ProposedFileChange("greeting.py", "modify", "new greeting\n"),
            ProposedFileChange("settings.json", "modify", '{"mode":"new"}\n'),
            ProposedFileChange("test_greeting.py", "create", "def test_ok():\n    assert True\n"),
        ],
    )

    assert result.backup_id
    assert repository.read_text("greeting.py") == "new greeting\n"
    assert repository.read_text("settings.json") == '{"mode":"new"}\n'
    assert repository.exists("test_greeting.py")


def test_incomplete_generated_transaction_is_blocked_before_write(tmp_path: Path):
    repository, applier = make_applier(tmp_path)
    repository.write_text("a.py", "before-a")
    repository.write_text("b.py", "before-b")
    plan = ChangePlan(
        summary="Modify both",
        changes=[
            PlannedChange(path="a.py", operation="modify", reason="A"),
            PlannedChange(path="b.py", operation="modify", reason="B"),
        ],
    )

    with pytest.raises(TransactionValidationError):
        applier.apply(plan, [ProposedFileChange("a.py", "modify", "after-a")])

    assert repository.read_text("a.py") == "before-a"
    assert repository.read_text("b.py") == "before-b"


def test_precondition_failure_happens_before_any_write(tmp_path: Path):
    repository, applier = make_applier(tmp_path)
    repository.write_text("existing.py", "original")
    plan = ChangePlan(
        summary="Bad create",
        changes=[PlannedChange(path="existing.py", operation="create", reason="Should fail")],
    )

    with pytest.raises(ApplyError, match="already exists"):
        applier.apply(plan, [ProposedFileChange("existing.py", "create", "replacement")])

    assert repository.read_text("existing.py") == "original"


def test_manual_rollback_restores_modified_and_created_files(tmp_path: Path):
    repository, applier = make_applier(tmp_path)
    repository.write_text("existing.py", "before")
    plan = ChangePlan(
        summary="Modify and create",
        changes=[
            PlannedChange(path="existing.py", operation="modify", reason="Modify"),
            PlannedChange(path="new.py", operation="create", reason="Create"),
        ],
    )

    result = applier.apply(
        plan,
        [
            ProposedFileChange("existing.py", "modify", "after"),
            ProposedFileChange("new.py", "create", "new"),
        ],
    )
    applier.rollback(result.backup_id)

    assert repository.read_text("existing.py") == "before"
    assert not repository.exists("new.py")
