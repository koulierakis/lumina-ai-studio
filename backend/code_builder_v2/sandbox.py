"""Sandbox runtime abstraction for Lumina Code Builder.

Uses SWE-ReX for unified local/Docker/Modal/Fargate execution.
Falls back to local subprocess if SWE-ReX unavailable.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SandboxError(RuntimeError):
    """Raised when sandbox operation fails."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class SandboxSession:
    """Represents an active sandbox session."""

    session_id: str
    workspace_root: Path
    metadata: dict[str, Any] = field(default_factory=dict)


class SandboxRuntime(ABC):
    """Abstract sandbox runtime."""

    @abstractmethod
    async def create_session(self, workspace_root: Path, env: dict[str, str] | None = None) -> SandboxSession:
        """Create a new sandbox session with workspace."""

    @abstractmethod
    async def run_command(
        self,
        session: SandboxSession,
        command: str,
        timeout_seconds: int = 120,
        workdir: str | None = None,
    ) -> CommandResult:
        """Run a command in the sandbox session."""

    @abstractmethod
    async def read_file(self, session: SandboxSession, path: str) -> str:
        """Read a file from the sandbox."""

    @abstractmethod
    async def write_file(self, session: SandboxSession, path: str, content: str) -> None:
        """Write a file to the sandbox."""

    @abstractmethod
    async def list_files(self, session: SandboxSession, path: str = ".") -> list[str]:
        """List files in sandbox path."""

    @abstractmethod
    async def close_session(self, session: SandboxSession) -> None:
        """Close and cleanup sandbox session."""

    @abstractmethod
    async def get_preview_url(self, session: SandboxSession, port: int) -> str:
        """Get public preview URL for a port in the sandbox."""


@dataclass(slots=True)
class LocalSubprocessRuntime(SandboxRuntime):
    """Local subprocess fallback (no isolation)."""

    _sessions: dict[str, SandboxSession] = field(default_factory=dict, init=False)

    async def create_session(self, workspace_root: Path, env: dict[str, str] | None = None) -> SandboxSession:
        session_id = f"local-{int(time.time() * 1000)}"
        session = SandboxSession(session_id=session_id, workspace_root=workspace_root)
        self._sessions[session_id] = session
        return session

    async def run_command(
        self,
        session: SandboxSession,
        command: str,
        timeout_seconds: int = 120,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        start = time.time()
        cwd = Path(workdir) if workdir else session.workspace_root
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **(env or {})},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            duration = time.time() - start
            return CommandResult(
                command=command,
                returncode=proc.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration_seconds=duration,
            )
        except TimeoutError:
            duration = time.time() - start
            return CommandResult(
                command=command,
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout_seconds}s",
                duration_seconds=duration,
            )

    async def read_file(self, session: SandboxSession, path: str) -> str:
        return (session.workspace_root / path).read_text(encoding="utf-8")

    async def write_file(self, session: SandboxSession, path: str, content: str) -> None:
        target = session.workspace_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def list_files(self, session: SandboxSession, path: str = ".") -> list[str]:
        target = session.workspace_root / path
        if not target.exists():
            return []
        return [str(p.relative_to(session.workspace_root)) for p in target.rglob("*") if p.is_file()]

    async def close_session(self, session: SandboxSession) -> None:
        self._sessions.pop(session.session_id, None)

    async def get_preview_url(self, session: SandboxSession, port: int) -> str:
        return f"http://127.0.0.1:{port}"


