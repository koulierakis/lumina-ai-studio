from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .models import BuildTask, TaskRequest
from .service import CodeBuilderService, TaskNotFound

router = APIRouter(prefix="/api/code-builder-v2", tags=["code-builder-v2"])
_service: CodeBuilderService | None = None


def configure(service: CodeBuilderService) -> None:
    global _service
    _service = service


def service() -> CodeBuilderService:
    if _service is None:
        raise RuntimeError("Code Builder V2 router is not configured")
    return _service


@router.get("/health")
def health() -> dict[str, object]:
    return {"status": "healthy", "version": 2, "configured": _service is not None}


@router.post("/tasks", response_model=BuildTask)
def create_task(request: TaskRequest) -> BuildTask:
    task = service().create_task(request)
    return service().plan_task(task.id)


@router.get("/tasks/{task_id}", response_model=BuildTask)
def get_task(task_id: str) -> BuildTask:
    try:
        return service().get_task(task_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@router.post("/tasks/{task_id}/cancel", response_model=BuildTask)
def cancel_task(task_id: str) -> BuildTask:
    try:
        return service().cancel_task(task_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
