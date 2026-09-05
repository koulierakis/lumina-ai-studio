from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from code_builder.backup_service import BackupService
from code_builder.build_service import BuildService, BuildServiceConfiguration
from code_builder.patch_service import PatchService
from code_builder.persistent_task_store import PersistentTaskStore
from code_builder.planning_service import GeneratedChangePlan, GeneratedFileChange, GeneratedPlanStep
from code_builder.router import CodeBuilderTaskPhase, StoredTask, TaskCreateRequest, create_code_builder_router
from code_builder.task_service import TaskCancellationToken, TaskRequest, TaskService, TaskServiceConfiguration


class DeterministicRepository:
    def __init__(self, root: Path, delay: float = 0.0) -> None:
        self.repository_root = root
        self.delay = delay

    def analyze_repository(self, **_: object) -> dict[str, object]:
        if self.delay:
            time.sleep(self.delay)
        return {"repository_root": str(self.repository_root), "files": []}


class DeterministicPlanner:
    def __init__(self, path: str) -> None:
        self.path = path
        self.calls = 0

    def plan(self, **_: object) -> GeneratedChangePlan:
        self.calls += 1
        return GeneratedChangePlan(
            title="Runtime verification change",
            summary="Create one disposable runtime verification file.",
            objective="Verify the real API transaction loop.",
            risk_level="low",
            files=[GeneratedFileChange(path=self.path, operation="create", summary="Create disposable file", rationale="Runtime test")],
            steps=[GeneratedPlanStep(order=1, title="Create file", description="Create disposable file", file_paths=[self.path], validation=["Compile the file"])],
            acceptance_criteria=["The file is created after approval."],
            test_plan=["Compile the file."],
            rollback_plan=["Restore the automatic backup."],
        )


class DeterministicReview:
    model = "runtime-test"

    def analyze_code_task(self, **_: object) -> str:
        return "PASS: deterministic runtime review"