@dataclass(slots=True)
class SWEReXRuntime(SandboxRuntime):
    """SWE-ReX runtime for isolated execution (local, Docker, Modal, Fargate)."""

    deployment_type: str = "local"  # local, docker, modal, fargate
    deployment_config: dict[str, Any] = field(default_factory=dict)
    _deployment: Any = field(default=None, init=False)
    _runtime: Any = field(default=None, init=False)
    _sessions: dict[str, SandboxSession] = field(default_factory=dict, init=False)

    def __post_init__(self):
        if importlib.util.find_spec("swe_rex") is not None:
            self._swe_rex_available = True
        else:
            self._swe_rex_available = False

    async def _ensure_deployment(self):
        if self._deployment is not None:
            return

        if not self._swe_rex_available:
            raise SandboxError("SWE-ReX not installed. pip install swe-rex")

        from swe_rex.config import (
            DockerDeploymentConfig,
            LocalDeploymentConfig,
            ModalDeploymentConfig,
        )
        from swe_rex.deployment.docker import DockerDeployment
        from swe_rex.deployment.local import LocalDeployment
        from swe_rex.deployment.modal import ModalDeployment

        if self.deployment_type == "local":
            config = LocalDeploymentConfig(**self.deployment_config)
            self._deployment = LocalDeployment.from_config(config)
        elif self.deployment_type == "docker":
            config = DockerDeploymentConfig(**self.deployment_config)
            self._deployment = DockerDeployment.from_config(config)
        elif self.deployment_type == "modal":
            config = ModalDeploymentConfig(**self.deployment_config)
            self._deployment = ModalDeployment.from_config(config)
        else:
            raise SandboxError(f"Unknown deployment type: {self.deployment_type}")

        await self._deployment.start()
        self._runtime = self._deployment.runtime

    async def create_session(self, workspace_root: Path, env: dict[str, str] | None = None) -> SandboxSession:
        await self._ensure_deployment()
        session_id = await self._runtime.create_session()
        session = SandboxSession(session_id=session_id, workspace_root=workspace_root)
        self._sessions[session_id] = session

        # Copy workspace to sandbox
        for file_path in workspace_root.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(workspace_root)
                content = file_path.read_bytes()
                await self._runtime.write_file(session_id, str(rel_path), content)

        # Set environment variables
        if env:
            for key, value in env.items():
                await self.run_command(session, f"export {key}='{value}'")

        return session

    async def run_command(
        self,
        session: SandboxSession,
        command: str,
        timeout_seconds: int = 120,
        workdir: str | None = None,
    ) -> CommandResult:
        await self._ensure_deployment()
        start = time.time()
        try:
            result = await asyncio.wait_for(
                self._runtime.run_in_session(session.session_id, command, cwd=workdir),
                timeout=timeout_seconds,
            )
            duration = time.time() - start
            return CommandResult(
                command=command,
                returncode=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_seconds=duration,
            )
        except TimeoutError:
            duration = time.time() - start
            return CommandResult(
                command=command,
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout_seconds}s",
                duration_seconds=duration,
            )

    async def read_file(self, session: SandboxSession, path: str) -> str:
        await self._ensure_deployment()
        content = await self._runtime.read_file(session.session_id, path)
        return content

    async def write_file(self, session: SandboxSession, path: str, content: str) -> None:
        await self._ensure_deployment()
        await self._runtime.write_file(session.session_id, path, content)

    async def list_files(self, session: SandboxSession, path: str = ".") -> list[str]:
        await self._ensure_deployment()
        # SWE-ReX doesn't have direct list, use shell
        result = await self.run_command(session, f"find {path} -type f -printf '%P\\n'")
        if result.returncode == 0:
            return [line for line in result.stdout.strip().split("\n") if line]
        return []

    async def close_session(self, session: SandboxSession) -> None:
        if self._runtime and session.session_id in self._sessions:
            try:
                await self._runtime.close_session(session.session_id)
            except Exception:
                pass
            self._sessions.pop(session.session_id, None)

    async def get_preview_url(self, session: SandboxSession, port: int) -> str:
        if self.deployment_type == "local":
            return f"http://127.0.0.1:{port}"
        # For remote deployments, would need port forwarding
        return f"http://127.0.0.1:{port}"

    async def shutdown(self):
        if self._deployment:
            await self._deployment.stop()


