"""Tests for the Code Builder planning model strategy.

The primary model (``qwen2.5-coder:1.5b``) must serve every planning request.
The stronger fallback model (``qwen2.5-coder:7b``) may be invoked at most once,
and only after the primary model exhausted its full repair budget (one
initial attempt plus every configured repair attempt).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from code_builder.ollama_service import (
    OllamaClientConfiguration,
    OllamaEndpoint,
    OllamaRawResponse,
    OllamaRequestCancelledError,
    OllamaService,
    OllamaStructuredResponse,
    OllamaTimeoutError,
)
from code_builder.planning_service import (
    DEFAULT_PLANNING_MODEL,
    FALLBACK_PLANNING_MODEL,
    PlanningConfiguration,
    PlanningService,
    PlanningValidationError,
)

PRIMARY_MODEL = "qwen2.5-coder:1.5b"
FALLBACK_MODEL = "qwen2.5-coder:7b"
USER_REQUEST = "Please change FLAG from False to True in app.py."


def _raw_response(model: str, content: str) -> OllamaRawResponse:
    return OllamaRawResponse(
        endpoint=OllamaEndpoint.GENERATE,
        model=model,
        content=content,
        raw_data={},
        created_at=None,
        done=True,
        done_reason="stop",
        total_duration_nanoseconds=None,
        load_duration_nanoseconds=None,
        prompt_eval_count=None,
        prompt_eval_duration_nanoseconds=None,
        eval_count=None,
        eval_duration_nanoseconds=None,
        elapsed_seconds=0.01,
    )


class ScriptedOllama:
    """Real ``OllamaService`` with a scripted ``generate_structured``."""

    def __init__(self) -> None:
        self.service = OllamaService(
            configuration=OllamaClientConfiguration()
        )
        self.requested_models: list[str] = []
        self.prompts: list[str] = []
        self.script: list[Any] = []

    def script_outcomes(self, *outcomes: Any) -> None:
        self.script.extend(outcomes)

    async def _generate_structured(
        self,
        *,
        model: str,
        prompt: str,
        **_: Any,
    ) -> OllamaStructuredResponse:
        self.requested_models.append(model)
        self.prompts.append(prompt)

        if not self.script:
            raise AssertionError(
                "Unexpected Ollama call: scripted outcomes exhausted."
            )

        outcome = self.script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome

        return OllamaStructuredResponse(
            raw_response=_raw_response(model, json.dumps(outcome)),
            data=outcome,
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            self.service,
            "generate_structured",
            self._generate_structured,
        )


class StubAnalysisFile:
    def __init__(self, path: str) -> None:
        self.path = path
        self.relative_path = path


def _valid_payload(title: str = "Enable feature flag") -> dict[str, Any]:
    return {
        "title": title,
        "summary": "Change the existing feature flag from false to true.",
        "objective": (
            "Apply the requested behavior without changing unrelated files."
        ),
        "files": [
            {
                "path": "app.py",
                "operation": "modify",
                "summary": "Enable the existing feature flag.",
                "rationale": "The user explicitly requested the flag change.",
            }
        ],
        "steps": [
            {
                "order": 1,
                "title": "Update flag",
                "description": "Change FLAG from False to True in app.py.",
                "file_paths": ["app.py"],
            }
        ],
        "acceptance_criteria": ["app.py contains FLAG = True and compiles."],
        "test_plan": ["python -m py_compile app.py"],
    }


def _invalid_payload() -> dict[str, Any]:
    return {"unexpected": "not a plan"}


def _service(
    stub: ScriptedOllama,
    repository_root: Path,
    *,
    fallback_model: str | None = None,
    maximum_repair_attempts: int = 1,
) -> PlanningService:
    return PlanningService(
        ollama_service=stub.service,
        configuration=PlanningConfiguration(
            fallback_model=fallback_model,
            maximum_repair_attempts=maximum_repair_attempts,
            timeout_seconds=5.0,
        ),
    )


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("FLAG = False\n", encoding="utf-8")
    return tmp_path


def _plan(service: PlanningService, analysis: StubAnalysis) -> Any:
    return asyncio.run(
        service.plan(
            user_request=USER_REQUEST,
            analysis=analysis,
            return_normalized=True,
        )
    )


def test_model_strategy_constants() -> None:
    assert DEFAULT_PLANNING_MODEL == PRIMARY_MODEL
    assert FALLBACK_PLANNING_MODEL == FALLBACK_MODEL
    configuration = PlanningConfiguration()
    assert configuration.model == PRIMARY_MODEL
    assert configuration.fallback_model is None


def test_primary_model_is_selected_first(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(_valid_payload())
    stub.install(monkeypatch)
    service = _service(stub, repository)

    result = _plan(service, StubAnalysis(repository))

    assert stub.requested_models[0] == PRIMARY_MODEL
    assert result.model == PRIMARY_MODEL


def test_valid_primary_result_does_not_invoke_fallback(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(_valid_payload())
    stub.install(monkeypatch)
    service = _service(stub, repository)

    _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [PRIMARY_MODEL]
    assert all(model != FALLBACK_MODEL for model in stub.requested_models)


def test_invalid_primary_result_invokes_fallback_once(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(
        _invalid_payload(),
        _invalid_payload(),
        _valid_payload("Recovered by fallback"),
    )
    stub.install(monkeypatch)
    service = _service(stub, repository)

    result = _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        FALLBACK_MODEL,
    ]
    assert result.model == FALLBACK_MODEL
    assert result.repaired is True


def test_fallback_success_returns_expected_valid_result(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(
        _invalid_payload(),
        _invalid_payload(),
        _valid_payload("Fallback generated plan"),
    )
    stub.install(monkeypatch)
    service = _service(stub, repository)

    result = _plan(service, StubAnalysis(repository))

    assert result.title == "Fallback generated plan"
    assert result.summary.startswith("Change the existing feature flag")
    assert result.risk_level.value == "low"
    assert [file.path for file in result.files] == ["app.py"]
    assert [file.operation.value for file in result.files] == ["update"]
    assert [step.title for step in result.steps] == ["Update flag"]
    assert list(result.acceptance_criteria) == [
        "app.py contains FLAG = True and compiles."
    ]
    assert list(result.test_plan) == ["python -m py_compile app.py"]
    assert list(result.rollback_plan) == [
        "Restore the pre-apply backup if post-apply verification fails."
    ]
    assert result.repository_root == str(repository)
    assert result.model == FALLBACK_MODEL
    assert result.repaired is True
    assert result.generation_duration_seconds >= 0.0


def test_fallback_used_after_exhausted_primary_repairs(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(
        _invalid_payload(),
        _invalid_payload(),
        _invalid_payload(),
        _valid_payload("Recovered after repairs"),
    )
    stub.install(monkeypatch)
    service = _service(stub, repository, maximum_repair_attempts=2)

    result = _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        FALLBACK_MODEL,
    ]
    assert result.model == FALLBACK_MODEL


def test_fallback_failure_does_not_loop_indefinitely(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(
        _invalid_payload(),
        _invalid_payload(),
        _invalid_payload(),
    )
    stub.install(monkeypatch)
    service = _service(stub, repository)

    with pytest.raises(PlanningValidationError):
        _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        FALLBACK_MODEL,
    ]


def test_fallback_failure_is_bounded_by_repair_attempts(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(*[_invalid_payload() for _ in range(5)])
    stub.install(monkeypatch)
    service = _service(stub, repository, maximum_repair_attempts=3)

    with pytest.raises(PlanningValidationError):
        _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        FALLBACK_MODEL,
    ]


def test_fallback_can_be_disabled_via_configuration(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(_invalid_payload(), _invalid_payload())
    stub.install(monkeypatch)
    service = _service(stub, repository, fallback_model="")

    with pytest.raises(PlanningValidationError):
        _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [PRIMARY_MODEL, PRIMARY_MODEL]


def test_configuration_can_override_fallback_model(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(
        _invalid_payload(),
        _invalid_payload(),
        _valid_payload(),
    )
    stub.install(monkeypatch)
    service = _service(stub, repository, fallback_model="custom-fallback:8b")

    result = _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        "custom-fallback:8b",
    ]
    assert result.model == "custom-fallback:8b"


def test_generation_timeout_falls_back_once_and_recovers(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(
        OllamaTimeoutError("primary model timed out"),
        OllamaTimeoutError("primary repair attempt timed out"),
        _valid_payload("Recovered after timeout"),
    )
    stub.install(monkeypatch)
    service = _service(stub, repository)

    result = _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        FALLBACK_MODEL,
    ]
    assert result.model == FALLBACK_MODEL


def test_timeout_on_both_models_raises_validation_error(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(
        OllamaTimeoutError("primary model timed out"),
        OllamaTimeoutError("primary repair attempt timed out"),
        OllamaTimeoutError("fallback model timed out"),
    )
    stub.install(monkeypatch)
    service = _service(stub, repository)

    with pytest.raises(PlanningValidationError):
        _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [
        PRIMARY_MODEL,
        PRIMARY_MODEL,
        FALLBACK_MODEL,
    ]


def test_cancellation_is_not_swallowed_by_fallback(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = ScriptedOllama()
    stub.script_outcomes(OllamaRequestCancelledError("request cancelled"))
    stub.install(monkeypatch)
    service = _service(stub, repository)

    with pytest.raises(OllamaRequestCancelledError):
        _plan(service, StubAnalysis(repository))

    assert stub.requested_models == [PRIMARY_MODEL]


class StubAnalysis:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self.repository_name = repository_root.name
        self.analysis_id = "analysis-1"
        self.files = [StubAnalysisFile("app.py")]

