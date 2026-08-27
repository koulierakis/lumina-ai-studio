from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from . import router as router_module
from .router import (
    CodeBuilderTaskPhase,
    StoredTask,
    TaskCreateRequest,
    TaskStore,
    _run_stored_task_sync,
    _serialize_value,
)
from .task_service import TaskCancellationToken, TaskRequest, TaskStatus


_DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / ".lumina-runtime"
    / "database"
    / "lumina.db"
)
_SAFE_RESTART_PHASES = {
    CodeBuilderTaskPhase.QUEUED,
    CodeBuilderTaskPhase.ANALYZING,
}
_UNSAFE_RESTART_PHASES = {
    CodeBuilderTaskPhase.EXECUTING,
    CodeBuilderTaskPhase.ROLLING_BACK,
}

_STORE_BY_TASK_ID: dict[str, "PersistentTaskStore"] = {}
_STORE_REGISTRY_LOCK = threading.RLock()
_ORIGINAL_TOUCH = StoredTask.touch
_TOUCH_INSTALLED = False
_CONFIGURE_INSTALLED = False
_ORIGINAL_CONFIGURE = router_module.configure_code_builder_router


def _install_touch_hook() -> None:
    global _TOUCH_INSTALLED
    if _TOUCH_INSTALLED:
        return

    def durable_touch(task: StoredTask) -> None:
        _ORIGINAL_TOUCH(task)
        with _STORE_REGISTRY_LOCK:
            store = _STORE_BY_TASK_ID.get(task.request.task_id)
        if store is not None:
            store.persist(task)

    StoredTask.touch = durable_touch
    _TOUCH_INSTALLED = True


