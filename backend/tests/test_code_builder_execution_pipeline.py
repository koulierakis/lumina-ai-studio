from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

from code_builder.models import (
    ChangePlan,
    ChangeType,
    ProposedFileChange,
)
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


def _plan_for_changes(
    changes: list[tuple[str, str]],
) -> GeneratedChangePlan:
    paths = [path for path, _ in changes]
    return GeneratedChangePlan(
        title="Apply controlled multi-file changes",
        summary="Apply every explicit file change in the approved plan.",
        objective="Keep generated patch coverage aligned with approval.",
        risk_level="low",
        files=[
            GeneratedFileChange(
                path=path,
                operation=operation,
                summary=f"{operation} {path}",
                rationale="Explicitly required by the task.",
            )
            for path, operation in changes
        ],
        steps=[
            GeneratedPlanStep(
                order=1,
                title="Apply approved files",
                description="Apply every explicit file operation.",
                file_paths=paths,
                validation=["Verify all planned files are covered."],
            )
        ],
        acceptance_criteria=["Every planned file is represented in the patch."],
        test_plan=["Compile the resulting Python files."],
        rollback_plan=["Restore the automatic backup."],
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


def test_builtin_python_compile_uses_running_interpreter_without_custom_allowlist(
    tmp_path: Path,
) -> None:
    source = tmp_path / "probe.py"
    source.write_text("FLAG = True\n", encoding="utf-8")

    build = BuildService(
        BuildServiceConfiguration(repository_root=tmp_path)
    ).execute_sequence(
        (
            BuildCommandSpec(
                command_id="probe-compile",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=(source.name,),
                timeout_seconds=60,
            ),
        )
    )

    command = build.commands[0]
    assert command.status is BuildStatus.SUCCEEDED, (
        f"stdout={command.stdout!r}; stderr={command.stderr!r}; "
        f"executable={command.executable!r}"
    )


def test_custom_absolute_executable_still_requires_explicit_allowlist(
    tmp_path: Path,
) -> None:
    build = BuildService(
        BuildServiceConfiguration(repository_root=tmp_path)
    ).execute_sequence(
        (
            BuildCommandSpec(
                command_id="custom-python",
                kind=BuildCommandKind.CUSTOM,
                executable=sys.executable,
                arguments=("--version",),
            ),
        )
    )

    command = build.commands[0]
    assert command.status is BuildStatus.ERROR
    assert "allowlist" in (command.error_message or "").lower()


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


def test_complete_create_modify_delete_plan_coverage_is_accepted(
    tmp_path: Path,
) -> None:
    created = "created.py"
    modified = "modified.py"
    deleted = "deleted.py"
    (tmp_path / modified).write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / deleted).write_text("REMOVE = True\n", encoding="utf-8")
    plan = _plan_for_changes(
        [(created, "create"), (modified, "modify"), (deleted, "delete")]
    )
    request = TaskRequest(
        instruction="Create, modify, and delete the three approved files.",
        target_paths=(created, modified, deleted),
        metadata={
            "patch_operations": [
                {"operation": "create", "path": created, "content": "CREATED = True\n"},
                {
                    "operation": "replace_text",
                    "path": modified,
                    "search_text": "VALUE = 1",
                    "replacement_text": "VALUE = 2",
                },
                {"operation": "delete", "path": deleted},
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="compile-covered-files",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=(created, modified),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, plan).execute_internal(request)

    assert result.status is TaskStatus.SUCCEEDED, result.error_message
    assert (tmp_path / created).read_text(encoding="utf-8") == "CREATED = True\n"
    assert (tmp_path / modified).read_text(encoding="utf-8") == "VALUE = 2\n"
    assert not (tmp_path / deleted).exists()


def test_incomplete_approved_plan_patch_is_rejected_before_apply(
    tmp_path: Path,
) -> None:
    greeting = "greeting.py"
    settings = "settings.json"
    test_file = "test_greeting.py"
    original_greeting = "def message() -> str:\n    return 'pending'\n"
    original_settings = '{\n  "mode": "pending"\n}\n'
    (tmp_path / greeting).write_text(original_greeting, encoding="utf-8")
    (tmp_path / settings).write_text(original_settings, encoding="utf-8")
    plan = {
        "changes": [
            {"relative_path": greeting, "change_type": "modify"},
            {"relative_path": settings, "change_type": "modify"},
            {"relative_path": test_file, "change_type": "create"},
        ]
    }
    request = TaskRequest(
        instruction="Apply the approved three-file greeting change.",
        target_paths=(greeting, settings, test_file),
        metadata={
            "patch_operations": [
                {
                    "operation": "replace_text",
                    "path": settings,
                    "search_text": '"pending"',
                    "replacement_text": '"verified"',
                }
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="must-not-run",
                kind=BuildCommandKind.PYTEST,
                arguments=(test_file,),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, plan).execute_internal(request)

    assert result.status is TaskStatus.ROLLED_BACK
    assert result.rollback_attempted is True
    assert result.patch_application is None
    assert result.build_result is None
    assert result.error_message is not None
    assert "Generated patch does not cover approved plan." in result.error_message
    assert "- greeting.py" in result.error_message
    assert "- test_greeting.py" in result.error_message
    assert (tmp_path / greeting).read_text(encoding="utf-8") == original_greeting
    assert (tmp_path / settings).read_text(encoding="utf-8") == original_settings
    assert not (tmp_path / test_file).exists()


def test_patch_path_traversal_alias_cannot_satisfy_plan_coverage(
    tmp_path: Path,
) -> None:
    path = "safe.py"
    original = "SAFE = True\n"
    (tmp_path / path).write_text(original, encoding="utf-8")
    request = TaskRequest(
        instruction="Modify the approved safe file.",
        target_paths=(path,),
        metadata={
            "patch_operations": [
                {
                    "operation": "replace_text",
                    "path": "nested/../safe.py",
                    "search_text": "True",
                    "replacement_text": "False",
                }
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="must-not-run",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=(path,),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(
        tmp_path,
        {
            "changes": [
                {"relative_path": path, "change_type": "modify"},
            ]
        },
    ).execute_internal(request)

    assert result.status is TaskStatus.ROLLED_BACK
    assert result.patch_application is None
    assert result.build_result is None
    assert result.error_message is not None
    assert "unsafe repository-relative path" in result.error_message
    assert (tmp_path / path).read_text(encoding="utf-8") == original


def test_informational_plan_entry_does_not_require_patch_coverage(
    tmp_path: Path,
) -> None:
    path = "covered.py"
    plan = {
        "changes": [
            {"relative_path": path, "change_type": "create"},
            {"relative_path": "notes-only.txt", "change_type": "informational"},
        ]
    }
    request = TaskRequest(
        instruction="Create the required file and retain informational guidance.",
        target_paths=(path,),
        metadata={
            "patch_operations": [
                {"operation": "create", "path": path, "content": "OK = True\n"}
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="compile",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=(path,),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, plan).execute_internal(request)

    assert result.status is TaskStatus.SUCCEEDED, result.error_message
    assert (tmp_path / path).read_text(encoding="utf-8") == "OK = True\n"


def test_plan_delete_but_patch_replaces_is_rejected(
    tmp_path: Path,
) -> None:
    """A patch cannot silently downgrade a planned delete to an edit."""

    deleted = "deleted.py"
    (tmp_path / deleted).write_text("REMOVE = True\n", encoding="utf-8")
    plan = {
        "changes": [
            {"relative_path": deleted, "change_type": "delete"},
        ]
    }
    request = TaskRequest(
        instruction="Delete the approved file.",
        target_paths=(deleted,),
        metadata={
            "patch_operations": [
                {
                    "operation": "replace_text",
                    "path": deleted,
                    "search_text": "REMOVE = True",
                    "replacement_text": "REMOVE = False",
                }
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="must-not-run",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=(deleted,),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, plan).execute_internal(request)

    assert result.status is TaskStatus.ROLLED_BACK
    assert result.patch_application is None
    assert result.error_message is not None
    assert "does not delete it" in result.error_message
    assert (tmp_path / deleted).read_text(encoding="utf-8") == "REMOVE = True\n"


def test_plan_rename_but_patch_renames_to_other_destination_is_rejected(
    tmp_path: Path,
) -> None:
    source = "old_name.py"
    (tmp_path / source).write_text("VALUE = 1\n", encoding="utf-8")
    plan = {
        "changes": [
            {
                "relative_path": "new_name.py",
                "change_type": "rename",
                "previous_path": source,
            },
        ]
    }
    request = TaskRequest(
        instruction="Rename the approved file.",
        target_paths=(source,),
        metadata={
            "patch_operations": [
                {
                    "operation": "rename",
                    "path": source,
                    "destination_path": "other_name.py",
                }
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="must-not-run",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=(source,),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, plan).execute_internal(request)

    assert result.status is TaskStatus.ROLLED_BACK
    assert result.patch_application is None
    assert result.error_message is not None
    # Path coverage rejects the unplanned destination before application.
    assert "new_name.py" in result.error_message
    assert (tmp_path / source).exists()
    assert not (tmp_path / "other_name.py").exists()


def test_domain_change_plan_delete_and_rename_execute_faithfully(
    tmp_path: Path,
) -> None:
    """Domain ChangePlan (change_type) coverage works at the task level."""

    stale = "stale.py"
    (tmp_path / stale).write_text("OLD = True\n", encoding="utf-8")
    old_name = "old_name.py"
    (tmp_path / old_name).write_text("VALUE = 1\n", encoding="utf-8")
    plan = ChangePlan(
        task_id=uuid4(),
        title="Delete stale file and rename module",
        summary="Controlled destructive operations.",
        changes=[
            ProposedFileChange(
                relative_path=stale,
                change_type=ChangeType.DELETE,
                old_content="OLD = True\n",
                summary="Remove stale file.",
                reason="Requested.",
            ),
            ProposedFileChange(
                relative_path="new_name.py",
                change_type=ChangeType.RENAME,
                previous_path=old_name,
                new_content="VALUE = 1\n",
                summary="Rename module.",
                reason="Requested.",
            ),
        ],
    )
    request = TaskRequest(
        instruction="Delete stale.py and rename old_name.py to new_name.py.",
        target_paths=(stale, old_name),
        metadata={
            "patch_operations": [
                {"operation": "delete", "path": stale},
                {
                    "operation": "rename",
                    "path": old_name,
                    "destination_path": "new_name.py",
                },
            ]
        },
        build_commands=(
            BuildCommandSpec(
                command_id="compile-remaining",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=("new_name.py",),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    result = _service(tmp_path, plan).execute_internal(request)

    assert result.status is TaskStatus.SUCCEEDED, result.error_message
    assert not (tmp_path / stale).exists()
    assert not (tmp_path / old_name).exists()
    assert (tmp_path / "new_name.py").read_text(encoding="utf-8") == "VALUE = 1\n"


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
