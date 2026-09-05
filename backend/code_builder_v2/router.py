from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .models import BuildTask, TaskRequest
from .service import CodeBuilderService, InvalidTaskState, TaskNotFound

router = APIRouter(prefix="/api/code-builder-v2", tags=["code-builder-v2"])
_service: CodeBuilderService | None = None


def configure(service: CodeBuilderService) -> None:
    global _service
    _service = service


def service() -> CodeBuilderService:
    if _service is None:
        raise RuntimeError("Code Builder V2 router is not configured")
    return _service


def _task_call(callback):
    try:
        return callback()
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except InvalidTaskState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/health")
def health() -> dict[str, object]:
    return {"status": "healthy", "version": 2, "configured": _service is not None}


@router.post("/tasks", response_model=BuildTask)
def create_task(request: TaskRequest) -> BuildTask:
    return service().create_task(request)


@router.get("/tasks/{task_id}", response_model=BuildTask)
def get_task(task_id: str) -> BuildTask:
    return _task_call(lambda: service().get_task(task_id))


@router.post("/tasks/{task_id}/execute", response_model=BuildTask)
def execute_task(task_id: str) -> BuildTask:
    return _task_call(lambda: service().execute_task(task_id))


@router.post("/tasks/{task_id}/cancel", response_model=BuildTask)
def cancel_task(task_id: str) -> BuildTask:
    return _task_call(lambda: service().cancel_task(task_id))


@router.post("/tasks/{task_id}/rollback", response_model=BuildTask)
def rollback_task(task_id: str) -> BuildTask:
    return _task_call(lambda: service().rollback_task(task_id))
