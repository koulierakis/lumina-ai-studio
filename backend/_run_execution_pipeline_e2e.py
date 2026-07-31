from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from code_builder.backup_service import BackupService
from code_builder.build_service import (
    BuildCommandKind,
    BuildCommandSpec,
    BuildService,
    BuildServiceConfiguration,
    BuildStatus,
)
from code_builder.models import RepositoryConfiguration
from code_builder.patch_service import PatchService
from code_builder.planning_service import (
    GeneratedChangePlan,
    GeneratedFileChange,
    GeneratedPlanStep,
)
from code_builder.repository_service import RepositoryService
from code_builder.task_service import (
    BackupPolicy,
    RollbackPolicy,
    TaskRequest,
    TaskService,
    TaskServiceConfiguration,
)


class ApprovedPlanningService:
    def __init__(self, plan: GeneratedChangePlan) -> None:
        self.generated_plan = plan

    def plan(self, **_: object) -> GeneratedChangePlan:
        return self.generated_plan


class ApprovedOllamaService:
    pass


def main() -> int:
    repository_root = Path(__file__).resolve().parent.parent
    relative_path = "backend/tests/test_health_check_unit.py"
    target_path = repository_root / relative_path
    if target_path.exists():
        raise RuntimeError(f"Target already exists: {relative_path}")

    new_content = (
        "from __future__ import annotations\n\n"
        "import asyncio\n\n"
        "from server import health\n\n\n"
        "def test_backend_health_check_contract(monkeypatch):\n"
        "    async def fake_statuses():\n"
        "        return {'mock': {'status': 'ok'}}\n\n"
        "    async def fake_health_summary():\n"
        "        return {'healthy': True}\n\n"
        "    monkeypatch.setattr('server.provider_manager.statuses', fake_statuses)\n"
        "    monkeypatch.setattr(\n"
        "        'server.provider_manager.health_summary',\n"
        "        fake_health_summary,\n"
        "    )\n"
        "    monkeypatch.setattr('server.available_providers', lambda: ['mock'])\n"
        "    monkeypatch.setattr('server.now_iso', lambda: '2026-01-01T00:00:00Z')\n\n"
        "    payload = asyncio.run(health())\n\n"
        "    assert payload['status'] == 'ok'\n"
        "    assert payload['backend'] == 'ok'\n"
        "    assert payload['providers_available'] == ['mock']\n"
    )

    plan = GeneratedChangePlan(
        title="Add backend health-check unit test",
        summary="Create a focused backend health-check unit test.",
        objective="Validate health-check response shape without public API changes.",
        risk_level="low",
        files=[
            GeneratedFileChange(
                path=relative_path,
                operation="create",
                summary="Add health-check unit test.",
                rationale="The approved task requested backend health-check unit coverage.",
            )
        ],
        steps=[
            GeneratedPlanStep(
                order=1,
                title="Create test file",
                description="Add a focused unit test for the backend health endpoint contract.",
                file_paths=[relative_path],
                validation=["Run pytest for backend/tests/test_health_check_unit.py."],
            )
        ],
        acceptance_criteria=["The new backend health-check unit test passes."],
        test_plan=["python -m pytest tests/test_health_check_unit.py -q"],
        rollback_plan=["Restore the automatic backup if validation fails."],
    )

    task_service = TaskService(
        repository_service=RepositoryService(
            RepositoryConfiguration(repository_root=str(repository_root))
        ),
        planning_service=ApprovedPlanningService(plan),
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
        ollama_service=ApprovedOllamaService(),
        configuration=TaskServiceConfiguration(
            repository_root=repository_root,
            use_default_build_sequence=False,
        ),
    )

    request = TaskRequest(
        instruction="Add a backend health-check unit test without changing public APIs.",
        target_paths=(relative_path,),
        metadata={
            "approved": True,
            "patch_operations": [
                {
                    "operation": "create",
                    "path": relative_path,
                    "content": new_content,
                    "description": "Create backend health-check unit test.",
                }
            ],
        },
        build_commands=(
            BuildCommandSpec(
                command_id="backend-health-check-unit",
                kind=BuildCommandKind.PYTEST,
                arguments=("tests/test_health_check_unit.py", "-q"),
                working_directory="backend",
                timeout_seconds=120,
            ),
        ),
        backup_policy=BackupPolicy.REQUIRED,
        rollback_policy=RollbackPolicy.ON_ANY_FAILURE,
    )

    events = []
    started = time.perf_counter()
    result = task_service.execute_internal(
        request,
        event_callback=lambda event: events.append(event.model_dump(mode="python")),
    )
    duration = time.perf_counter() - started

    rollback_events = [event for event in events if event["stage"] == "rollback"]
    rollback_duration = 0.0
    if result.rollback_result is not None and rollback_events:
        rollback_duration = max(
            0.0,
            rollback_events[-1]["timestamp_epoch"] - rollback_events[0]["timestamp_epoch"],
        )

    tests_executed = 0
    tests_passed = 0
    if result.build_result is not None:
        tests_executed = len(result.build_result.commands)
        tests_passed = sum(
            1
            for command in result.build_result.commands
            if command.status is BuildStatus.SUCCEEDED
        )

    payload = {
        "execution_duration_seconds": duration,
        "files_modified": list(result.changed_paths),
        "backups_created": 1 if result.backup is not None else 0,
        "backup_id": getattr(result.backup, "backup_id", None),
        "diff_generated": bool(
            result.patch_application
            and result.patch_application.results
            and result.patch_application.results[0].diff
        ),
        "tests_executed": tests_executed,
        "tests_passed": tests_passed,
        "rollback_triggered": result.rollback_attempted,
        "rollback_duration_seconds": rollback_duration,
        "final_task_status": result.status.value,
        "event_count": len(events),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