def _runtime_app(root: Path, store: PersistentTaskStore, path: str, delay: float = 0.0):
    repository = DeterministicRepository(root, delay=delay)
    planner = DeterministicPlanner(path)
    service = TaskService(
        repository_service=repository,
        planning_service=DeterministicPlanner(path),
        backup_service=BackupService(root),
        patch_service=PatchService(repository_root=root),
        build_service=BuildService(BuildServiceConfiguration(repository_root=root)),
        ollama_service=DeterministicReview(),
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
    app.include_router(create_code_builder_router(
        task_service=service,
        repository_service=repository,
        backup_service=service.backup_service,
        task_store=store,
    ))
    return app, service, planner


def test_real_router_full_loop_reconnect_cancel_and_rollback(tmp_path: Path) -> None:
    path = "runtime_created.py"
    store = PersistentTaskStore(path=tmp_path / "runtime.db")
    app, service, _ = _runtime_app(tmp_path, store, path)

    with TestClient(app) as client:
        payload = {
            "instruction": "Create one harmless disposable runtime verification file.",
            "target_paths": [path],
            "require_approval": True,
            "auto_start_after_approval": True,
            "build_policy": "disabled",
            "backup_policy": "required",
            "metadata": {"patch_operations": [{"operation": "create", "path": path, "content": "RUNTIME_OK = True\n"}]},
        }
        first = client.post("/api/code-builder/tasks", json=payload, headers={"Idempotency-Key": "runtime-loop"})
        second = client.post("/api/code-builder/tasks", json=payload, headers={"Idempotency-Key": "runtime-loop"})
        assert first.status_code == 202
        assert second.status_code == 202
        task_id = first.json()["task"]["task_id"]
        assert second.json()["task"]["task_id"] == task_id

        prepared = client.get(f"/api/code-builder/tasks/{task_id}").json()
        assert prepared["phase"] == "awaiting_approval"
        assert len(prepared["events"]) >= 4
        assert client.get("/api/code-builder/tasks").json()["items"][0]["task_id"] == task_id

        approved = client.post(f"/api/code-builder/tasks/{task_id}/approve", json={"decision": "approve", "start_immediately": True})
        assert approved.status_code == 202
        completed = client.get(f"/api/code-builder/tasks/{task_id}").json()
        for _ in range(20):
            if completed["phase"] == "completed":
                break
            time.sleep(0.05)
            completed = client.get(f"/api/code-builder/tasks/{task_id}").json()
        assert completed["phase"] == "completed"
        assert (tmp_path / path).read_text(encoding="utf-8") == "RUNTIME_OK = True\n"

        rollback = client.post(
            f"/api/code-builder/tasks/{task_id}/rollback",
            json={"reason": "runtime manual rollback verification"},
        )
        assert rollback.status_code == 200
        rolled_back = client.get(f"/api/code-builder/tasks/{task_id}").json()
        assert rolled_back["phase"] == "rolled_back"
        assert not (tmp_path / path).exists()

        reconnect_store = PersistentTaskStore(path=tmp_path / "runtime.db")
        restored = reconnect_store.get(task_id)
        assert restored.request.task_id == task_id
        assert restored.phase is CodeBuilderTaskPhase.ROLLED_BACK

        cancel_path = "cancelled.py"
        cancel_store = PersistentTaskStore(path=tmp_path / "cancel.db")
        cancel_app, cancel_service, _ = _runtime_app(tmp_path, cancel_store, cancel_path, delay=2.0)
        cancel_request = TaskRequest(
            task_id="cancel-runtime",
            instruction="cancel runtime task",
            target_paths=(cancel_path,),
            allow_file_creation=True,
            metadata={"patch_operations": []},
        )
        cancel_task = StoredTask(
            request=cancel_request,
            api_request=TaskCreateRequest(
                instruction="cancel runtime task",
                target_paths=(cancel_path,),
                require_approval=False,
                auto_start_after_approval=False,
                build_policy="disabled",
                metadata={"patch_operations": []},
            ),
            phase=CodeBuilderTaskPhase.QUEUED,
            created_at_epoch=time.time(),
            updated_at_epoch=time.time(),
            require_approval=False,
            auto_start_after_approval=False,
            cancellation_token=TaskCancellationToken(task_id="cancel-runtime"),
        )
        cancel_store.create(cancel_task)
        worker = threading.Thread(
            target=cancel_service.execute,
            args=(cancel_task.request,),
            kwargs={"cancellation_token": cancel_task.cancellation_token, "return_domain_model": False},
            daemon=True,
        )
        worker.start()
        time.sleep(0.1)
        with TestClient(cancel_app) as cancel_client:
            response = cancel_client.post("/api/code-builder/tasks/cancel-runtime/cancel", json={"reason": "runtime cancellation"})
            assert response.status_code == 200
            assert cancel_task.cancellation_token.is_cancelled()
        worker.join(timeout=5)

        broken = "broken.py"
        broken_store = PersistentTaskStore(path=tmp_path / "rollback.db")
        broken_app, _, _ = _runtime_app(tmp_path, broken_store, broken)
        broken_payload = {
            **payload,
            "target_paths": [broken],
            "build_policy": "required",
            "build_commands": [{"command_id": "compile", "kind": "python_compile", "arguments": [broken]}],
            "metadata": {"patch_operations": [{"operation": "create", "path": broken, "content": "def broken(:\n"}]},
        }
        created = client.post("/api/code-builder/tasks", json=broken_payload).json()["task"]["task_id"]
        assert client.post(f"/api/code-builder/tasks/{created}/approve", json={"decision": "approve", "start_immediately": True}).status_code == 202
        failed = client.get(f"/api/code-builder/tasks/{created}").json()
        for _ in range(20):
            if failed["phase"] == "rolled_back":
                break
            time.sleep(0.05)
            failed = client.get(f"/api/code-builder/tasks/{created}").json()
        assert failed["phase"] == "rolled_back"
        assert not (tmp_path / broken).exists()
        assert failed["phase"] == "rolled_back"
        assert not (tmp_path / broken).exists()


def test_real_router_timeout_produces_terminal_timed_out_state(tmp_path: Path) -> None:
    path = "timeout_created.py"
    store = PersistentTaskStore(path=tmp_path / "timeout.db")
    app, _, _ = _runtime_app(tmp_path, store, path, delay=1.0)

    with TestClient(app) as client:
        payload = {
            "instruction": "Timeout runtime verification task.",
            "target_paths": [path],
            "require_approval": True,
            "auto_start_after_approval": True,
            "task_timeout_seconds": 0.5,
            "build_policy": "disabled",
            "backup_policy": "required",
            "metadata": {"patch_operations": [{"operation": "create", "path": path, "content": "TIMEOUT_OK = True\n"}]},
        }
        created = client.post("/api/code-builder/tasks", json=payload, headers={"Idempotency-Key": "timeout-loop"})
        assert created.status_code == 202
        task_id = created.json()["task"]["task_id"]

        detail = client.get(f"/api/code-builder/tasks/{task_id}").json()
        for _ in range(80):
            if detail["phase"] in {"timed_out", "completed", "failed", "rolled_back", "rollback_failed"}:
                break
            time.sleep(0.05)
            detail = client.get(f"/api/code-builder/tasks/{task_id}").json()

        assert detail["phase"] == "timed_out"
        assert detail["result"] is not None
        assert detail["result"]["status"] == "timed_out"
        timeout_message = str(detail["result"].get("error_message", "")).lower()
        assert "timed out" in timeout_message or "timeout" in timeout_message
        assert not (tmp_path / path).exists()

    restored = PersistentTaskStore(path=tmp_path / "timeout.db").get(task_id)
    assert restored.phase is CodeBuilderTaskPhase.TIMED_OUT
    assert restored.finished_at_epoch is not None

