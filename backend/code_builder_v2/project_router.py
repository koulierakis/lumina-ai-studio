from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .models import BrowserEvidence, DevServerInfo, Project, ProjectStatus, TaskRequest, TaskStatus
from .project_service import ProjectService, ProjectNotFound, InvalidProjectState
from .service import CodeBuilderService, TaskNotFound, InvalidTaskState

router = APIRouter(prefix="/api/code-builder-v2/projects", tags=["code-builder-v2-projects"])
_service: ProjectService | None = None
_builder_service: CodeBuilderService | None = None


def configure(project_service: ProjectService, builder_service: CodeBuilderService | None = None) -> None:
    global _service, _builder_service
    _service = project_service
    _builder_service = builder_service


def service() -> ProjectService:
    if _service is None:
        raise RuntimeError("Code Builder V2 project service is not configured")
    return _service


def builder_service() -> CodeBuilderService | None:
    return _builder_service


class CreateProjectRequest(BaseModel):
    prompt: str
    project_name: str | None = None
    framework_hint: str | None = None
    auto_install: bool = True
    auto_start_server: bool = True


class BrowserInteractionRequest(BaseModel):
    interactions: list[dict]


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "healthy",
        "version": 2,
        "configured": _service is not None,
    }


@router.post("", response_model=Project)
def create_project(request: CreateProjectRequest) -> Project:
    return service().create_project(
        prompt=request.prompt,
        project_name=request.project_name,
        framework_hint=request.framework_hint,
    )


@router.get("", response_model=list[Project])
def list_projects() -> list[Project]:
    return service().list_projects()


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    try:
        return service().get_project(project_id)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.delete("/{project_id}")
def delete_project(project_id: str) -> dict[str, bool]:
    try:
        success = service().delete_project(project_id)
        return {"success": success}
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/install-deps")
def install_dependencies(project_id: str) -> dict[str, object]:
    try:
        success, output = service().install_dependencies(project_id)
        return {"success": success, "output": output}
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/start-server", response_model=DevServerInfo)
def start_dev_server(project_id: str, timeout: int = Query(60, ge=10, le=300)) -> DevServerInfo:
    try:
        return service().start_dev_server(project_id, timeout=timeout)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except InvalidProjectState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{project_id}/stop-server")
def stop_dev_server(project_id: str) -> dict[str, bool]:
    try:
        success = service().stop_dev_server(project_id)
        return {"success": success}
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/{project_id}/server", response_model=DevServerInfo | None)
def get_server_info(project_id: str) -> DevServerInfo | None:
    try:
        return service().get_dev_server_info(project_id)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/{project_id}/logs")
def get_server_logs(project_id: str) -> dict[str, str]:
    try:
        return {"logs": service().get_dev_server_logs(project_id)}
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/{project_id}/browser-check", response_model=BrowserEvidence)
def browser_check(
    project_id: str,
    wait_for_selector: str | None = None,
    expected_text: str | None = None,
) -> BrowserEvidence:
    try:
        return service().run_browser_check(project_id, wait_for_selector, expected_text)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except InvalidProjectState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{project_id}/browser-interaction", response_model=BrowserEvidence)
def browser_interaction(project_id: str, request: BrowserInteractionRequest) -> BrowserEvidence:
    try:
        return service().run_browser_interaction(project_id, request.interactions)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except InvalidProjectState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{project_id}/full-verification", response_model=BrowserEvidence)
def full_verification(
    project_id: str,
    expected_heading: str | None = None,
    expected_button_text: str | None = None,
    expected_message_after_click: str | None = None,
) -> BrowserEvidence:
    try:
        return service().run_full_verification(
            project_id=project_id,
            expected_heading=expected_heading,
            expected_button_text=expected_button_text,
            expected_message_after_click=expected_message_after_click,
        )
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except InvalidProjectState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{project_id}/tasks", response_model=TaskRequest)
def create_task(project_id: str, request: TaskRequest) -> TaskRequest:
    try:
        service().get_project(project_id)
        request.project_id = project_id
        return request
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc