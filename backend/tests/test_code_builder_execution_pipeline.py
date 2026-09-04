from __future__ import annotations

from pathlib import Path
import sys

from code_builder.backup_service import BackupService
from code_builder.build_service import (
    BuildCommandKind,
    BuildCommandSpec,
    BuildService,
    BuildServiceConfiguration,
    BuildStatus,
)
from code_builder.patch_service import PatchService
from code_builder.planning_service import (
    GeneratedChangePlan,
    GeneratedFileChange,
    GeneratedPlanStep,
)
from code_builder.task_service import (
    BackupPolicy,
    RollbackPolicy,
    TaskRequest,
    TaskService,
    TaskServiceConfiguration,
    TaskStatus,
)
from code_builder.router import (
    ApprovalDecision,
    CodeBuilderTaskPhase,
    StoredTask,
    TaskApprovalRequest,
    TaskCreateRequest,
    TaskStore,
    _phase_allows_approval,
    _task_request_from_api,
)


class StaticRepositoryService:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root

    def analyze_repository(self) -> dict[str, object]:
        return {
            "repository_root": str(self.repository_root),
            "files": [],
        }


class StaticPlanningService:
    def __init__(self, plan: GeneratedChangePlan) -> None:
        self.generated_plan = plan

    def plan(self, **_: object) -> GeneratedChangePlan:
        return self.generated_plan


class UnusedOllamaService:
    pass


def _plan_for(path: str) -> GeneratedChangePlan:
    return GeneratedChangePlan(
        title="Add health-check backend unit test",
        summary="Create a small backend health-check unit test.",
        objective="Validate health-check behavior without public API changes.",
        risk_level="low",
        files=[
            GeneratedFileChange(
                path=path,
                operation="create",
                summary="Add unit test file.",
                rationale="The task requested a backend health-check unit test.",
            )
        ],
        steps=[
            GeneratedPlanStep(
                order=1,
                title="Create test",
                description="Write the health-check unit test file.",
                file_paths=[path],
                validation=["Run pytest for the new test."],
            )
        ],
        acceptance_criteria=["The new test passes."],
        test_plan=["python -m pytest tests/test_health_check_unit.py"],
        rollback_plan=["Restore files from automatic backup."],
    )


def _service(repository_root: Path, plan: GeneratedChangePlan) -> TaskService:
    return TaskService(
        repository_service=StaticRepositoryService(repository_root),
        planning_service=StaticPlanningService(plan),
        backup_service=BackupService(repository_root),
        patch_service=PatchService(repository_root=repository_root),
        build_service=BuildService(
            BuildServiceConfiguration(
                repository_root=repository_root,
                custom_command_policy={
                    "executable_paths": frozenset({sys.executable}),
                },
            )
        ),
        ollama_service=UnusedOllamaService(),
        configuration=TaskServiceConfiguration(
            repository_root=repository_root,
            use_default_build_sequence=False,
            include_ruff=False,
            include_mypy=False,
            include_frontend_tests=False,
            include_frontend_build=False,
        ),
    )


def test_nested_pytest_build_preserves_repository_and_backup(tmp_path: Path) -> None:
    test_path = "tests/test_nested_pass.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / test_path).write_text("def test_pass():\n    assert True\n", encoding="utf-8")
    backup_service = BackupService(tmp_path)
    backup = backup_service.create_backup((test_path,), reason="nested pytest diagnostic")
    manifest = Path(backup.manifest_path)
    assert manifest.exists()

    build = BuildService(
        BuildServiceConfiguration(
            repository_root=tmp_path,
            custom_command_policy={"executable_paths": frozenset({sys.executable})},
        )
    ).execute_sequence(
        (
            BuildCommandSpec(
                command_id="nested-pytest-diagnostic",
                kind=BuildCommandKind.PYTEST,
                arguments=(test_path,),
                timeout_seconds=60,
            ),
        )
    )
    command = build.commands[0]
    assert command.status is BuildStatus.SUCCEEDED, (
        f"stdout={command.stdout!r}; stderr={command.stderr!r}; "
        f"cwd={command.working_directory!r}; args={command.arguments!r}"
    )
    assert manifest.exists(), f"nested pytest removed backup manifest: {manifest}"


