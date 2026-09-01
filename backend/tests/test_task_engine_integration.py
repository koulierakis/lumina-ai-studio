from pathlib import Path

from code_builder.task_engine_integration import (
    _approved_openhands_plan,
    _is_openhands_preparation,
    execute_openhands_preparation,
)
from code_builder.task_service import TaskRequest, TaskServiceConfiguration


class FakeTaskService:
    def __init__(self, root: Path) -> None:
        self.configuration = TaskServiceConfiguration(repository_root=root)


class FakePreparationService:
    def prepare(self, *, task_id, repository_root, instruction):
        assert Path(repository_root).is_dir()
        return {
            "task_id": task_id,
            "engine": "openhands",
            "changed_paths": ["demo.txt"],
            "plan": {"files": ["demo.txt"], "engine": "openhands"},
            "patch": {
                "operations": [
                    {
                        "operation": "create",
                        "path": "demo.txt",
                        "content": "hello\n",
                    }
                ]
            },
            "openhands_review": {"changed_files": 1},
        }


def test_only_openhands_preparation_is_intercepted():
    assert _is_openhands_preparation(
        TaskRequest(
            instruction="fix",
            metadata={"code_builder_preparation": True, "coding_engine": "openhands"},
        )
    )
    assert not _is_openhands_preparation(
        TaskRequest(
            instruction="fix",
            metadata={"code_builder_preparation": True, "coding_engine": "native"},
        )
    )
    assert not _is_openhands_preparation(
        TaskRequest(instruction="fix", metadata={"coding_engine": "openhands"})
    )


def test_approved_openhands_plan_is_reused_exactly():
    approved = {"files": ["demo.txt"], "engine": "openhands", "review_only": True}
    request = TaskRequest(
        instruction="fix",
        metadata={
            "coding_engine": "openhands",
            "approved_preparation_plan": approved,
        },
    )
    assert _approved_openhands_plan(request) is approved


def test_native_task_never_reuses_openhands_plan_metadata():
    request = TaskRequest(
        instruction="fix",
        metadata={
            "coding_engine": "native",
            "approved_preparation_plan": {"files": ["wrong.txt"]},
        },
    )
    assert _approved_openhands_plan(request) is None


def test_openhands_preparation_returns_task_execution_result_without_source_changes(tmp_path: Path):
    original = tmp_path / "original.txt"
    original.write_text("unchanged\n", encoding="utf-8")
    request = TaskRequest(
        task_id="openhands-prep-1",
        instruction="create demo",
        dry_run=True,
        metadata={"code_builder_preparation": True, "coding_engine": "openhands"},
    )

    result = execute_openhands_preparation(
        FakeTaskService(tmp_path),
        request,
        return_domain_model=False,
        preparation_service=FakePreparationService(),
    )

    assert result.status.value == "dry_run"
    assert result.changed_paths == ("demo.txt",)
    assert result.metadata["coding_engine"] == "openhands"
    assert result.metadata["source_repository_unchanged"] is True
    assert result.metadata["requires_approval"] is True
    assert result.patch["operations"][0]["path"] == "demo.txt"
    assert original.read_text(encoding="utf-8") == "unchanged\n"
    assert not (tmp_path / "demo.txt").exists()
