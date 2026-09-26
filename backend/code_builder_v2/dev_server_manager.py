from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import DevServerInfo, DevServerStatus, Project
from .project_generator import find_free_port, get_dev_server_command


@dataclass
class DevServerProcess:
    process: subprocess.Popen
    port: int
    url: str
    command: str
    log_buffer: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_log(self, line: str) -> None:
        with self._lock:
            self.log_buffer.append(line)
            if len(self.log_buffer) > 1000:
                self.log_buffer = self.log_buffer[-1000:]

    def get_logs(self) -> str:
        with self._lock:
            return "\n".join(self.log_buffer)


class DevServerManager:
    def __init__(self, runtime_root: Path):
        self.runtime_root = runtime_root
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._servers: dict[str, DevServerProcess] = {}
        self._lock = threading.RLock()

    def start_server(self, project: Project) -> DevServerInfo:
        project_path = Path(project.workspace_root)
        if not project_path.exists():
            raise RuntimeError(f"Project workspace does not exist: {project_path}")

        cmd_template = get_dev_server_command(project)
        if cmd_template is None:
            raise RuntimeError(f"No dev server command found for framework: {project.framework}")

        port = find_free_port()
        command = cmd_template[0].format(port=port)
        url = f"http://localhost:{port}"

        env = os.environ.copy()
        env["PORT"] = str(port)

        log_file = self.runtime_root / f"devserver_{project.id}.log"
        log_fh = open(log_file, "a", encoding="utf-8")

        try:
            process = subprocess.Popen(
                command,
                cwd=project_path,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                start_new_session=True,
            )
        except Exception as exc:
            log_fh.close()
            raise RuntimeError(f"Failed to start dev server: {exc}") from exc

        server_process = DevServerProcess(
            process=process,
            port=port,
            url=url,
            command=command,
        )

        with self._lock:
            self._servers[project.id] = server_process

        threading.Thread(target=self._monitor_process, args=(project.id, server_process, log_fh), daemon=True).start()

        project.dev_server = DevServerInfo(
            port=port,
            url=url,
            pid=process.pid,
            status=DevServerStatus.starting,
            command=command,
            started_at=datetime.now(UTC),
            framework=project.framework,
        )

        if self._wait_for_ready(project.id, timeout=60):
            project.dev_server.status = DevServerStatus.ready
            return project.dev_server

        project.dev_server.status = DevServerStatus.failed
        project.dev_server.error = "Dev server failed to become ready within timeout"
        self.stop_server(project.id)
        raise RuntimeError("Dev server failed to start")

    def _monitor_process(self, project_id: str, server_process: DevServerProcess, log_fh) -> None:
        process = server_process.process
        try:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                line = line.rstrip("\n")
                server_process.add_log(line)
                log_fh.write(line + "\n")
                log_fh.flush()
        except Exception:
            pass
        finally:
            log_fh.close()
            with self._lock:
                if project_id in self._servers:
                    del self._servers[project_id]

    def _wait_for_ready(self, project_id: str, timeout: int = 60) -> bool:
        start_time = time.time()
        server_process = self._servers.get(project_id)
        if not server_process:
            return False

        while time.time() - start_time < timeout:
            if server_process.process.poll() is not None:
                return False
            if self._check_health(server_process.url):
                return True
            time.sleep(0.5)
        return False

    def _check_health(self, url: str) -> bool:
        try:
            import urllib.request
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status < 500
        except Exception:
            return False

    def stop_server(self, project_id: str) -> bool:
        with self._lock:
            server_process = self._servers.pop(project_id, None)

        if not server_process:
            return False

        process = server_process.process
        try:
            if process.poll() is None:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait(timeout=2)
        except Exception:
            pass
        return True

    def get_server_info(self, project_id: str) -> DevServerInfo | None:
        with self._lock:
            server_process = self._servers.get(project_id)
        if not server_process:
            return None
        return DevServerInfo(
            port=server_process.port,
            url=server_process.url,
            pid=server_process.process.pid,
            status=DevServerStatus.ready if server_process.process.poll() is None else DevServerStatus.failed,
            command=server_process.command,
        )

    def get_logs(self, project_id: str) -> str:
        with self._lock:
            server_process = self._servers.get(project_id)
        if not server_process:
            return ""
        return server_process.get_logs()

    def cleanup_all(self) -> None:
        with self._lock:
            project_ids = list(self._servers.keys())
        for project_id in project_ids:
            self.stop_server(project_id)