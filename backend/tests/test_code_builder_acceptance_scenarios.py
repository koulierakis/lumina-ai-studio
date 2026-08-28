"""Acceptance scenarios for the LUMINA Code Builder.

Scenario A: Successful execution flow - instruction → approval → execution → completion
Scenario B: Forced failure rollback - instruction → approval → execution fails → rollback
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from code_builder.backup_service import BackupService
from code_builder.build_service import BuildService, BuildServiceConfiguration
from code_builder.patch_service import PatchService
from code_builder.persistent_task_store import PersistentTaskStore
from code_builder.planning_service import GeneratedChangePlan, GeneratedFileChange, GeneratedPlanStep
from code_builder.router import CodeBuilderTaskPhase, create_code_builder_router
from code_builder.task_service import BuildPolicy, TaskService, TaskServiceConfiguration


class DeterministicRepository:
    def __init__(self, root: Path) -> None:
        self.repository_root = root

    def analyze_repository(self, **_):
        return {"repository_root": str(self.repository_root), "files": []}


class ScenarioAPlanner:
    """Deterministic planner that creates a simple file."""

    def __init__(self, path: str, content: str) -> None:
        self.path = path
        self.content = content
        self.calls = 0

    def plan(self, **_):
        self.calls += 1
        return GeneratedChangePlan(
            title="Acceptance scenario A: successful execution",
            summary="Create a smoke file to verify end-to-end success.",
            objective="Verify the Code Builder completes successfully.",
            risk_level="low",
            files=[
                GeneratedFileChange(
                    path=self.path,
                    operation="create",
                    summary="Create acceptance test file",
                    rationale="Verify success path",
                )
            ],
            steps=[
                GeneratedPlanStep(
                    order=1,
                    title="Create file",
                    description=f"Create {self.path} with acceptance content.",
                    file_paths=[self.path],
                    validation=["Verify file exists and contains expected content."],
                )
            ],
            acceptance_criteria=[
                f"File {self.path} exists.",
                f"File contains: {self.content!r}",
            ],
            test_plan=["Read file and verify contents."],
            rollback_plan=["Restore from backup if needed."],
        )


class ScenarioBPlanner:
    """Planner that creates a file that will fail to compile."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.calls = 0

    def plan(self, **_):
        self.calls += 1
        return GeneratedChangePlan(
            title="Acceptance scenario B: forced failure rollback",
            summary="Create a file with syntax error to trigger rollback.",
            objective="Verify rollback mechanism activates on build failure.",
            risk_level="medium",
            files=[
                GeneratedFileChange(
                    path=self.path,
                    operation="create",
                    summary="Create syntactically invalid file",
                    rationale="Trigger rollback for acceptance test",
                )
            ],
            steps=[
                GeneratedPlanStep(
                    order=1,
                    title="Create broken file",
                    description=f"Create {self.path} with intentional syntax error.",
                    file_paths=[self.path],
                    validation=["Compile should fail."],
                )
            ],
            acceptance_criteria=[
                f"File {self.path} does not exist after rollback.",
                "Rollback phase was entered.",
            ],
            test_plan=["Verify file was removed by rollback."],
            rollback_plan=["Remove the broken file."],
        )


class DummyOllamaService:
    """Dummy AI service for deterministic behavior."""

    model = "test-model"

    def analyze_code_task(self, **_):
        return "PASS: deterministic test review"


def _create_app(root: Path, path: str, planner):
    """Create a test FastAPI app with Code Builder router."""
    store = PersistentTaskStore(path=root / "tasks.db")
    service = TaskService(
        repository_service=DeterministicRepository(root),
        planning_service=planner,
        backup_service=BackupService(root),
        patch_service=PatchService(repository_root=root),
        build_service=BuildService(BuildServiceConfiguration(repository_root=root)),
        ollama_service=DummyOllamaService(),
        configuration=TaskServiceConfiguration(
            repository_root=root,
            use_default_build_sequence=False,
            include_ruff=False,
            include_mypy=False,
            include_frontend_tests=False,
            include_frontend_build=False,
        ),
    )
    app = FastAPI()
    app.include_router(
        create_code_builder_router(
            task_service=service,
            repository_service=DeterministicRepository(root),
            backup_service=service.backup_service,
            task_store=store,
        )
    )
    return app, store


