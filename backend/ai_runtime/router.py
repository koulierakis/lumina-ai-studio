from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from auth import require_owner

from .manager import runtime_manager
from .schemas import RuntimeJob, RuntimeJobStatus

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/health")
async def runtime_health(_: str = Depends(require_owner)) -> dict:
    return runtime_manager.health()


@router.get("/jobs")
async def runtime_jobs(owner: str = Depends(require_owner)) -> dict:
    return {"jobs": runtime_manager.list_jobs(owner)}


@router.get("/jobs/{job_id}")
async def runtime_job(job_id: str, owner: str = Depends(require_owner)) -> dict:
    job = runtime_manager.jobs.get(job_id)
    if not job or job.owner_email != owner:
        raise HTTPException(404, "Runtime job not found")
    return job.as_dict()


@router.post("/jobs")
async def submit_runtime_job(body: dict, owner: str = Depends(require_owner)) -> dict:
    task_type = str(body.get("task_type") or "llm")
    job = RuntimeJob(
        studio=str(body.get("studio") or "runtime"),
        task_type=task_type,
        payload=body.get("payload") or {},
        owner_email=owner,
        provider=body.get("provider"),
        model=body.get("model"),
    )

    async def default_executor(runtime_job, progress):
        await progress(
            runtime_job,
            RuntimeJobStatus.RUNNING,
            75,
            "Generic runtime validation completed",
        )
        return {"ok": True, "payload": runtime_job.payload}

    await runtime_manager.submit(job, default_executor, run_background=False)
    return job.as_dict()


@router.post("/jobs/{job_id}/cancel")
async def cancel_runtime_job(job_id: str, owner: str = Depends(require_owner)) -> dict:
    job = runtime_manager.jobs.get(job_id)
    if not job or job.owner_email != owner:
        raise HTTPException(404, "Runtime job not found")
    return runtime_manager.cancel(job_id).as_dict()


@router.post("/jobs/{job_id}/pause")
async def pause_runtime_job(job_id: str, owner: str = Depends(require_owner)) -> dict:
    job = runtime_manager.jobs.get(job_id)
    if not job or job.owner_email != owner:
        raise HTTPException(404, "Runtime job not found")
    return runtime_manager.pause(job_id).as_dict()


@router.post("/jobs/{job_id}/retry")
async def retry_runtime_job(job_id: str, owner: str = Depends(require_owner)) -> dict:
    job = runtime_manager.jobs.get(job_id)
    if not job or job.owner_email != owner:
        raise HTTPException(404, "Runtime job not found")
    if job.status not in {RuntimeJobStatus.FAILED, RuntimeJobStatus.CANCELLED}:
        raise HTTPException(400, "Only failed or cancelled runtime jobs can be retried")
    return runtime_manager.retry(job_id).as_dict()


@router.get("/providers")
async def runtime_providers(_: str = Depends(require_owner)) -> dict:
    return runtime_manager.providers.validate()


@router.post("/providers/plugins")
async def install_runtime_plugin(body: dict, _: str = Depends(require_owner)) -> dict:
    try:
        return runtime_manager.plugins.install(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/plugins")
async def runtime_plugins(_: str = Depends(require_owner)) -> dict:
    return {"plugins": runtime_manager.plugins.list()}


@router.get("/models")
async def runtime_models(_: str = Depends(require_owner)) -> dict:
    return runtime_manager.models.list()


@router.post("/models/{model_id}/load")
async def load_runtime_model(model_id: str, _: str = Depends(require_owner)) -> dict:
    return runtime_manager.load_model(model_id)


@router.post("/models/{model_id}/unload")
async def unload_runtime_model(model_id: str, _: str = Depends(require_owner)) -> dict:
    return runtime_manager.unload_model(model_id)


@router.post("/models/{model_id}/enable")
async def enable_runtime_model(
    model_id: str,
    body: dict,
    _: str = Depends(require_owner),
) -> dict:
    try:
        return runtime_manager.models.set_enabled(
            model_id,
            bool(body.get("enabled", True)),
        ).as_dict()
    except KeyError as exc:
        raise HTTPException(404, "Model not found") from exc


@router.post("/models/{model_id}/default")
async def default_runtime_model(
    model_id: str,
    body: dict,
    _: str = Depends(require_owner),
) -> dict:
    try:
        return runtime_manager.models.select_default(
            model_id,
            str(body.get("studio") or "global"),
        ).as_dict()
    except KeyError as exc:
        raise HTTPException(404, "Model not found") from exc


@router.post("/models/{model_id}/download")
async def download_runtime_model(model_id: str, _: str = Depends(require_owner)) -> dict:
    return runtime_manager.models.queue_download(model_id)


@router.post("/models/queue/{queue_id}/{action}")
async def runtime_model_queue_action(
    queue_id: str,
    action: str,
    _: str = Depends(require_owner),
) -> dict:
    try:
        if action == "pause":
            return runtime_manager.models.pause(queue_id)
        if action == "resume":
            return runtime_manager.models.resume(queue_id)
        if action == "cancel":
            return runtime_manager.models.cancel(queue_id)
    except KeyError as exc:
        raise HTTPException(404, "Queue item not found") from exc
    raise HTTPException(400, "Unsupported queue action")


@router.post("/models/{model_id}/verify")
async def verify_runtime_model(model_id: str, _: str = Depends(require_owner)) -> dict:
    try:
        return runtime_manager.models.verify(model_id)
    except KeyError as exc:
        raise HTTPException(404, "Model not found") from exc


@router.post("/models/{model_id}/repair")
async def repair_runtime_model(model_id: str, _: str = Depends(require_owner)) -> dict:
    try:
        return runtime_manager.models.repair(model_id)
    except KeyError as exc:
        raise HTTPException(404, "Model not found") from exc


@router.delete("/models/{model_id}")
async def delete_runtime_model(model_id: str, _: str = Depends(require_owner)) -> dict:
    try:
        return runtime_manager.models.delete(model_id)
    except KeyError as exc:
        raise HTTPException(404, "Model not found") from exc


@router.post("/models/storage")
async def move_runtime_storage(body: dict, _: str = Depends(require_owner)) -> dict:
    path = str(body.get("path") or runtime_manager.models.models_dir)
    return runtime_manager.models.move_storage(path)


@router.post("/models/import")
async def import_runtime_model(body: dict, _: str = Depends(require_owner)) -> dict:
    try:
        return runtime_manager.models.import_model(
            name=str(body.get("name") or "Imported Model"),
            path=str(body.get("path") or ""),
            type=str(body.get("type") or "llm"),
            provider=str(body.get("provider") or "local"),
        ).as_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/models/export")
async def export_runtime_models(_: str = Depends(require_owner)) -> dict:
    return runtime_manager.models.export_installed()


@router.get("/models/updates")
async def runtime_model_updates(_: str = Depends(require_owner)) -> dict:
    return runtime_manager.models.update_detection()


@router.get("/resources")
async def runtime_resources(_: str = Depends(require_owner)) -> dict:
    health = runtime_manager.health()
    return health["resources"]


@router.get("/diagnostics")
async def runtime_diagnostics(_: str = Depends(require_owner)) -> dict:
    return runtime_manager.diagnostic_report()


@router.post("/diagnostics/repair")
async def runtime_repair(body: dict, _: str = Depends(require_owner)) -> dict:
    return runtime_manager.diagnostics.repair(body or runtime_manager.diagnostic_report())
