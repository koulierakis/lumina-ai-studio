from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .models import BuildTask, Project


@dataclass
class JsonTaskStore:
    path: Path

    def __post_init__(self) -> None:
        self.path = self.path.resolve()
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> dict[str, BuildTask]:
        with self._lock:
            if not self.path.exists():
                return {}
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {task_id: BuildTask.model_validate(payload) for task_id, payload in raw.items()}

    def save_all(self, tasks: dict[str, BuildTask]) -> None:
        payload = {task_id: task.model_dump(mode="json") for task_id, task in tasks.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with self._lock:
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)


@dataclass
class JsonProjectStore:
    path: Path

    def __post_init__(self) -> None:
        self.path = self.path.resolve()
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> dict[str, Project]:
        with self._lock:
            if not self.path.exists():
                return {}
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {project_id: Project.model_validate(payload) for project_id, payload in raw.items()}

    def save_all(self, projects: dict[str, Project]) -> None:
        payload = {project_id: project.model_dump(mode="json") for project_id, project in projects.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with self._lock:
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    def get(self, project_id: str) -> Project | None:
        with self._lock:
            projects = self.load_all()
            return projects.get(project_id)

    def save(self, project: Project) -> None:
        with self._lock:
            projects = self.load_all()
            projects[project.id] = project
            self.save_all(projects)

    def delete(self, project_id: str) -> bool:
        with self._lock:
            projects = self.load_all()
            if project_id in projects:
                del projects[project_id]
                self.save_all(projects)
                return True
            return False
