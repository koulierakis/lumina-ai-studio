from __future__ import annotations

import asyncio
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .browser_evidence import BrowserEvidenceCollector, run_browser_check, run_browser_interaction
from .dev_server_manager import DevServerManager
from .models import (
    BrowserEvidence,
    DevServerInfo,
    DevServerStatus,
    FrameworkType,
    Project,
    ProjectStatus,
    TaskRequest,
    TaskStatus,
)
from .project_generator import (
    create_project_from_prompt,
    detect_framework,
    install_dependencies,
    find_free_port,
    get_dev_server_command,
)
from .store import JsonProjectStore


class ProjectNotFound(KeyError):
    pass


class InvalidProjectState(RuntimeError):
    pass


@dataclass
class ProjectService:
    """Service for managing the full lifecycle of a generated project."""

    project_store: JsonProjectStore
    runtime_root: Path
    _dev_server_manager: DevServerManager = field(init=False)
    _projects: dict[str, Project] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._dev_server_manager = DevServerManager(self.runtime_root)
        self._projects = self.project_store.load_all()

    def _persist_project(self, project: Project) -> None:
        self.project_store.save(project)

    def create_project(
        self,
        prompt: str,
        project_name: str | None = None,
        framework_hint: str | None = None,
    ) -> Project:
        """Create a new project from a natural language prompt."""
        project = create_project_from_prompt(
            prompt=prompt,
            project_name=project_name,
            framework_hint=framework_hint,
        )
        project.transition(ProjectStatus.generating, "Generating project files")
        with self._lock:
            self._projects[project.id] = project
        self._persist_project(project)
        return project

    def get_project(self, project_id: str) -> Project:
        with self._lock:
            project = self._projects.get(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project

    def list_projects(self) -> list[Project]:
        with self._lock:
            return list(self._projects.values())

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            project = self._projects.pop(project_id, None)
        if project is None:
            return False
        self.project_store.delete(project_id)
        return True

    def install_dependencies(self, project_id: str) -> tuple[bool, str]:
        """Install dependencies for a project."""
        project = self.get_project(project_id)
        project.transition(ProjectStatus.installing_deps, "Installing dependencies")
        self._persist_project(project)

        success, output = install_dependencies(project)
        if success:
            project.transition(ProjectStatus.generating, "Dependencies installed successfully")
        else:
            project.transition(ProjectStatus.failed, f"Dependency installation failed: {output}")
        self._persist_project(project)
        return success, output

    def start_dev_server(self, project_id: str, timeout: int = 60) -> DevServerInfo:
        """Start the dev server for a project."""
        project = self.get_project(project_id)
        project.transition(ProjectStatus.starting_server, "Starting dev server")
        self._persist_project(project)

        server_info = self._dev_server_manager.start_server(project, timeout=timeout)
        project.dev_server = server_info
        project.transition(ProjectStatus.running, "Dev server running")
        self._persist_project(project)
        return server_info

    def stop_dev_server(self, project_id: str) -> bool:
        """Stop the dev server for a project."""
        project = self.get_project(project_id)
        success = self._dev_server_manager.stop_server(project.id)
        if success:
            project.dev_server.status = DevServerStatus.stopped
            project.transition(ProjectStatus.stopped, "Dev server stopped")
            self._persist_project(project)
        return success

    def get_dev_server_info(self, project_id: str) -> DevServerInfo | None:
        return self._dev_server_manager.get_server_info(project_id)

    def get_dev_server_logs(self, project_id: str) -> str:
        return self._dev_server_manager.get_logs(project_id)

    def run_browser_check(
        self,
        project_id: str,
        wait_for_selector: str | None = None,
        expected_text: str | None = None,
    ) -> BrowserEvidence:
        """Run a browser check against the project's dev server."""
        project = self.get_project(project_id)
        server_info = self.get_dev_server_info(project_id)
        if not server_info or not server_info.url:
            raise InvalidProjectState("Dev server is not running")

        evidence = run_browser_check(
            url=server_info.url,
            runtime_root=self.runtime_root,
            wait_for_selector=wait_for_selector,
            expected_text=expected_text,
        )
        return evidence

    def run_browser_interaction(
        self,
        project_id: str,
        interactions: list[dict[str, Any]],
    ) -> BrowserEvidence:
        """Run browser interactions against the project's dev server."""
        project = self.get_project(project_id)
        server_info = self.get_dev_server_info(project_id)
        if not server_info or not server_info.url:
            raise InvalidProjectState("Dev server is not running")

        evidence = run_browser_interaction(
            url=server_info.url,
            interactions=interactions,
            runtime_root=self.runtime_root,
        )
        return evidence

    def run_full_verification(
        self,
        project_id: str,
        expected_heading: str | None = None,
        expected_button_text: str | None = None,
        expected_message_after_click: str | None = None,
    ) -> BrowserEvidence:
        """Run a comprehensive browser verification for the generated app."""
        interactions = []

        if expected_heading:
            interactions.append({
                "action": "wait_for_function",
                "value": f"document.body.innerText.includes('{expected_heading}')",
            })

        if expected_button_text:
            interactions.append({
                "action": "click",
                "selector": f"button:has-text('{expected_button_text}')",
            })

        if expected_message_after_click:
            interactions.append({
                "action": "wait_for_function",
                "value": f"document.body.innerText.includes('{expected_message_after_click}')",
            })

        return self.run_browser_interaction(project_id, interactions)

    def cleanup(self) -> None:
        self._dev_server_manager.cleanup_all()


@dataclass
class V2Builder:
    """High-level builder that combines project creation with task execution."""

    project_service: ProjectService
    code_builder_service: Any = None  # Will be set later

    def build_from_prompt(
        self,
        prompt: str,
        project_name: str | None = None,
        framework_hint: str | None = None,
        auto_install: bool = True,
        auto_start_server: bool = True,
        max_attempts: int = 3,
    ) -> Project:
        """Build a complete project from a natural language prompt."""
        project = self.project_service.create_project(
            prompt=prompt,
            project_name=project_name,
            framework_hint=framework_hint,
        )

        if auto_install:
            success, output = self.project_service.install_dependencies(project.id)
            if not success:
                raise RuntimeError(f"Failed to install dependencies: {output}")

        if auto_start_server:
            self.project_service.start_dev_server(project.id)

        return project