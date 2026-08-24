from __future__ import annotations

from pathlib import Path
import sys

from backend.code_builder.backup_service import BackupService
from backend.code_builder.build_service import (
    BuildCommandKind,
    BuildCommandSpec,
    BuildService,
    BuildServiceConfiguration,
)
from backend.code_builder.patch_service import PatchService
from backend.code_builder.planning_service import (
    GeneratedChangePlan,
    GeneratedFileChange,
    GeneratedPlanStep,
)
from backend.code_builder.task_service import (
    BackupPolicy,
    RollbackPolicy,
    TaskRequest,
    TaskService,
    TaskServiceConfiguration,
    TaskStatus,
)


class _RepositoryService:
    def __init__(self, root: Path) -> None:
        self.root = root

    def analyze_repository(self) -> dict[str, object]:
        return {
            "repository_root": str(self.root),
            "files": [
                path.relative_to(self.root).as_posix()
                for path in self.root.rglob("*")
                if path.is_file()
            ],
        }


class _PlanningService:
    def __init__(self, target_path: str) -> None:
        self.target_path = target_path

    def plan(self, **_: object) -> GeneratedChangePlan:
        return GeneratedChangePlan(
            title="Preserve unrelated work",
            summary="Change only the approved target.",
            objective="Prove unrelated repository work remains untouched.",
            risk_level="low",
            files=[
                GeneratedFileChange(
                    path=self.target_path,
                    operation="update",
                    summary="Update approved target only",
                    rationale="Controlled preservation test.",
                )
            ],
            steps=[
                GeneratedPlanStep(
                    order=1,
                    title="Update approved target",
                    description="Edit only the approved file.",
                    file_paths=[self.target_path],
                    validation=["Compile the approved target."],
                )
            ],
            acceptance_criteria=["Unrelated work remains byte-for-byte unchanged."],
            test_plan=["Compile the target and compare unrelated content."],
            rollback_plan=["Restore only the target from backup."],
        )


class _UnusedModelService:
    pass


def _service(root: Path, target_path: str) -> TaskService:
    return TaskService(
        repository_service=_RepositoryService(root),
        planning_service=_PlanningService(target_path),
        backup_service=BackupService(root),
        patch_service=PatchService(repository_root=root),
        build_service=BuildService(
            BuildServiceConfiguration(
                repository_root=root,
                custom_command_policy={
                    "executable_paths": frozenset({sys.executable}),
                },
            )
        ),
        ollama_service=_UnusedModelService(),
        configuration=TaskServiceConfiguration(
            repository_root=root,
            use_default_build_sequence=False,
            include_ruff=False,
            include_mypy=False,
            include_frontend_tests=False,
            include_frontend_build=False,
        ),
    )


def _compile(path: str) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id="compile-approved-target",
        kind=BuildCommandKind.PYTHON_COMPILE,
        arguments=(path,),
        timeout_seconds=30,
    )


def test_success_preserves_unrelated_existing_work(tmp_path: Path) -> None:
    target_path = "target.py"
    unrelated_path = "unrelated_work.py"
    target = tmp_path / target_path
    unrelated = tmp_path / unrelated_path
    target.write_text("VALUE = 1\n", encoding="utf-8")
    unrelated_content = "# pre-existing user work\nUNRELATED = 'keep me'\n"
    unrelated.write_text(unrelated_content, encoding="utf-8")

    request = TaskRequest(
        instruction="Update only target.py.",
        target_paths=(target_path,),
        metadata={
            "patch_operations": [
                {
                    "operation": "replace_file",
                    "path": target_path,
                    "content": "VALUE = 2\n",
                }
            ]
        },
        build_commands=(_compile(target_path),),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, target_path).execute_internal(request)

    assert result.status is TaskStatus.SUCCEEDED, result.error_message
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert unrelated.read_text(encoding="utf-8") == unrelated_content
    assert result.changed_paths == (target_path,)


def test_failed_change_rolls_back_target_without_touching_unrelated_work(tmp_path: Path) -> None:
    target_path = "target.py"
    unrelated_path = "unrelated_work.py"
    target = tmp_path / target_path
    unrelated = tmp_path / unrelated_path
    original_target = "VALUE = 1\n"
    unrelated_content = "# dirty work outside task scope\nUNRELATED = 'preserve exactly'\n"
    target.write_text(original_target, encoding="utf-8")
    unrelated.write_text(unrelated_content, encoding="utf-8")

    request = TaskRequest(
        instruction="Update only target.py and validate it.",
        target_paths=(target_path,),
        metadata={
            "max_automatic_repair_attempts": 0,
            "patch_operations": [
                {
                    "operation": "replace_file",
                    "path": target_path,
                    "content": "def broken(:\n",
                }
            ],
        },
        build_commands=(_compile(target_path),),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, target_path).execute_internal(request)

    assert result.status is TaskStatus.ROLLED_BACK, result.error_message
    assert result.rollback_attempted is True
    assert result.rollback_succeeded is True
    assert target.read_text(encoding="utf-8") == original_target
    assert unrelated.read_text(encoding="utf-8") == unrelated_content
