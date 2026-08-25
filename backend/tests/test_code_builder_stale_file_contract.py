from __future__ import annotations

from pathlib import Path

from code_builder.backup_service import BackupService
from code_builder.build_service import BuildService, BuildServiceConfiguration
from code_builder.patch_service import PatchService
from code_builder.planning_service import (
    GeneratedChangePlan,
    GeneratedFileChange,
    GeneratedPlanStep,
)
from code_builder.router import (
    CodeBuilderTaskPhase,
    StoredTask,
    TaskCreateRequest,
    TaskStore,
    _bind_prepared_patch_to_request,
    _run_stored_task_sync,
    _task_request_from_api,
)
from code_builder.task_service import BuildPolicy, TaskService, TaskServiceConfiguration


class StaticRepositoryService:
    def __init__(self, root: Path) -> None:
        self.repository_root = root

    def analyze_repository(self):
        return {"repository_root": str(self.repository_root), "files": []}


class StaticPlanningService:
    def __init__(self, path: str) -> None:
        self.plan_result = GeneratedChangePlan(
            title="Update guarded file",
            summary="Update one existing file.",
            objective="Prove stale files are never overwritten after approval preview.",
            risk_level="low",
            files=[GeneratedFileChange(path=path, operation="update", summary="Update", rationale="test")],
            steps=[GeneratedPlanStep(order=1, title="Update", description="Update file", file_paths=[path], validation=["verify"])],
            acceptance_criteria=["stale state is preserved"],
            test_plan=["targeted verification"],
            rollback_plan=["restore backup"],
        )

    def plan(self, **_):
        return self.plan_result


class UnusedOllamaService:
    pass


def _service(root: Path, path: str) -> TaskService:
    return TaskService(
        repository_service=StaticRepositoryService(root),
        planning_service=StaticPlanningService(path),
        backup_service=BackupService(root),
        patch_service=PatchService(repository_root=root),
        build_service=BuildService(BuildServiceConfiguration(repository_root=root)),
        ollama_service=UnusedOllamaService(),
        configuration=TaskServiceConfiguration(
            repository_root=root,
            use_default_build_sequence=False,
            include_ruff=False,
            include_mypy=False,
            include_frontend_tests=False,
            include_frontend_build=False,
        ),
    )


def test_file_changed_after_preview_is_not_overwritten(tmp_path: Path) -> None:
    relative = "backend/guarded.py"
    target = tmp_path / relative
    target.parent.mkdir()
    target.write_text("VALUE = 'original'\n", encoding="utf-8")

    payload = TaskCreateRequest(
        instruction="Update guarded.py.",
        require_approval=True,
        auto_start_after_approval=False,
        build_policy=BuildPolicy.DISABLED,
        metadata={
            "patch_operations": [
                {
                    "operation": "replace_file",
                    "path": relative,
                    "content": "VALUE = 'approved'\n",
                }
            ]
        },
    )
    service = _service(tmp_path, relative)
    request = _task_request_from_api(payload, task_id="stale-file-test")
    stored = StoredTask(
        request=request,
        api_request=payload,
        phase=CodeBuilderTaskPhase.QUEUED,
        created_at_epoch=1.0,
        updated_at_epoch=1.0,
        require_approval=True,
        auto_start_after_approval=False,
        cancellation_token=service.create_cancellation_token("stale-file-test"),
    )
    store = TaskStore()
    store.create(stored)

    _run_stored_task_sync(task_service=service, task_store=store, stored_task=stored)
    assert stored.phase is CodeBuilderTaskPhase.AWAITING_APPROVAL

    approved_request = _bind_prepared_patch_to_request(stored)
    approved_operations = approved_request.metadata["approved_patch_operations"]
    assert approved_operations[0].get("expected_sha256")

    target.write_text("VALUE = 'external-newer-change'\n", encoding="utf-8")

    stored.request = approved_request
    stored.approved_at_epoch = 2.0
    stored.phase = CodeBuilderTaskPhase.APPROVED
    stored.cancellation_token = service.create_cancellation_token("stale-file-test")
    _run_stored_task_sync(task_service=service, task_store=store, stored_task=stored)

    assert stored.phase in {
        CodeBuilderTaskPhase.ROLLED_BACK,
        CodeBuilderTaskPhase.FAILED,
    }
    assert target.read_text(encoding="utf-8") == "VALUE = 'external-newer-change'\n"
