from __future__ import annotations

from types import SimpleNamespace

from code_builder.router import (
    CodeBuilderTaskPhase,
    StoredTask,
    TaskCreateRequest,
    _review_prepared_change,
    _task_request_from_api,
)
from code_builder.task_service import TaskCancellationToken


class GenerateOnlyOllama:
    async def generate(self, **kwargs):
        assert kwargs["model"] == "qwen2.5-coder:7b"
        assert "prepared_change" in kwargs["prompt"]
        assert kwargs["system_prompt"].startswith("Act as the independent LUMINA")
        return SimpleNamespace(content="PASS: Prepared change is scoped and safe.")


class PlanningConfiguration:
    model = "qwen2.5-coder:7b"
    context_window = 4096


class ReviewTaskService:
    def __init__(self):
        self.ollama_service = GenerateOnlyOllama()
        self.planning_service = SimpleNamespace(configuration=PlanningConfiguration())


def test_review_falls_back_to_real_ollama_generate_method() -> None:
    payload = TaskCreateRequest(
        instruction="Create one safe file.",
        require_approval=True,
        auto_start_after_approval=False,
    )
    request = _task_request_from_api(payload, task_id="real-review-adapter")
    stored = StoredTask(
        request=request,
        api_request=payload,
        phase=CodeBuilderTaskPhase.AWAITING_APPROVAL,
        created_at_epoch=1.0,
        updated_at_epoch=1.0,
        require_approval=True,
        auto_start_after_approval=False,
        cancellation_token=TaskCancellationToken(task_id="real-review-adapter"),
    )

    review = _review_prepared_change(
        task_service=ReviewTaskService(),
        stored_task=stored,
        preparation_result={
            "plan": {"title": "Safe change"},
            "patch": {"operations": [{"operation": "create", "path": "safe.txt"}]},
            "patch_validation": {"valid": True},
        },
    )

    assert review["status"] == "completed"
    assert review["verdict"] == "pass"
    assert review["model"] == "qwen2.5-coder:7b"


def test_review_unknown_first_word_defaults_to_warning_not_pass() -> None:
    class AmbiguousOllama:
        async def generate(self, **_kwargs):
            return SimpleNamespace(content="Needs another look before applying.")

    service = ReviewTaskService()
    service.ollama_service = AmbiguousOllama()

    payload = TaskCreateRequest(instruction="Review ambiguous output.")
    request = _task_request_from_api(payload, task_id="ambiguous-review")
    stored = StoredTask(
        request=request,
        api_request=payload,
        phase=CodeBuilderTaskPhase.AWAITING_APPROVAL,
        created_at_epoch=1.0,
        updated_at_epoch=1.0,
        require_approval=True,
        auto_start_after_approval=False,
        cancellation_token=TaskCancellationToken(task_id="ambiguous-review"),
    )

    review = _review_prepared_change(
        task_service=service,
        stored_task=stored,
        preparation_result={"plan": {"title": "Ambiguous"}},
    )

    assert review["status"] == "completed"
    assert review["verdict"] == "warn"
