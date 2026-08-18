from __future__ import annotations

from code_builder.ollama_service import OllamaClientConfiguration, OllamaService
from code_builder.planning_service import PlanningConfiguration, PlanningService


def _service(configuration: PlanningConfiguration) -> PlanningService:
    return PlanningService(
        ollama_service=OllamaService(
            configuration=OllamaClientConfiguration()
        ),
        configuration=configuration,
    )


def _analysis(tmp_path):
    return {
        "repository_root": str(tmp_path),
        "repository_name": "budget-test",
        "files": [],
    }


def test_default_planning_context_budget_never_exceeds_available_input(tmp_path) -> None:
    configuration = PlanningConfiguration()
    context = _service(configuration).build_context(
        user_request="Update one small backend function safely.",
        analysis=_analysis(tmp_path),
    )
    metadata = context.context_metadata or {}

    available_input = max(
        512,
        configuration.context_window
        - configuration.maximum_output_tokens
        - configuration.input_token_safety_margin,
    )
    assert metadata["context_budget_tokens"] <= available_input


def test_large_context_still_uses_configured_context_cap(tmp_path) -> None:
    configuration = PlanningConfiguration(
        context_window=16_384,
        maximum_output_tokens=2_048,
        input_token_safety_margin=2_048,
        maximum_context_input_tokens=6_000,
    )
    context = _service(configuration).build_context(
        user_request="Update one small backend function safely.",
        analysis=_analysis(tmp_path),
    )
    metadata = context.context_metadata or {}

    assert metadata["context_budget_tokens"] == 6_000
