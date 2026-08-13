from pathlib import Path

from code_builder.backup_service import BackupService
from code_builder.build_service import BuildService, BuildServiceConfiguration
from code_builder.patch_service import PatchService
from code_builder.planning_service import GeneratedChangePlan, GeneratedFileChange, GeneratedPlanStep
from code_builder.router import (
    CodeBuilderTaskPhase,
    StoredTask,
    TaskCreateRequest,
    TaskStore,
    _bind_prepared_patch_to_request,
    _review_prepared_change,
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
    def __init__(self, plan: GeneratedChangePlan) -> None:
        self.plan_result = plan

    def plan(self, **_):
        return self.plan_result


class UnusedOllamaService:
    pass


def make_plan(path: str) -> GeneratedChangePlan:
    return GeneratedChangePlan(
        title="Prepared change",
        summary="Prepare one deterministic file change.",
        objective="Verify approval is the production-write boundary.",
        risk_level="low",
        files=[GeneratedFileChange(path=path, operation="create", summary="Create file", rationale="test")],
        steps=[GeneratedPlanStep(order=1, title="Create", description="Create file", file_paths=[path], validation=["verify"])],
        acceptance_criteria=["file exists after approval"],
        test_plan=["targeted verification"],
        rollback_plan=["restore backup"],
    )


def make_service(root: Path, path: str) -> TaskService:
    return TaskService(
        repository_service=StaticRepositoryService(root),
        planning_service=StaticPlanningService(make_plan(path)),
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


def test_preparation_generates_diff_without_writing_then_approval_applies(tmp_path: Path) -> None:
    relative = "backend/prepared_boundary.py"
    (tmp_path / "backend").mkdir()
    payload = TaskCreateRequest(
        instruction="Create the prepared boundary module.",
        require_approval=True,
        auto_start_after_approval=False,
        build_policy=BuildPolicy.DISABLED,
        metadata={
            "patch_operations": [
                {"operation": "create", "path": relative, "content": "BOUNDARY = 'approved'\n"}
            ]
        },
    )
    service = make_service(tmp_path, relative)
    request = _task_request_from_api(payload, task_id="boundary-test")
    stored = StoredTask(
        request=request,
        api_request=payload,
        phase=CodeBuilderTaskPhase.QUEUED,
        created_at_epoch=1.0,
        updated_at_epoch=1.0,
        require_approval=True,
        auto_start_after_approval=False,
        cancellation_token=service.create_cancellation_token("boundary-test"),
    )
    store = TaskStore()
    store.create(stored)

    _run_stored_task_sync(task_service=service, task_store=store, stored_task=stored)

    assert stored.phase is CodeBuilderTaskPhase.AWAITING_APPROVAL
    assert stored.preparation_result is not None
    assert not (tmp_path / relative).exists()
    prepared = stored.preparation_result
    assert prepared.patch_validation is not None
    assert "BOUNDARY = 'approved'" in prepared.patch_validation.results[0].diff

    stored.request = _bind_prepared_patch_to_request(stored)
    stored.approved_at_epoch = 2.0
    stored.phase = CodeBuilderTaskPhase.APPROVED
    stored.cancellation_token = service.create_cancellation_token("boundary-test")
    _run_stored_task_sync(task_service=service, task_store=store, stored_task=stored)

    assert stored.phase is CodeBuilderTaskPhase.COMPLETED, stored.result
    assert (tmp_path / relative).read_text(encoding="utf-8") == "BOUNDARY = 'approved'\n"


class ReviewOllamaService:
    model = "review-test-model"

    def analyze_code_task(self, **kwargs):
        assert kwargs["user_context"]["purpose"] == "pre_approval_review"
        return "WARN: Add a targeted regression test for backend/prepared_boundary.py."


def test_prepared_change_ai_review_is_non_writing_and_structured(tmp_path: Path) -> None:
    relative = "backend/prepared_boundary.py"
    (tmp_path / "backend").mkdir()
    payload = TaskCreateRequest(
        instruction="Review prepared change.",
        require_approval=True,
        auto_start_after_approval=False,
        build_policy=BuildPolicy.DISABLED,
    )
    service = make_service(tmp_path, relative)
    service._ollama_service = ReviewOllamaService()
    request = _task_request_from_api(payload, task_id="review-test")
    stored = StoredTask(
        request=request,
        api_request=payload,
        phase=CodeBuilderTaskPhase.AWAITING_APPROVAL,
        created_at_epoch=1.0,
        updated_at_epoch=1.0,
        require_approval=True,
        auto_start_after_approval=False,
        cancellation_token=service.create_cancellation_token("review-test"),
    )

    review = _review_prepared_change(
        task_service=service,
        stored_task=stored,
        preparation_result={"plan": {"title": "test"}, "patch_validation": {"valid": True}},
    )

    assert review["status"] == "completed"
    assert review["verdict"] == "warn"
    assert review["model"] == "review-test-model"
    assert "targeted regression test" in review["summary"]
    assert not (tmp_path / relative).exists()
