from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from .models import BuildTask, TaskRequest, TaskStatus
from .planner import Planner
from .store import JsonTaskStore


class TaskNotFound(KeyError):
    pass


@dataclass
class CodeBuilderService:
    planner: Planner
    store: JsonTaskStore | None = None
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

    def cancel_task(self, task_id: str) -> BuildTask:
        task = self.get_task(task_id)
        if task.status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.rolled_back}:
            return task
        task.transition(TaskStatus.cancelled, "Task cancelled")
        with self._lock:
            self._persist()
        return task
