from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .diagnostics import DiagnosticsEngine
from .models import ModelManager
from .providers import PluginManager, build_default_provider_registry
from .resources import ResourceManager
from .schemas import RuntimeExecutor, RuntimeJob, RuntimeJobStatus, utc_now


class RuntimeManager:
    def __init__(self) -> None:
        root = Path(__file__).resolve().parents[2] / ".lumina" / "runtime"
        self.models = ModelManager(root)
        self.resources = ResourceManager(Path(__file__).resolve().parents[2])
        self.providers = build_default_provider_registry()
        self.plugins = PluginManager(self.providers)
        self.diagnostics = DiagnosticsEngine()
        self.jobs: dict[str, RuntimeJob] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.executors: dict[str, RuntimeExecutor] = {}
        self.loaded_models: set[str] = set()
        self.worker_started = False
        self.max_concurrent = 2
        self._running = 0
        self.jobs_path = root / "jobs.json"
        self._load_jobs()

    def _persist_jobs(self) -> None:
        self.jobs_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.jobs_path.with_suffix(".tmp")
        tmp.write_text(json.dumps([job.as_dict() for job in self.jobs.values()], indent=2, default=str), encoding="utf-8")
        tmp.replace(self.jobs_path)

    def _load_jobs(self) -> None:
        try:
            rows = json.loads(self.jobs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            rows = []
        if not isinstance(rows, list):
            return
        active = {RuntimeJobStatus.RUNNING.value, RuntimeJobStatus.PREPARING.value, RuntimeJobStatus.LOADING_MODEL.value, RuntimeJobStatus.RETRYING.value, RuntimeJobStatus.WAITING.value}
        for row in rows:
            if not isinstance(row, dict):
                continue
            row = dict(row)
            row.pop("logs", None)
            if row.get("status") in active:
                row["status"] = RuntimeJobStatus.FAILED
                row["error"] = row.get("error") or "Runtime restarted before this job completed. Retry the job to run it again."
                row["finished_at"] = row.get("finished_at") or utc_now()
            try:
                job = RuntimeJob(**row)
            except TypeError:
                continue
            self.jobs[job.id] = job

    def register_executor(self, task_type: str, executor: RuntimeExecutor) -> None:
        self.executors[task_type] = executor

    def load_model(self, model_id: str) -> dict[str, Any]:
        self.loaded_models.add(model_id)
        return {"model_id": model_id, "status": "loaded"}

    def unload_model(self, model_id: str) -> dict[str, Any]:
        self.loaded_models.discard(model_id)
        return {"model_id": model_id, "status": "unloaded"}

    async def submit(self, job: RuntimeJob, executor: RuntimeExecutor | None = None, run_background: bool = True) -> RuntimeJob:
        provider = self.providers.route(job.task_type, job.provider)
        job.provider = provider.name
        job.metadata["resource_allocation"] = self.resources.allocate(job.task_type)
        job.log("info", f"Queued runtime job through {provider.name}")
        self.jobs[job.id] = job
        self._persist_jobs()
        if executor:
            self.executors[job.task_type] = executor
        if run_background:
            await self.queue.put(job.id)
            self.ensure_worker()
        else:
            await self.run_job(job.id)
        return job

    def ensure_worker(self) -> None:
        if not self.worker_started:
            self.worker_started = True
            asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            while self._running >= self.max_concurrent:
                await asyncio.sleep(0.05)
            self._running += 1
            asyncio.create_task(self._run_and_release(job_id))

    async def _run_and_release(self, job_id: str) -> None:
        try:
            await self.run_job(job_id)
        finally:
            self._running = max(0, self._running - 1)
            self.queue.task_done()

    async def progress(self, job: RuntimeJob, status: RuntimeJobStatus, progress: int, message: str) -> None:
        job.status = status
        job.progress = max(0, min(100, progress))
        job.updated_at = utc_now()
        job.log("info", message)
        self._persist_jobs()

    async def run_job(self, job_id: str) -> RuntimeJob:
        job = self.jobs[job_id]
        executor = self.executors.get(job.task_type)
        if not executor:
            await self.progress(job, RuntimeJobStatus.FAILED, job.progress, "No runtime executor registered")
            job.error = "No runtime executor registered"
            job.finished_at = utc_now()
            self._persist_jobs()
            return job
        while True:
            try:
                job.started_at = job.started_at or utc_now()
                await self.progress(job, RuntimeJobStatus.PREPARING, 8, "Preparing runtime job")
                if job.model:
                    await self.progress(job, RuntimeJobStatus.LOADING_MODEL, 18, "Loading model")
                    self.load_model(job.model)
                await self.progress(job, RuntimeJobStatus.RUNNING, max(job.progress, 25), "Runtime execution started")
                job.result = await executor(job, self.progress)
                await self.progress(job, RuntimeJobStatus.COMPLETED, 100, "Runtime job completed")
                job.finished_at = utc_now()
                self._persist_jobs()
                return job
            except Exception as exc:
                job.log("error", str(exc))
                if job.retry_count < job.max_retries:
                    job.retry_count += 1
                    await self.progress(job, RuntimeJobStatus.RETRYING, job.progress, "Retrying after runtime failure")
                    await asyncio.sleep(0.05 * job.retry_count)
                    continue
                job.status = RuntimeJobStatus.FAILED
                job.error = str(exc)
                job.metadata["diagnostics"] = self.diagnostics.analyze_error(exc, job.as_dict())
                job.finished_at = utc_now()
                job.updated_at = utc_now()
                self._persist_jobs()
                return job

    def cancel(self, job_id: str) -> RuntimeJob:
        job = self.jobs[job_id]
        if job.status not in {RuntimeJobStatus.COMPLETED, RuntimeJobStatus.FAILED, RuntimeJobStatus.CANCELLED}:
            job.status = RuntimeJobStatus.CANCELLED
            job.finished_at = utc_now()
            job.log("warning", "Runtime job cancelled")
            self._persist_jobs()
        return job

    def pause(self, job_id: str) -> RuntimeJob:
        job = self.jobs[job_id]
        if job.status in {RuntimeJobStatus.QUEUED, RuntimeJobStatus.RUNNING, RuntimeJobStatus.WAITING}:
            job.status = RuntimeJobStatus.PAUSED
            job.log("warning", "Runtime job paused")
            self._persist_jobs()
        return job

    def retry(self, job_id: str) -> RuntimeJob:
        original = self.jobs[job_id]
        job = RuntimeJob(
            studio=original.studio,
            task_type=original.task_type,
            payload=original.payload,
            owner_email=original.owner_email,
            provider=original.provider,
            model=original.model,
            max_retries=original.max_retries,
            metadata={"retry_of": original.id},
        )
        job.log("info", f"Retry created from runtime job {original.id}")
        self.jobs[job.id] = job
        self._persist_jobs()
        return job

    def list_jobs(self, owner: str | None = None) -> list[dict[str, Any]]:
        jobs = self.jobs.values()
        if owner:
            jobs = [job for job in jobs if job.owner_email == owner]
        return sorted([job.as_dict() for job in jobs], key=lambda item: item["updated_at"], reverse=True)

    def health(self) -> dict[str, Any]:
        running = len([j for j in self.jobs.values() if j.status in {RuntimeJobStatus.RUNNING, RuntimeJobStatus.PREPARING, RuntimeJobStatus.LOADING_MODEL, RuntimeJobStatus.RETRYING}])
        queued = len([j for j in self.jobs.values() if j.status == RuntimeJobStatus.QUEUED])
        providers = self.providers.validate()
        resources = self.resources.snapshot(running_jobs=running, queued_jobs=queued)
        models = self.models.list()
        return {"status": "ok" if providers["ok"] else "degraded", "providers": providers, "resources": resources, "models": models, "loaded_models": sorted(self.loaded_models), "jobs": {"running": running, "queued": queued, "total": len(self.jobs)}, "services": {"queue": "ready", "scheduler": "ready", "diagnostics": "ready", "plugins": "ready"}}

    def diagnostic_report(self) -> dict[str, Any]:
        return self.diagnostics.report(self.health())


runtime_manager = RuntimeManager()