def test_scenario_a_success_path(tmp_path: Path) -> None:
    """Scenario A: Verify successful execution from instruction to completion."""
    target_file = "scenario_a_result.txt"
    expected_content = "ACCEPTANCE_TEST_SUCCESS"

    app, _ = _create_app(tmp_path, target_file, ScenarioAPlanner(target_file, expected_content))

    with TestClient(app) as client:
        create_response = client.post(
            "/api/code-builder/tasks",
            json={
                "instruction": "Create acceptance test file for scenario A.",
                "target_paths": [target_file],
                "require_approval": True,
                "auto_start_after_approval": True,
                "build_policy": "disabled",
                "backup_policy": "required",
                "metadata": {
                    "patch_operations": [
                        {"operation": "create", "path": target_file, "content": f"{expected_content}\n"}
                    ]
                },
            },
        )
        assert create_response.status_code == 202, f"Task creation failed: {create_response.json()}"
        task_id = create_response.json()["task"]["task_id"]

        status = client.get(f"/api/code-builder/tasks/{task_id}").json()
        assert status["phase"] == "awaiting_approval", f"Expected awaiting_approval, got {status['phase']}"

        approve_response = client.post(
            f"/api/code-builder/tasks/{task_id}/approve",
            json={"decision": "approve", "start_immediately": True},
        )
        assert approve_response.status_code == 202, f"Approval failed: {approve_response.json()}"

        for _ in range(30):
            status = client.get(f"/api/code-builder/tasks/{task_id}").json()
            if status["phase"] == "completed":
                break
            time.sleep(0.1)

        assert status["phase"] == "completed", f"Task did not complete: {status}"

        result_file = tmp_path / target_file
        assert result_file.exists(), f"Result file {target_file} was not created"
        content = result_file.read_text(encoding="utf-8")
        assert expected_content in content, f"File content mismatch: {content!r}"


def test_scenario_b_rollback_on_build_failure(tmp_path: Path) -> None:
    """Scenario B: Verify rollback when build fails."""
    broken_file = "scenario_b_broken.py"
    content_with_syntax_error = "def broken(:\n    pass\n"

    app, _ = _create_app(tmp_path, broken_file, ScenarioBPlanner(broken_file))

    with TestClient(app) as client:
        create_response = client.post(
            "/api/code-builder/tasks",
            json={
                "instruction": "Create acceptance test file for scenario B (will fail).",
                "target_paths": [broken_file],
                "require_approval": True,
                "auto_start_after_approval": True,
                "build_policy": "required",
                "backup_policy": "required",
                "build_commands": [{"command_id": "compile", "kind": "python_compile", "arguments": [broken_file]}],
                "metadata": {
                    "patch_operations": [
                        {"operation": "create", "path": broken_file, "content": content_with_syntax_error}
                    ]
                },
            },
        )
        assert create_response.status_code == 202, f"Task creation failed: {create_response.json()}"
        task_id = create_response.json()["task"]["task_id"]

        status = client.get(f"/api/code-builder/tasks/{task_id}").json()
        assert status["phase"] == "awaiting_approval"

        approve_response = client.post(
            f"/api/code-builder/tasks/{task_id}/approve",
            json={"decision": "approve", "start_immediately": True},
        )
        assert approve_response.status_code == 202

        for _ in range(30):
            status = client.get(f"/api/code-builder/tasks/{task_id}").json()
            if status["phase"] in ("completed", "rolled_back", "failed"):
                break
            time.sleep(0.1)

        assert status["phase"] == "rolled_back", f"Expected rolled_back, got {status['phase']}: {status}"

        result_file = tmp_path / broken_file
        assert not result_file.exists(), f"Broken file {broken_file} should have been rolled back"
