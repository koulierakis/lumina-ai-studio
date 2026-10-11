"""Preview lifecycle manager.

After a generated app passes verification, its dev server is kept alive so
the user can open a live preview. A `PreviewManager` singleton owns the
per-job `RunningServer` handles and exposes start / stop / restart /
status operations.

The engine also exposes an HTTP reverse proxy at
`/api/gb/jobs/{id}/proxy/{path}` so the running app can be embedded in the
console iframe even though it binds to 127.0.0.1 inside the container.
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Dict, Optional

from .executor import RunningServer, start_stack_server
from .stacks import StackConfig, get_stack
from .. import workspace
from ..models import PreviewInfo


class PreviewManager:
    def __init__(self):
        self._by_job: Dict[str, RunningServer] = {}
        self._started_at: Dict[str, str] = {}
        self._stack_id: Dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def start(self, job_id: str, stack: StackConfig) -> PreviewInfo:
        async with self._lock:
            await self._stop_locked(job_id)
            project = workspace.project_dir(job_id)
            artifacts = workspace.artifacts_dir(job_id)
            server = await start_stack_server(stack, project, artifacts)
            self._by_job[job_id] = server
            self._started_at[job_id] = datetime.now(timezone.utc).isoformat()
            self._stack_id[job_id] = stack.id
            return self._info_for(job_id)

    async def adopt(self, job_id: str, stack: StackConfig, server: RunningServer) -> PreviewInfo:
        """Retain the exact server instance that was browser-verified."""
        async with self._lock:
            existing = self._by_job.get(job_id)
            if existing is not None and existing is not server:
                with contextlib.suppress(Exception):
                    await existing.stop()
            self._by_job[job_id] = server
            self._started_at[job_id] = datetime.now(timezone.utc).isoformat()
            self._stack_id[job_id] = stack.id
            return self._info_for(job_id)

    async def restart(self, job_id: str) -> Optional[PreviewInfo]:
        stack_id = self._stack_id.get(job_id)
        if not stack_id:
            return None
        return await self.start(job_id, get_stack(stack_id))

    async def stop(self, job_id: str) -> Optional[PreviewInfo]:
        async with self._lock:
            info = self._info_for(job_id, running_override=False)
            await self._stop_locked(job_id)
            return info

    async def _stop_locked(self, job_id: str) -> None:
        srv = self._by_job.pop(job_id, None)
        self._started_at.pop(job_id, None)
        if srv is not None:
            with contextlib.suppress(Exception):
                await srv.stop()

    def status(self, job_id: str) -> Optional[PreviewInfo]:
        if job_id not in self._by_job:
            return None
        return self._info_for(job_id)

    def internal_url(self, job_id: str) -> Optional[str]:
        srv = self._by_job.get(job_id)
        return srv.url if srv else None

    def port(self, job_id: str) -> Optional[int]:
        srv = self._by_job.get(job_id)
        return srv.port if srv else None

    def _info_for(self, job_id: str, running_override: Optional[bool] = None) -> PreviewInfo:
        srv = self._by_job.get(job_id)
        running = running_override if running_override is not None else (srv is not None)
        return PreviewInfo(
            job_id=job_id,
            running=running,
            port=srv.port if srv else None,
            internal_url=srv.url if srv else None,
            proxy_url=f"/api/gb/jobs/{job_id}/proxy/" if running else None,
            stack_id=self._stack_id.get(job_id),
            started_at=self._started_at.get(job_id),
        )


# Module-level singleton — safe because the engine is single-process
manager = PreviewManager()