class PersistentTaskStore(TaskStore):
    """SQLite-backed task snapshots compatible with the router TaskStore API."""

    def __init__(
        self,
        *,
        path: Path | str | None = None,
        max_stored_events: int = router_module.DEFAULT_MAX_STORED_EVENTS,
        retention_seconds: float = router_module.DEFAULT_TASK_RETENTION_SECONDS,
    ) -> None:
        _install_touch_hook()
        super().__init__(
            max_stored_events=max_stored_events,
            retention_seconds=retention_seconds,
        )
        configured_path = path or os.environ.get("LUMINA_CODE_BUILDER_DB_PATH")
        self.path = Path(configured_path).expanduser() if configured_path else _DEFAULT_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.RLock()
        self._initialize_schema()
        self._load_from_disk()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize_schema(self) -> None:
        with self._db_lock, self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS code_builder_tasks ("
                "task_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, "
                "updated_at_epoch REAL NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS code_builder_idempotency ("
                "idempotency_key TEXT PRIMARY KEY, task_id TEXT NOT NULL)"
            )
            connection.commit()

    def _snapshot(self, task: StoredTask) -> dict[str, Any]:
        return {
            "request": task.request.model_dump(mode="json"),
            "api_request": task.api_request.model_dump(mode="json"),
            "phase": task.phase.value,
            "created_at_epoch": task.created_at_epoch,
            "updated_at_epoch": task.updated_at_epoch,
            "require_approval": task.require_approval,
            "auto_start_after_approval": task.auto_start_after_approval,
            "result": _serialize_value(task.result),
            "preparation_result": _serialize_value(task.preparation_result),
            "review_result": _serialize_value(task.review_result),
            "started_at_epoch": task.started_at_epoch,
            "finished_at_epoch": task.finished_at_epoch,
            "approved_at_epoch": task.approved_at_epoch,
            "approval_comment": task.approval_comment,
            "rollback_requested": task.rollback_requested,
            "rollback_result": _serialize_value(task.rollback_result),
            "events": _serialize_value(task.events) or [],
            "metadata": _serialize_value(task.metadata) or {},
        }

    def _restore(self, payload: dict[str, Any]) -> StoredTask:
        request = TaskRequest.model_validate(payload["request"])
        return StoredTask(
            request=request,
            api_request=TaskCreateRequest.model_validate(payload["api_request"]),
            phase=CodeBuilderTaskPhase(payload["phase"]),
            created_at_epoch=float(payload["created_at_epoch"]),
            updated_at_epoch=float(payload["updated_at_epoch"]),
            require_approval=bool(payload.get("require_approval", True)),
            auto_start_after_approval=bool(payload.get("auto_start_after_approval", True)),
            cancellation_token=TaskCancellationToken(task_id=request.task_id),
            result=payload.get("result"),
            preparation_result=payload.get("preparation_result"),
            review_result=payload.get("review_result"),
            started_at_epoch=payload.get("started_at_epoch"),
            finished_at_epoch=payload.get("finished_at_epoch"),
            approved_at_epoch=payload.get("approved_at_epoch"),
            approval_comment=payload.get("approval_comment"),
            rollback_requested=bool(payload.get("rollback_requested", False)),
            rollback_result=payload.get("rollback_result"),
            events=list(payload.get("events") or []),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _load_from_disk(self) -> None:
        with self._db_lock, self._connect() as connection:
            task_rows = connection.execute(
                "SELECT payload_json FROM code_builder_tasks"
            ).fetchall()
            idempotency_rows = connection.execute(
                "SELECT idempotency_key, task_id FROM code_builder_idempotency"
            ).fetchall()

        with self._lock:
            for row in task_rows:
                try:
                    task = self._restore(json.loads(row["payload_json"]))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                self._tasks[task.request.task_id] = task
                with _STORE_REGISTRY_LOCK:
                    _STORE_BY_TASK_ID[task.request.task_id] = self
            for row in idempotency_rows:
                if row["task_id"] in self._tasks:
                    self._idempotency_keys[row["idempotency_key"]] = row["task_id"]

        self._apply_restart_policy()

    def _apply_restart_policy(self) -> None:
        for task in tuple(self._tasks.values()):
            interrupted_phase = task.phase
            if interrupted_phase in _SAFE_RESTART_PHASES:
                task.phase = CodeBuilderTaskPhase.QUEUED
                task.finished_at_epoch = None
                task.metadata["recovery_state"] = "restart_resume_preparation"
                task.metadata["interrupted_phase"] = interrupted_phase.value
                task.touch()
            elif interrupted_phase is CodeBuilderTaskPhase.APPROVED:
                task.metadata["recovery_state"] = "restart_resume_approved"
                task.touch()
            elif interrupted_phase in _UNSAFE_RESTART_PHASES:
                task.phase = CodeBuilderTaskPhase.FAILED
                task.finished_at_epoch = task.updated_at_epoch
                task.metadata["recovery_state"] = "interrupted_requires_manual_review"
                task.metadata["interrupted_phase"] = interrupted_phase.value
                task.metadata["safe_to_auto_resume"] = False
                task.result = {
                    "task_id": task.request.task_id,
                    "status": TaskStatus.FAILED.value,
                    "success": False,
                    "error_type": "BackendRestartInterruption",
                    "error_message": (
                        "The backend restarted after mutation may have begun; "
                        "automatic replay was blocked."
                    ),
                }
                task.touch()

    def persist(self, task: StoredTask) -> None:
        payload = json.dumps(self._snapshot(task), ensure_ascii=False, separators=(",", ":"), default=str)
        with self._db_lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO code_builder_tasks(task_id, payload_json, updated_at_epoch) "
                "VALUES (?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET "
                "payload_json=excluded.payload_json, updated_at_epoch=excluded.updated_at_epoch",
                (task.request.task_id, payload, float(task.updated_at_epoch)),
            )
            connection.commit()

    def create(self, stored_task: StoredTask, *, idempotency_key: str | None = None) -> StoredTask:
        created = super().create(stored_task, idempotency_key=idempotency_key)
        with _STORE_REGISTRY_LOCK:
            _STORE_BY_TASK_ID[created.request.task_id] = self
        self.persist(created)
        if idempotency_key:
            with self._db_lock, self._connect() as connection:
                connection.execute(
                    "INSERT INTO code_builder_idempotency(idempotency_key, task_id) VALUES (?, ?) "
                    "ON CONFLICT(idempotency_key) DO UPDATE SET task_id=excluded.task_id",
                    (idempotency_key, created.request.task_id),
                )
                connection.commit()
        return created

    def append_event(self, task_id: str, event: Any) -> None:
        super().append_event(task_id, event)
        try:
            self.persist(self.get(task_id))
        except Exception:
            pass

    def remove(self, task_id: str) -> bool:
        removed = super().remove(task_id)
        if not removed:
            return False
        with _STORE_REGISTRY_LOCK:
            _STORE_BY_TASK_ID.pop(task_id, None)
        with self._db_lock, self._connect() as connection:
            connection.execute("DELETE FROM code_builder_tasks WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM code_builder_idempotency WHERE task_id = ?", (task_id,))
            connection.commit()
        return True

    def tasks_for_automatic_resume(self) -> tuple[StoredTask, ...]:
        return tuple(
            task for task in self._tasks.values()
            if task.metadata.get("recovery_state") in {
                "restart_resume_preparation",
                "restart_resume_approved",
            }
        )


def _resume_safe_tasks(store: PersistentTaskStore, task_service: Any) -> None:
    for task in store.tasks_for_automatic_resume():
        task.metadata["recovery_state"] = "restart_resume_scheduled"
        task.touch()
        worker = threading.Thread(
            target=_run_stored_task_sync,
            kwargs={"task_service": task_service, "task_store": store, "stored_task": task},
            name=f"lumina-code-builder-recovery-{task.request.task_id[:8]}",
            daemon=True,
        )
        worker.start()


def install_persistent_task_store() -> None:
    global _CONFIGURE_INSTALLED
    if _CONFIGURE_INSTALLED:
        return

    def configure_with_persistence(*, task_service: Any, repository_service: Any, backup_service: Any, task_store: TaskStore | None = None) -> Any:
        store = task_store or PersistentTaskStore()
        dependencies = _ORIGINAL_CONFIGURE(
            task_service=task_service,
            repository_service=repository_service,
            backup_service=backup_service,
            task_store=store,
        )
        if isinstance(store, PersistentTaskStore):
            _resume_safe_tasks(store, task_service)
        return dependencies

    router_module.configure_code_builder_router = configure_with_persistence
    _CONFIGURE_INSTALLED = True
