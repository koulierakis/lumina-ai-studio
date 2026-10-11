"""Stack-aware execution + build/test/lint/typecheck pipelines.

All child processes are launched with a **sandboxed environment**
(`gold_builder.security.sandbox_env`) — the parent's LLM keys, MongoDB URL,
provider credentials, and any other secrets are NEVER inherited by
generated applications.

Preserves earlier helpers used by the html-static path:
  - start_static_server
  - run_command
  - run_pipeline
Adds:
  - start_stack_server (stack-aware, sandboxed)
"""
from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional

from ..models import CommandResult
from ..security import sandbox_env
from .stacks import StackConfig

_QUIET_FLAGS = frozenset({"--silent", "--quiet", "-s", "-q"})
_FAIL_OUTPUT_CHARS = 8000
_OK_OUTPUT_CHARS = 500


def _pick_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class ServiceInstance:
    name: str
    process: asyncio.subprocess.Process
    port: int
    url: str
    log_path: Path
    log_f: Any

@dataclass
class RunningServer:
    process: Optional[asyncio.subprocess.Process]
    port: int
    url: str
    log_path: Path
    log_f: Any = None
    services: List[ServiceInstance] = field(default_factory=list)

    async def stop(self) -> None:
        procs = [s.process for s in self.services] if self.services else ([self.process] if self.process else [])
        for p in procs:
            if p and p.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    p.terminate()
        for p in procs:
            if p and p.returncode is None:
                try:
                    await asyncio.wait_for(p.wait(), timeout=5)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        p.kill()
                        await p.wait()
        for s in self.services:
            if s.log_f and not s.log_f.closed:
                with contextlib.suppress(Exception):
                    s.log_f.close()
        if self.log_f and not self.log_f.closed:
            with contextlib.suppress(Exception):
                self.log_f.close()


async def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            r, w = await asyncio.open_connection(host, port)
            w.close()
            with contextlib.suppress(Exception):
                await w.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.15)
    raise RuntimeError(f"Timeout waiting for {host}:{port}")


async def start_static_server(project: Path, artifacts: Path) -> RunningServer:
    port = _pick_port()
    log_path = artifacts / "server.log"
    log_f = log_path.open("wb")
    proc = await asyncio.create_subprocess_exec(
        "python", "-m", "http.server", str(port), "--bind", "127.0.0.1",
        cwd=str(project),
        env=sandbox_env({"PORT": str(port)}),
        stdout=log_f, stderr=asyncio.subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}/"
    await _wait_for_port("127.0.0.1", port, timeout=10)
    return RunningServer(process=proc, port=port, url=url, log_path=log_path, log_f=log_f)


async def start_stack_server(
    stack: StackConfig, project: Path, artifacts: Path,
) -> RunningServer:
    if not stack.start_command:
        static_root = (project / stack.start_cwd).resolve()
        if not static_root.exists() or not static_root.is_dir():
            raise RuntimeError(f"Static preview root does not exist: {stack.start_cwd}")
        return await start_static_server(static_root, artifacts)

    port = _pick_port()
    cmd = [c.replace("{port}", str(port)) for c in stack.start_command]
    cwd = (project / stack.start_cwd).resolve()
    log_path = artifacts / "server.log"
    log_f = log_path.open("wb")

    extra_env = {stack.port_env: str(port), "PORT": str(port)}
    extra_env.update(stack.extra_env or {})
    env = sandbox_env(extra_env)

    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd), env=env,
        stdout=log_f, stderr=asyncio.subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}{stack.ready_path}"
    try:
        await _wait_for_port("127.0.0.1", port, timeout=45)
    except Exception:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        log_f.close()
        tail = ""
        with contextlib.suppress(Exception):
            tail = log_path.read_text(errors="replace")[-1500:]
        raise RuntimeError(f"server did not open {port}\n--- log tail ---\n{tail}")
    return RunningServer(process=proc, port=port, url=url, log_path=log_path, log_f=log_f)


async def run_command(
    cmd: List[str],
    cwd: Path,
    timeout: float = 240.0,
    env: Optional[dict] = None,
) -> tuple[int, str]:
    """Run a one-off command in a sandboxed environment."""
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd),
        env=sandbox_env(env or {}),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"command timed out after {timeout}s"
    return proc.returncode or 0, (stdout or b"").decode("utf-8", errors="replace")


def _without_quiet_flags(cmd: List[str]) -> List[str]:
    return [part for part in cmd if part not in _QUIET_FLAGS]


def _clip_output(out: str, rc: int) -> str:
    limit = _FAIL_OUTPUT_CHARS if rc else _OK_OUTPUT_CHARS
    return (out or "")[-limit:]


async def run_pipeline(
    label: str,
    pipeline: Iterable[List[str]],
    project: Path,
    timeout: float = 300.0,
) -> List[CommandResult]:
    results: List[CommandResult] = []
    for cmd in pipeline:
        started = time.time()
        recorded_cmd = list(cmd)
        rc, out = await run_command(cmd, project, timeout=timeout)
        quiet = any(part in _QUIET_FLAGS for part in cmd)
        if rc != 0 and quiet and not (out or "").strip():
            noisy = _without_quiet_flags(cmd)
            if noisy != cmd:
                rc, out = await run_command(noisy, project, timeout=timeout)
        results.append(CommandResult(
            label=label,
            cmd=recorded_cmd,
            cwd=".",
            rc=rc,
            output_tail=_clip_output(out, rc),
            duration_s=round(time.time() - started, 2),
        ))
        if rc != 0:
            break
    return results