@dataclass(slots=True)
class DockerSandboxRuntime(SandboxRuntime):
    """Docker-based isolated sandbox (alternative to SWE-ReX)."""

    image: str = "python:3.11-slim"
    _container_name: str | None = field(default=None, init=False)
    _workspace_volume: str = field(default="", init=False)

    async def create_session(self, workspace_root: Path, env: dict[str, str] | None = None) -> SandboxSession:
        import uuid
        session_id = f"docker-{uuid.uuid4().hex[:8]}"
        self._container_name = f"lumina-sandbox-{session_id}"
        self._workspace_volume = f"/workspace-{session_id}"

        # Create Docker volume and copy workspace
        subprocess.run(["docker", "volume", "create", self._workspace_volume], check=True, capture_output=True)

        # Copy files to volume using a temporary container
        tar_data = shutil.make_archive(f"/tmp/{session_id}", "tar", workspace_root)
        with open(tar_data, "rb") as archive:
            archive_bytes = archive.read()
        subprocess.run(
            ["docker", "run", "--rm", "-v", f"{self._workspace_volume}:/target", "alpine"],
            input=archive_bytes,
            check=True,
        )
        os.unlink(tar_data)

        # Start sandbox container
        env_args = []
        if env:
            for k, v in env.items():
                env_args.extend(["-e", f"{k}={v}"])

        subprocess.run([
            "docker", "run", "-d",
            "--name", self._container_name,
            "-v", f"{self._workspace_volume}:/workspace",
            *env_args,
            self.image,
            "sleep", "infinity"
        ], check=True, capture_output=True)

        return SandboxSession(session_id=session_id, workspace_root=workspace_root)

    async def run_command(
        self,
        session: SandboxSession,
        command: str,
        timeout_seconds: int = 120,
        workdir: str | None = None,
    ) -> CommandResult:
        if not self._container_name:
            raise SandboxError("No active container")

        cwd = f"/workspace/{workdir}" if workdir else "/workspace"
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "-w", cwd, self._container_name, "sh", "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            duration = time.time() - start
            return CommandResult(
                command=command,
                returncode=proc.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration_seconds=duration,
            )
        except TimeoutError:
            duration = time.time() - start
            return CommandResult(
                command=command,
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout_seconds}s",
                duration_seconds=duration,
            )

    async def read_file(self, session: SandboxSession, path: str) -> str:
        result = await self.run_command(session, f"cat /workspace/{path}")
        if result.returncode != 0:
            raise SandboxError(f"Failed to read file: {result.stderr}")
        return result.stdout

    async def write_file(self, session: SandboxSession, path: str, content: str) -> None:
        import base64
        encoded = base64.b64encode(content.encode()).decode()
        result = await self.run_command(session, f"echo '{encoded}' | base64 -d > /workspace/{path}")
        if result.returncode != 0:
            raise SandboxError(f"Failed to write file: {result.stderr}")

    async def list_files(self, session: SandboxSession, path: str = ".") -> list[str]:
        result = await self.run_command(session, f"find /workspace/{path} -type f -printf '%P\\n'")
        if result.returncode == 0:
            return [line for line in result.stdout.strip().split("\n") if line]
        return []

    async def close_session(self, session: SandboxSession) -> None:
        if self._container_name:
            subprocess.run(["docker", "stop", self._container_name], capture_output=True)
            subprocess.run(["docker", "rm", self._container_name], capture_output=True)
            subprocess.run(["docker", "volume", "rm", self._workspace_volume], capture_output=True)
            self._container_name = None

    async def get_preview_url(self, session: SandboxSession, port: int) -> str:
        # Would need port mapping in docker run
        return f"http://127.0.0.1:{port}"


def create_sandbox_runtime(prefer_isolated: bool = True) -> SandboxRuntime:
    """Factory to create best available sandbox runtime.

    Priority: SWE-ReX (local) -> Docker -> Local subprocess
    """
    # Try SWE-ReX first
    if prefer_isolated:
        if importlib.util.find_spec("swe_rex") is not None:
            return SWEReXRuntime(deployment_type="local")

    # Try Docker
    if prefer_isolated and shutil.which("docker"):
        try:
            subprocess.run(["docker", "info"], check=True, capture_output=True)
            return DockerSandboxRuntime()
        except Exception:
            pass

    # Fallback to local subprocess
    return LocalSubprocessRuntime()
