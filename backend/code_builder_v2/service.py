from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from .models import BuildTask, ExecutionReport, TaskRequest, TaskStatus
from .pipeline import ExecutionPipeline
from .planner import Planner
from .store import JsonTaskStore


class TaskNotFound(KeyError):
    pass


class InvalidTaskState(RuntimeError):
    pass


@dataclass
class CodeBuilderService:
    planner: Planner
    store: JsonTaskStore | None = None
    pipeline: ExecutionPipeline | None = None
    _tasks: dict[str, BuildTask] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def __post_init__(self) -> None:
        if self.store is not None:
            self._tasks = self.store.load_all()

    def _persist(self) -> None:
        if self.store is not None:
            self.store.save_all(self._tasks)

    def create_task(self, request: TaskRequest) -> BuildTask:
        task = BuildTask(request=request)
        task.transition(TaskStatus.queued, "Task created")
        with self._lock:
            self._tasks[task.id] = task
            self._persist()
        task = self.plan_task(task.id)
        if request.auto_apply and task.status is TaskStatus.awaiting_approval:
            task = self.execute_task(task.id)
        return task

    def get_task(self, task_id: str) -> BuildTask:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        return task

    def plan_task(self, task_id: str) -> BuildTask:
        task = self.get_task(task_id)
        task.transition(TaskStatus.planning, "Creating structured change plan")
        try:
            task.plan = self.planner.create_plan(task.request)
            task.transition(TaskStatus.awaiting_approval, "Plan ready for approval")
        except Exception as exc:
            task.error = str(exc)
            task.transition(TaskStatus.failed, "Planning failed")
        with self._lock:
            self._persist()
        return task

    def execute_task(self, task_id: str) -> BuildTask:
        task = self.get_task(task_id)
        if task.status is not TaskStatus.awaiting_approval:
            raise InvalidTaskState(f"Task must be awaiting approval, got {task.status.value}")
        if task.plan is None:
            raise InvalidTaskState("Task has no approved plan")
        if self.pipeline is None:
            raise InvalidTaskState("Execution pipeline is not configured")

        task.error = None
        task.transition(TaskStatus.executing, "Generating and applying approved changes")
        with self._lock:
            self._persist()
        try:
            result = self.pipeline.execute(task.request, task.plan)
            task.transition(TaskStatus.validating, "Validation completed successfully")
            task.execution = ExecutionReport(
                backup_id=result.backup_id,
                changed_paths=list(result.changed_paths),
                validation_commands=list(result.validation_commands),
            )
            task.transition(TaskStatus.completed, "Task completed")
        except Exception as exc:
            task.error = str(exc)
            task.transition(TaskStatus.failed, "Execution failed")
        with self._lock:
            self._persist()
        return task

    def cancel_task(self, task_id: str) -> BuildTask:
        task = self.get_task(task_id)
        if task.status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.rolled_back}:
            return task
        task.transition(TaskStatus.cancelled, "Task cancelled")
        with self._lock:
            self._persist()
        return task

    def rollback_task(self, task_id: str) -> BuildTask:
        task = self.get_task(task_id)
        if self.pipeline is None:
            raise InvalidTaskState("Execution pipeline is not configured")
        if task.execution is None:
            raise InvalidTaskState("Task has no completed execution to roll back")
        self.pipeline.applier.rollback(task.execution.backup_id)
        task.transition(TaskStatus.rolled_back, "Repository restored from backup")
        with self._lock:
            self._persist()
        return task
