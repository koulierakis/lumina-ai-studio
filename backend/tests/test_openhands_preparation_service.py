from code_builder.openhands_adapter import OpenHandsRunResult
from code_builder.openhands_execution_service import OpenHandsExecutionResult, OpenHandsFileChange
from code_builder.openhands_preparation_service import OpenHandsPreparationService


class FakeRegistry:
    def execute(self, *, engine, repository_root, instruction):
        assert engine == "openhands"
        assert repository_root == "repo"
        assert instruction == "fix it"
        return OpenHandsExecutionResult(
            run=OpenHandsRunResult(("openhands",), 0, (), "", ""),
            changes=(
                OpenHandsFileChange(
                    path="new.txt",
                    change_type="created",
                    diff="--- a/new.txt\n+++ b/new.txt\n",
                    content="hello\n",
                ),
            ),
        )


def test_preparation_payload_matches_existing_approval_contract():
    payload = OpenHandsPreparationService(FakeRegistry()).prepare(
        task_id="task-1",
        repository_root="repo",
        instruction="fix it",
    )

    assert payload["status"] == "dry_run"
    assert payload["success"] is True
    assert payload["engine"] == "openhands"
    assert payload["source_repository_unchanged"] is True
    assert payload["requires_approval"] is True
    assert payload["changed_paths"] == ["new.txt"]
    assert payload["plan"]["files"] == ["new.txt"]
    assert payload["patch"]["operations"][0]["operation"] == "create"
    assert payload["patch"]["operations"][0]["path"] == "new.txt"
    assert payload["patch"]["operations"][0]["content"] == "hello\n"
