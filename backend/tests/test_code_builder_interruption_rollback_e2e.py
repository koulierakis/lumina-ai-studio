from __future__ import annotations

import sys
from pathlib import Path

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
    TaskCancellationToken,
    TaskRequest,
    TaskService,
    TaskServiceConfiguration,
    TaskStage,
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
    def __init__(self, path: str) -> None:
        self.path = path

    def plan(self, **_: object) -> GeneratedChangePlan:
        return GeneratedChangePlan(
            title="Interruption rollback E2E",
            summary="Modify one controlled file and verify rollback after cancellation.",
            objective="Prove cancellation cannot strand applied repository changes.",
            risk_level="low",
            files=[
                GeneratedFileChange(
                    path=self.path,
                    operation="update",
                    summary="Update controlled target",
                    rationale="Exercise interruption-safe rollback.",
                )
            ],
            steps=[
                GeneratedPlanStep(
                    order=1,
                    title="Update controlled target",
                    description="Apply one controlled edit.",
                    file_paths=[self.path],
                    validation=["Compile controlled target."],
                )
            ],
            acceptance_criteria=["Cancellation restores the original file."],
            test_plan=["Cancel immediately after patch application."],
            rollback_plan=["Restore the automatic backup."],
        )


class _UnusedModelService:
    pass


def _service(root: Path, path: str) -> TaskService:
    return TaskService(
        repository_service=_RepositoryService(root),
        planning_service=_PlanningService(path),
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
            rollback_timeout_seconds=30.0,
        ),
    )


def test_e2e_cancellation_after_applied_patch_restores_original_file(tmp_path: Path) -> None:
    path = "cancelled_target.py"
    target = tmp_path / path
    original = "VALUE = 'before'\n"
    modified = "VALUE = 'after'\n"
    target.write_text(original, encoding="utf-8")

    request = TaskRequest(
        task_id="cancel-after-apply",
        instruction="Change the controlled target and validate it.",
        target_paths=(path,),
        metadata={
            "patch_operations": [
                {
                    "operation": "replace_file",
                    "path": path,
                    "content": modified,
                    "description": "Controlled change before cancellation.",
                }
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="compile-cancelled-target",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=(path,),
                timeout_seconds=30,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )
    token = TaskCancellationToken(task_id=request.task_id)
    saw_applied_change = False

    def cancel_after_apply(event) -> None:
        nonlocal saw_applied_change
        if (
            event.stage is TaskStage.PATCH_APPLICATION
            and event.message == "Patch application completed."
        ):
            assert target.read_text(encoding="utf-8") == modified
            saw_applied_change = True
            token.cancel("controlled cancellation after patch application")

    result = _service(tmp_path, path).execute_internal(
        request,
        event_callback=cancel_after_apply,
        cancellation_token=token,
    )

    assert saw_applied_change is True
    assert token.is_cancelled() is True
    assert result.status is TaskStatus.ROLLED_BACK, result.error_message
    assert result.rollback_attempted is True
    assert result.rollback_succeeded is True
    assert target.read_text(encoding="utf-8") == original
    assert any(
        event.status is TaskStatus.ROLLED_BACK
        for event in result.events
    )
