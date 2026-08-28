from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_builder.backup_service import BackupService
from code_builder.build_service import (
    BuildCommandKind,
    BuildCommandSpec,
    BuildService,
    BuildServiceConfiguration,
    BuildStatus,
)
from code_builder.patch_generation_service import install_ai_patch_generation
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


class StaticRepositoryService:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root

    def analyze_repository(self) -> dict[str, object]:
        return {
            "repository_root": str(self.repository_root),
            "files": ["app.py"],
        }


class StaticPlanningService:
    def __init__(self, plan: GeneratedChangePlan) -> None:
        self.generated_plan = plan

    def plan(self, **_: object) -> GeneratedChangePlan:
        return self.generated_plan


def _plan() -> GeneratedChangePlan:
    return GeneratedChangePlan(
        title="Enable feature flag",
        summary="Change the existing feature flag from false to true.",
        objective="Apply the requested behavior without changing unrelated files.",
        risk_level="low",
        files=[
            GeneratedFileChange(
                path="app.py",
                operation="modify",
                summary="Enable the existing feature flag.",
                rationale="The user explicitly requested the flag change.",
            )
        ],
        steps=[
            GeneratedPlanStep(
                order=1,
                title="Update flag",
                description="Change FLAG from False to True in app.py.",
                file_paths=["app.py"],
                validation=["Compile app.py successfully."],
            )
        ],
        acceptance_criteria=["app.py contains FLAG = True and compiles."],
        test_plan=["python -m py_compile app.py"],
        rollback_plan=["Restore app.py from the automatic backup."],
    )


def _service(repository_root: Path) -> TaskService:
    install_ai_patch_generation()
    return TaskService(
        repository_service=StaticRepositoryService(repository_root),
        planning_service=StaticPlanningService(_plan()),
        backup_service=BackupService(repository_root),
        patch_service=PatchService(repository_root=repository_root),
        build_service=BuildService(
            BuildServiceConfiguration(
                repository_root=repository_root,
                custom_command_policy={"executable_paths": frozenset({sys.executable})},
            )
        ),
        ollama_service=SimpleNamespace(model="test-coder"),
        configuration=TaskServiceConfiguration(
            repository_root=repository_root,
            use_default_build_sequence=False,
            include_ruff=False,
            include_mypy=False,
            include_frontend_tests=False,
            include_frontend_build=False,
        ),
    )


def _install_fake_ollama(monkeypatch: pytest.MonkeyPatch, replacement: str) -> None:
    generated_patch = {
        "operations": [
            {
                "operation": "replace_text",
                "path": "app.py",
                "content": None,
                "search_text": "FLAG = False",
                "replacement_text": replacement,
                "unified_diff": None,
                "description": "Apply the requested feature flag change.",
            }
        ],
        "description": "Structured patch generated from the approved plan.",
    }
    envelope = json.dumps(
        {"response": json.dumps(generated_patch)},
        ensure_ascii=False,
    ).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit: int = -1) -> bytes:
            return envelope

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:11434/api/generate"
        assert timeout > 0
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model"] == "test-coder"
        assert payload["format"]["type"] == "object"
        assert payload["options"]["temperature"] == 0
        assert "Change FLAG = False to FLAG = True" in payload["prompt"]
        assert "FILE: app.py" in payload["prompt"]
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def _request() -> TaskRequest:
    return TaskRequest(
        instruction="Change FLAG = False to FLAG = True in app.py and verify it compiles.",
        target_paths=("app.py",),
        metadata={},
        build_commands=(
            BuildCommandSpec(
                command_id="compile-app",
                kind=BuildCommandKind.PYTHON_COMPILE,
                arguments=("app.py",),
                timeout_seconds=60,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
        allow_file_creation=False,
    )


def test_prompt_only_task_generates_applies_and_verifies_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "app.py"
    target.write_text("# feature flag\nFLAG = False\n", encoding="utf-8")
    _install_fake_ollama(monkeypatch, "FLAG = True")

    events: list[str] = []
    result = _service(tmp_path).execute_internal(
        _request(),
        event_callback=lambda event: events.append(event.stage.value),
    )

    assert result.status is TaskStatus.SUCCEEDED, (
        f"error_type={result.error_type}; error_message={result.error_message}; "
        f"rollback_attempted={result.rollback_attempted}"
    )
    assert target.read_text(encoding="utf-8") == "# feature flag\nFLAG = True\n"
    assert result.backup is not None
    assert result.patch_validation is not None
    assert result.patch_application is not None
    assert result.patch_application.successful
    assert result.build_result is not None
    assert result.build_result.status is BuildStatus.SUCCEEDED
    assert result.rollback_attempted is False
    assert result.changed_paths == ("app.py",)
    assert "backup" in events
    assert "patch_generation" in events
    assert "patch_validation" in events
    assert "patch_application" in events
    assert "build" in events


def test_prompt_only_task_rolls_back_when_generated_change_fails_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "app.py"
    original = "# feature flag\nFLAG = False\n"
    target.write_text(original, encoding="utf-8")
    _install_fake_ollama(monkeypatch, "FLAG =")

    result = _service(tmp_path).execute_internal(_request())

    assert result.status is TaskStatus.ROLLED_BACK, (
        f"error_type={result.error_type}; error_message={result.error_message}; "
        f"rollback_attempted={result.rollback_attempted}; "
        f"rollback_succeeded={result.rollback_succeeded}"
    )
    assert result.rollback_attempted is True
    assert result.rollback_succeeded is True
    assert result.rollback_result is not None
    assert target.read_text(encoding="utf-8") == original
