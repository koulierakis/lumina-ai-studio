import pytest

from code_builder.openhands_adapter import OpenHandsRunResult
from code_builder.openhands_execution_service import OpenHandsExecutionResult, OpenHandsFileChange
from code_builder.openhands_preparation_service import OpenHandsPreparationService, OpenHandsScopeError


class FakeRegistry:
    def __init__(self, changes=None):
        self.changes = changes or (
            OpenHandsFileChange(
                path="new.txt",
                change_type="created",
                diff="--- a/new.txt\n+++ b/new.txt\n",
                content="hello\n",
            ),
        )

    def execute(self, *, engine, repository_root, instruction):
        assert engine == "openhands"
        assert repository_root == "repo"
        assert "USER INSTRUCTION:\nfix it" in instruction
        assert "LUMINA SAFETY SCOPE:" in instruction
        return OpenHandsExecutionResult(
            run=OpenHandsRunResult(("openhands",), 0, (), "", ""),
            changes=self.changes,
        )


def test_preparation_payload_matches_existing_approval_contract():
    payload = OpenHandsPreparationService(FakeRegistry()).prepare(
        task_id="task-1",
        repository_root="repo",
        instruction="fix it",
        target_paths=("new.txt",),
        allow_file_creation=True,
    )

    assert payload["status"] == "dry_run"
    assert payload["success"] is True
    assert payload["engine"] == "openhands"
    assert payload["source_repository_unchanged"] is True
    assert payload["requires_approval"] is True
    assert payload["changed_paths"] == ["new.txt"]
    assert payload["plan"]["files"] == ["new.txt"]
    assert payload["plan"]["target_paths"] == ["new.txt"]
    assert payload["patch"]["operations"][0]["operation"] == "create"
    assert payload["patch"]["operations"][0]["path"] == "new.txt"
    assert payload["patch"]["operations"][0]["content"] == "hello\n"


def test_out_of_scope_change_is_rejected():
    registry = FakeRegistry(
        changes=(
            OpenHandsFileChange(
                path="other.txt",
                change_type="created",
                diff="--- a/other.txt\n+++ b/other.txt\n",
                content="bad\n",
            ),
        )
    )
    with pytest.raises(OpenHandsScopeError, match="out-of-scope"):
        OpenHandsPreparationService(registry).prepare(
            task_id="task-2",
            repository_root="repo",
            instruction="fix it",
            target_paths=("allowed.txt",),
            allow_file_creation=True,
        )


def test_excluded_path_change_is_rejected():
    with pytest.raises(OpenHandsScopeError, match="excluded path"):
        OpenHandsPreparationService(FakeRegistry()).prepare(
            task_id="task-3",
            repository_root="repo",
            instruction="fix it",
            excluded_paths=("new.txt",),
            allow_file_creation=True,
        )


def test_creation_policy_is_enforced():
    with pytest.raises(OpenHandsScopeError, match="creation is disabled"):
        OpenHandsPreparationService(FakeRegistry()).prepare(
            task_id="task-4",
            repository_root="repo",
            instruction="fix it",
            target_paths=("new.txt",),
            allow_file_creation=False,
        )