def test_approved_generated_change_plan_executes_with_backup_and_diff(
    tmp_path: Path,
) -> None:
    test_path = "tests/test_health_check_unit.py"
    (tmp_path / "tests").mkdir()
    new_content = (
        "def test_backend_health_check_contract():\n"
        "    response = {'status': 'ok'}\n"
        "    assert response['status'] == 'ok'\n"
    )

    request = TaskRequest(
        instruction="Add a backend health-check unit test without changing public APIs.",
        target_paths=(test_path,),
        metadata={
            "patch_operations": [
                {
                    "operation": "create",
                    "path": test_path,
                    "content": new_content,
                    "description": "Create backend health-check unit test.",
                }
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="health-check-test",
                kind=BuildCommandKind.PYTEST,
                arguments=("tests/test_health_check_unit.py",),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    events: list[str] = []
    result = _service(tmp_path, _plan_for(test_path)).execute_internal(
        request,
        event_callback=lambda event: events.append(event.stage.value),
    )

    assert result.status is TaskStatus.SUCCEEDED, (
        f"error_type={result.error_type}; error_message={result.error_message}; "
        f"rollback_attempted={result.rollback_attempted}; "
        f"rollback_succeeded={result.rollback_succeeded}"
    )
    assert (tmp_path / test_path).read_text(encoding="utf-8") == new_content
    assert result.backup is not None
    assert result.patch_validation is not None
    assert result.patch_application is not None
    assert result.build_result is not None
    assert result.build_result.status is BuildStatus.SUCCEEDED
    assert result.rollback_attempted is False
    assert result.changed_paths == (test_path,)
    assert "backup" in events
    assert "patch_application" in events
    assert "build" in events
    assert "def test_backend_health_check_contract" in (
        result.patch_application.results[0].diff
    )


def test_execution_rolls_back_when_validation_fails(
    tmp_path: Path,
) -> None:
    test_path = "tests/test_health_check_unit.py"
    (tmp_path / "tests").mkdir()
    request = TaskRequest(
        instruction="Add a backend health-check unit test without changing public APIs.",
        target_paths=(test_path,),
        metadata={
            "patch_operations": [
                {
                    "operation": "create",
                    "path": test_path,
                    "content": "def test_broken():\n    assert False\n",
                }
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="health-check-test",
                kind=BuildCommandKind.PYTEST,
                arguments=("tests/test_health_check_unit.py",),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, _plan_for(test_path)).execute_internal(request)

    assert result.status is TaskStatus.ROLLED_BACK, (
        f"error_type={result.error_type}; error_message={result.error_message}; "
        f"rollback_attempted={result.rollback_attempted}; "
        f"rollback_succeeded={result.rollback_succeeded}"
    )
    assert result.rollback_attempted is True
    assert result.rollback_succeeded is True
    assert result.rollback_result is not None
    assert not (tmp_path / test_path).exists()


def test_execution_rejects_unapproved_plan_path(
    tmp_path: Path,
) -> None:
    planned_path = "tests/test_health_check_unit.py"
    unexpected_path = "tests/test_other.py"
    (tmp_path / "tests").mkdir()
    request = TaskRequest(
        instruction="Add a backend health-check unit test without changing public APIs.",
        target_paths=(planned_path,),
        metadata={
            "patch_operations": [
                {
                    "operation": "create",
                    "path": unexpected_path,
                    "content": "def test_other():\n    assert True\n",
                }
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="compile",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=(".",),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, _plan_for(planned_path)).execute_internal(request)

    assert result.status is TaskStatus.ROLLED_BACK
    assert result.rollback_attempted is True
    assert not (tmp_path / unexpected_path).exists()


def test_execution_rejects_patch_missing_required_planned_file(tmp_path: Path) -> None:
    first = "tests/test_first.py"
    second = "tests/test_second.py"
    (tmp_path / "tests").mkdir()
    plan = GeneratedChangePlan(
        title="Create two required tests",
        summary="Both files are required by the approved plan.",
        objective="Verify incomplete generated patches cannot execute.",
        risk_level="low",
        files=[
            GeneratedFileChange(path=first, operation="create", summary="Create first test.", rationale="Required by task."),
            GeneratedFileChange(path=second, operation="create", summary="Create second test.", rationale="Required by task."),
        ],
        steps=[GeneratedPlanStep(order=1, title="Create both tests", description="Create both planned files.", file_paths=[first, second], validation=["Both files must exist."])],
        acceptance_criteria=["Both planned files are present."],
        test_plan=["python -m compileall tests"],
        rollback_plan=["Restore the automatic backup."],
    )
    request = TaskRequest(
        instruction="Create both planned test files.",
        target_paths=(first, second),
        metadata={"patch_operations": [{"operation": "create", "path": first, "content": "FIRST = True\n"}]},
        build_commands=(BuildCommandSpec(command_id="compile", kind=BuildCommandKind.PYTHON_COMPILE, arguments=(".",), timeout_seconds=60),),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, plan).execute_internal(request)

    assert result.status is TaskStatus.ROLLED_BACK
    assert result.rollback_attempted is True
    assert "required planned files are missing" in (result.error_message or "")
    assert second in (result.error_message or "")
    assert not (tmp_path / first).exists()
    assert not (tmp_path / second).exists()


def test_approval_marks_awaiting_task_as_approved() -> None:
    api_request = TaskCreateRequest(
        instruction="Add a backend health-check unit test without changing public APIs.",
        target_paths=("tests/test_health_check_unit.py",),
        require_approval=True,
        auto_start_after_approval=False,
        metadata={
            "patch_operations": [
                {
                    "operation": "create",
                    "path": "tests/test_health_check_unit.py",
                    "content": "def test_health():\n    assert True\n",
                }
            ]
        },
    )
    task_request = _task_request_from_api(
        api_request,
        task_id="approval-test",
    )
    store = TaskStore()
    stored = StoredTask(
        request=task_request,
        api_request=api_request,
        phase=CodeBuilderTaskPhase.AWAITING_APPROVAL,
        created_at_epoch=1.0,
        updated_at_epoch=1.0,
        require_approval=True,
        auto_start_after_approval=False,
        cancellation_token=_service(
            Path.cwd(),
            _plan_for("tests/test_health_check_unit.py"),
        ).create_cancellation_token("approval-test"),
    )

    created = store.create(stored)
    approval = TaskApprovalRequest(
        decision=ApprovalDecision.APPROVE,
        comment="Approved execution test.",
        start_immediately=False,
    )

    assert _phase_allows_approval(created.phase) is True
    created.approved_at_epoch = 2.0
    created.approval_comment = approval.comment
    created.phase = CodeBuilderTaskPhase.APPROVED
    created.touch()

    assert created.phase is CodeBuilderTaskPhase.APPROVED
    assert created.approved_at_epoch == 2.0
    assert created.approval_comment == "Approved execution test."
