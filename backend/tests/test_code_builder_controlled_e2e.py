from __future__ import annotations

from pathlib import Path
import sys

from backend.code_builder.backup_service import BackupService
from backend.code_builder.build_service import (
    BuildCommandKind,
    BuildCommandSpec,
    BuildService,
    BuildServiceConfiguration,
    BuildStatus,
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
    def __init__(self, plan: GeneratedChangePlan) -> None:
        self.plan_value = plan

    def plan(self, **_: object) -> GeneratedChangePlan:
        return self.plan_value


class _UnusedModelService:
    pass


def _plan(paths: tuple[str, ...]) -> GeneratedChangePlan:
    return GeneratedChangePlan(
        title="Controlled Code Builder E2E",
        summary="Apply controlled edits to test targets.",
        objective="Verify real multi-stage Code Builder file editing.",
        risk_level="low",
        files=[
            GeneratedFileChange(
                path=path,
                operation="update",
                summary=f"Update {path}",
                rationale="Controlled E2E target.",
            )
            for path in paths
        ],
        steps=[
            GeneratedPlanStep(
                order=index,
                title=f"Update {path}",
                description=f"Apply the requested controlled edit to {path}.",
                file_paths=[path],
                validation=[f"Compile {path}."],
            )
            for index, path in enumerate(paths, start=1)
        ],
        acceptance_criteria=["All requested files contain the expected content."],
        test_plan=["Compile every edited Python target."],
        rollback_plan=["Restore the automatic backup."],
    )


def _service(root: Path, paths: tuple[str, ...]) -> TaskService:
    return TaskService(
        repository_service=_RepositoryService(root),
        planning_service=_PlanningService(_plan(paths)),
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


def _compile_command(command_id: str, path: str) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.PYTHON_COMPILE,
        arguments=(path,),
        timeout_seconds=60,
    )


def test_e2e_modifies_existing_file_and_verifies_result(tmp_path: Path) -> None:
    path = "target.py"
    target = tmp_path / path
    target.write_text("VALUE = 'before'\n", encoding="utf-8")

    request = TaskRequest(
        instruction="Change target VALUE from before to after.",
        target_paths=(path,),
        metadata={
            "patch_operations": [
                {
                    "operation": "replace_text",
                    "path": path,
                    "search": "VALUE = 'before'",
                    "replacement": "VALUE = 'after'",
                    "description": "Controlled existing-file modification.",
                }
            ]
        },
        build_commands=(_compile_command("compile-target", path),),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, (path,)).execute_internal(request)

    assert result.status is TaskStatus.SUCCEEDED, result.error_message
    assert target.read_text(encoding="utf-8") == "VALUE = 'after'\n"
    assert result.changed_paths == (path,)
    assert result.build_result is not None
    assert result.build_result.status is BuildStatus.SUCCEEDED
    assert result.rollback_attempted is False


def test_e2e_modifies_multiple_files_and_verifies_all_results(tmp_path: Path) -> None:
    first_path = "first.py"
    second_path = "second.py"
    first = tmp_path / first_path
    second = tmp_path / second_path
    first.write_text("FIRST = 1\n", encoding="utf-8")
    second.write_text("SECOND = 1\n", encoding="utf-8")

    request = TaskRequest(
        instruction="Update both controlled Python targets.",
        target_paths=(first_path, second_path),
        metadata={
            "patch_operations": [
                {
                    "operation": "replace_text",
                    "path": first_path,
                    "search": "FIRST = 1",
                    "replacement": "FIRST = 2",
                },
                {
                    "operation": "replace_text",
                    "path": second_path,
                    "search": "SECOND = 1",
                    "replacement": "SECOND = 2",
                },
            ]
        },
        build_commands=(
            _compile_command("compile-first", first_path),
            _compile_command("compile-second", second_path),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, (first_path, second_path)).execute_internal(request)

    assert result.status is TaskStatus.SUCCEEDED, result.error_message
    assert first.read_text(encoding="utf-8") == "FIRST = 2\n"
    assert second.read_text(encoding="utf-8") == "SECOND = 2\n"
    assert set(result.changed_paths) == {first_path, second_path}
    assert result.build_result is not None
    assert result.build_result.status is BuildStatus.SUCCEEDED
    assert all(command.status is BuildStatus.SUCCEEDED for command in result.build_result.commands)
    assert result.rollback_attempted is False
