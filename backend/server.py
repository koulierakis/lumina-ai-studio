"""Lumina AI Desktop - FastAPI backend.

Endpoints (all prefixed with /api):
  Auth:
    POST /auth/login
    GET  /auth/me
  Providers:
    GET  /providers
  Identity Packs:
    POST /identity-packs
    GET  /identity-packs
    GET  /identity-packs/{id}
    PATCH /identity-packs/{id}
    DELETE /identity-packs/{id}
    POST /identity-packs/{id}/photos    (multipart upload)
    DELETE /identity-packs/{id}/photos/{photo_id}
  Media:
    GET  /media/{id}         (returns bytes for authenticated owner)
  Generation:
    POST /generate           (creates job, runs in background)
    GET  /jobs/{id}
    GET  /jobs
  Gallery:
    GET  /gallery
    PATCH /gallery/{id}      (favorite / unfavorite)
    DELETE /gallery/{id}
  Health:
    GET  /health
"""
from __future__ import annotations
import asyncio
import ipaddress
import json
import math
import logging
import os
import io
import re
import socket
import shutil
import subprocess
import tempfile
import traceback
import wave
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from persistence import LocalPersistenceCollection, SQLitePersistenceProvider, TalkingPortraitCollection, initialize_persistence_provider, create_persistence_provider  # noqa: E402

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from auth import issue_token, require_owner, verify_credentials  # noqa: E402
from login_limiter import login_limiter  # noqa: E402
from developer_center import TASKS as DEVELOPER_TASKS, local_system_metrics, manager as developer_manager, repository_status  # noqa: E402
from models import (  # noqa: E402
    AiEditJob,
    GalleryItem,
    GenerationJob,
    GenerationRequest,
    IdentityPack,
    IdentityPackCreate,
    IdentityPackUpdate,
    Project,
    ProjectCreate,
    WorkspaceNotification,
    LoginRequest,
    MediaAsset,
    PhotoBatchJob,
    PhotoCollection,
    TokenResponse,
    VideoGenerationJob,
    VideoLibraryOrganization,
    PersonalVoiceModel,
    VoiceJob,
    VoiceExportRequest,
    VoiceLibraryOrganization,
    VoicePack,
    VoicePreset,
    VoiceProject,
    VoiceProjectVersion,
    VoiceRecordingSession,
    VideoVoiceIntegrationRequest,
    TranscriptionJob,
    TalkingFaceJob,
    TalkingPortraitInstallJob,
    TalkingPortraitJob,
    VideoBrandKit,
    VideoTemplate,
    VideoProject,
    new_id,
    now_iso,
)
from providers import (  # noqa: E402
    ErrorKind,
    GenerationInput,
    ProviderError,
    ProviderTimeoutError,
    available_providers,
    manager as provider_manager,
)
from storage import delete_file, read_bytes, save_bytes  # noqa: E402
from video_providers import VideoGenerationInput, VideoProviderError, available_video_providers, get_video_provider, video_provider_catalog  # noqa: E402
from platform_services import emit_notification  # noqa: E402
from voice_providers import get_voice_provider, voice_provider_catalog  # noqa: E402
from stt_providers import get_stt_provider, stt_provider_catalog  # noqa: E402
from talking_face_providers import get_talking_face_provider, talking_face_catalog  # noqa: E402
from talking_portrait_providers import available_talking_portrait_providers, auto_detect_talking_portrait_provider, get_talking_portrait_provider, talking_portrait_catalog, TalkingPortraitInput, TalkingPortraitProviderError  # noqa: E402
from talking_portrait_providers.base import TalkingPortraitCancelledError  # noqa: E402
from talking_portrait_providers.liveportrait_installer import ACTIVE_INSTALL_STATES, LivePortraitInstaller, build_initial_install_payload, recent_log_lines  # noqa: E402
from talking_portrait_providers.liveportrait_provider import LivePortraitProvider, latest_log_lines as latest_talking_portrait_log_lines  # noqa: E402
from fastapi import Depends  # noqa: E402

from code_builder.models import RepositoryConfiguration  # noqa: E402
from code_builder.repository_service import RepositoryService  # noqa: E402
from code_builder.backup_service import BackupService  # noqa: E402
from code_builder.ollama_service import OllamaService  # noqa: E402
from code_builder.ollama_adapter import create_ollama_task_adapter  # noqa: E402
from code_builder.planning_service import (  # noqa: E402
    PlanningConfiguration,
    PlanningService,
)
from code_builder.patch_service import PatchService  # noqa: E402
from code_builder.build_service import (  # noqa: E402
    BuildService,
    BuildServiceConfiguration,
)
from code_builder.task_service import create_task_service  # noqa: E402
from code_builder.router import (  # noqa: E402
    configure_code_builder_router,
    router as code_builder_router,
)
from document_studio.router import configure_document_studio_router, router as document_studio_router  # noqa: E402
from ai_runtime.router import router as runtime_router  # noqa: E402
from ai_runtime.manager import runtime_manager  # noqa: E402
from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus  # noqa: E402

from code_creator import create_project as code_create_project, generate_project as code_generate_project, get_project as code_get_project, list_projects as code_list_projects, ollama_status as code_ollama_status, read_file as code_read_file, run_safe_check as code_run_safe_check  # noqa: E402
from runtime_info import (  # noqa: E402
    APP_VERSION,
    build_installation_center,
    build_system_status,
    detect_local_environment,
    load_runtime_config,
    save_runtime_settings,
    validate_runtime_settings,
)

logger = logging.getLogger("lumina")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

runtime_config = load_runtime_config()

# ---------- local persistence ----------
persistence_provider = create_persistence_provider()
if isinstance(persistence_provider, SQLitePersistenceProvider):
    persistence_provider._initialize_sync()
media_coll = LocalPersistenceCollection(persistence_provider, "media")
packs_coll = LocalPersistenceCollection(persistence_provider, "identity_packs")
jobs_coll = LocalPersistenceCollection(persistence_provider, "jobs")
gallery_coll = LocalPersistenceCollection(persistence_provider, "gallery")
video_generation_jobs_coll = LocalPersistenceCollection(persistence_provider, "video_generation_jobs")
video_library_orgs_coll = LocalPersistenceCollection(persistence_provider, "video_library_organizations")
video_templates_coll = LocalPersistenceCollection(persistence_provider, "video_templates")
video_brand_kits_coll = LocalPersistenceCollection(persistence_provider, "video_brand_kits")
voice_jobs_coll = LocalPersistenceCollection(persistence_provider, "voice_jobs")
voice_library_orgs_coll = LocalPersistenceCollection(persistence_provider, "voice_library_organizations")
voice_packs_coll = LocalPersistenceCollection(persistence_provider, "voice_packs")
voice_personal_models_coll = LocalPersistenceCollection(persistence_provider, "voice_personal_models")
voice_projects_coll = LocalPersistenceCollection(persistence_provider, "voice_projects")
voice_recordings_coll = LocalPersistenceCollection(persistence_provider, "voice_recordings")
transcription_jobs_coll = LocalPersistenceCollection(persistence_provider, "transcription_jobs")
talking_face_jobs_coll = LocalPersistenceCollection(persistence_provider, "talking_face_jobs")
talking_portrait_jobs_coll = TalkingPortraitCollection(persistence_provider, "talking_portrait_jobs")
talking_portrait_installs_coll = TalkingPortraitCollection(persistence_provider, "talking_portrait_install_jobs")
projects_coll = LocalPersistenceCollection(persistence_provider, "projects")
preferences_coll = LocalPersistenceCollection(persistence_provider, "preferences")
notifications_coll = LocalPersistenceCollection(persistence_provider, "notifications")


def _configure_local_first_collections() -> None:
    global media_coll, packs_coll, gallery_coll, sessions_coll, ai_edit_jobs_coll
    if isinstance(persistence_provider, SQLitePersistenceProvider):
        if not persistence_provider.ready:
            persistence_provider._initialize_sync()
        media_coll = LocalPersistenceCollection(persistence_provider, "media")
        packs_coll = LocalPersistenceCollection(persistence_provider, "identity_packs")
        gallery_coll = LocalPersistenceCollection(persistence_provider, "gallery")
        if "sessions_coll" in globals():
            sessions_coll = LocalPersistenceCollection(persistence_provider, "editor_sessions")
        if "ai_edit_jobs_coll" in globals():
            ai_edit_jobs_coll = LocalPersistenceCollection(persistence_provider, "ai_edit_jobs")


_configure_local_first_collections()

ALLOWED_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
ALLOWED_VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm", "video/x-msvideo"}
ALLOWED_AUDIO_MIMES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB (images / mask; verified for 20 MB uploads)
MAX_VIDEO_ASSET_BYTES = 500 * 1024 * 1024  # 500 MB (video / audio for editor)
MAX_PHOTOS_PER_PACK = 5
VIDEO_STUDIO_DURATIONS = {3, 5, 8}
VIDEO_STUDIO_ASPECT_RATIOS = {"16:9", "9:16"}
IMAGE_STUDIO_IDENTITY_LOCKS = {"low", "medium", "high", "maximum"}
IMAGE_STUDIO_RATIOS = {"1:1", "16:9", "9:16", "4:5", "3:2"}
IMAGE_STUDIO_QUALITIES = {"draft", "standard", "high", "ultra"}

app = FastAPI(title="Lumina AI Desktop API")
api = APIRouter(prefix="/api")


def _image_studio_prompt_context(identity_lock: str, metadata: dict | None = None) -> str:
    metadata = metadata or {}
    level = identity_lock if identity_lock in IMAGE_STUDIO_IDENTITY_LOCKS else "high"
    preservation = {
        "low": "Preserve the main subject identity when possible.",
        "medium": "Preserve face, body proportions, skin tone, hairstyle, and age.",
        "high": "Strictly preserve face, facial proportions, wrinkles, beard, eyebrows, hairline, skin tone, age, body proportions, and hands.",
        "maximum": "Maximum Identity Lock: preserve face, facial proportions, wrinkles, beard, eyebrows, hairline, skin tone, age, body proportions, hands, expression, pose, and all non-requested subject attributes exactly whenever the provider supports it.",
    }[level]
    parts = [preservation]
    if metadata.get("style_reference_id"):
        parts.append("Use the provided style reference for lighting, color, and visual treatment without copying unrelated content.")
    if metadata.get("composition_reference_id"):
        parts.append("Use the provided composition reference for framing and layout while keeping the requested subject and prompt primary.")
    return "\n".join(parts)


def _metadata_payload(*, provider: str, prompt: str, negative_prompt: str = "", seed=None, resolution: str = "", quality: str = "", aspect_ratio: str = "", generation_time_ms=None, extra: dict | None = None) -> dict:
    payload = {
        "provider": provider,
        "model": (extra or {}).get("model") or provider,
        "seed": seed,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "resolution": resolution,
        "quality": quality,
        "aspect_ratio": aspect_ratio,
        "generation_time_ms": generation_time_ms,
        "date": now_iso(),
    }
    payload.update(extra or {})
    return payload


async def _attach_to_project(owner: str, project_id: str | None, *, media_ids: list[str] | None = None, job_id: str | None = None, activity: str = "Image Studio updated") -> None:
    if not project_id:
        return
    project = await projects_coll.find_one({"id": project_id, "owner_email": owner}, {"_id": 0})
    if not project:
        raise HTTPException(404, "Project not found")
    media_ids = [mid for mid in (media_ids or []) if mid]
    project["media_ids"] = list(dict.fromkeys((project.get("media_ids") or []) + media_ids))
    project["job_ids"] = list(dict.fromkeys((project.get("job_ids") or []) + ([job_id] if job_id else [])))
    if media_ids and not project.get("cover_media_id"):
        project["cover_media_id"] = media_ids[0]
    project.setdefault("activity", []).insert(0, {"at": now_iso(), "type": "image_studio", "message": activity})
    project["activity"] = project["activity"][:50]
    project["updated_at"] = now_iso()
    await projects_coll.replace_one({"id": project_id, "owner_email": owner}, project)


@app.middleware("http")
async def upload_transport_diagnostics(request: Request, call_next):
    content_type = request.headers.get("content-type", "")
    is_multipart = content_type.lower().startswith("multipart/form-data")
    if is_multipart:
        logger.info(
            "Upload transport request method=%s path=%s content-type=%s content-length=%s origin=%s",
            request.method,
            request.url.path,
            content_type,
            request.headers.get("content-length"),
            request.headers.get("origin"),
        )
    response = await call_next(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", None) or "unmatched"
    if is_multipart:
        logger.info(
            "Upload transport response method=%s path=%s route=%s status=%s",
            request.method,
            request.url.path,
            route_path,
            response.status_code,
        )
    response.headers["X-Lumina-Route-Matched"] = route_path
    return response

# ---------- Code Builder bootstrap ----------
CODE_BUILDER_REPOSITORY_ROOT = ROOT_DIR.parent.resolve()

code_builder_repository_service = RepositoryService(
    RepositoryConfiguration(
        repository_root=str(
            CODE_BUILDER_REPOSITORY_ROOT
        ),
    )
)

code_builder_backup_service = BackupService(
    repository_root=CODE_BUILDER_REPOSITORY_ROOT,
)

code_builder_ollama_service = OllamaService()

# Planning model strategy: every planning request runs on the fast primary
# model first; the stronger model is used only as a one-shot fallback when the
# primary model cannot produce a valid, usable plan (see
# PlanningService.create_normalized_change_plan).
CODE_BUILDER_FALLBACK_MODEL = "qwen2.5-coder:7b"

code_builder_planning_service = PlanningService(
    ollama_service=code_builder_ollama_service,
    configuration=PlanningConfiguration(
        model=str(runtime_config["preferred_ollama_model"]),
        fallback_model=CODE_BUILDER_FALLBACK_MODEL,
        context_window=int(runtime_config["code_builder_num_ctx"]),
        maximum_output_tokens=int(runtime_config["code_builder_num_predict"]),
        input_token_safety_margin=0,
    ),
)

code_builder_patch_service = PatchService(
    repository_root=CODE_BUILDER_REPOSITORY_ROOT,
)

code_builder_build_service = BuildService(
    BuildServiceConfiguration(
        repository_root=CODE_BUILDER_REPOSITORY_ROOT,
    )
)

code_builder_task_service = create_task_service(
    repository_root=CODE_BUILDER_REPOSITORY_ROOT,
    repository_service=code_builder_repository_service,
    planning_service=code_builder_planning_service,
    backup_service=code_builder_backup_service,
    patch_service=code_builder_patch_service,
    build_service=code_builder_build_service,
    ollama_service=create_ollama_task_adapter(
        code_builder_ollama_service,
        model=str(runtime_config["preferred_ollama_model"]),
    ),
)

configure_code_builder_router(
    task_service=code_builder_task_service,
    repository_service=code_builder_repository_service,
    backup_service=code_builder_backup_service,
)
configure_document_studio_router(persistence_provider, media_coll, notifications_coll)


async def _runtime_execute(owner: str, studio: str, task_type: str, provider: str | None, payload: dict, executor):
    job = RuntimeJob(owner_email=owner, studio=studio, task_type=task_type, provider=provider, payload=payload, max_retries=0)
    completed = await runtime_manager.submit(job, executor, run_background=False)
    if completed.status == RuntimeJobStatus.FAILED:
        provider_error = (completed.metadata or {}).get("provider_error")
        if isinstance(provider_error, dict):
            status_code = provider_error.get("http_status") or provider_error.get("status_code")
            raise ProviderError(
                str(provider_error.get("provider") or provider or "manager"),
                str(provider_error.get("message") or completed.error or "Provider request failed."),
                kind=ErrorKind(provider_error.get("kind") or ErrorKind.UNAVAILABLE.value),
                retryable=bool(provider_error.get("retryable")),
                status_code=status_code,
                safe_message=str(provider_error.get("message") or completed.error or "Provider request failed."),
                retry_after_seconds=provider_error.get("retry_after_seconds"),
            )
        raise RuntimeError(completed.error or "Runtime job failed")
    return completed.result, completed


def _safe_provider_failure(exc: Exception, *, provider: str | None = None, model: str | None = None) -> dict:
    if isinstance(exc, ProviderError) and isinstance(exc.__cause__, ProviderError):
        exc = exc.__cause__
    if isinstance(exc, ProviderError):
        summary = exc.safe_summary()
        resolved_provider = exc.provider or provider or "manager"
        resolved_model = model
        if resolved_provider == "gemini":
            resolved_model = model or os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
        return {
            "provider": resolved_provider,
            "model": resolved_model,
            "error_code": "RESOURCE_EXHAUSTED" if exc.kind == ErrorKind.QUOTA else exc.kind.value,
            "http_status": exc.status_code,
            "message": exc.public_message(),
            "retryable": exc.retryable,
            "retry_after_seconds": exc.retry_after_seconds,
            "kind": exc.kind.value,
            "availability_state": summary.get("availability_state"),
        }
    return {"provider": provider or "unknown", "model": model, "error_code": "UNKNOWN", "http_status": None, "message": str(exc), "retryable": False, "kind": ErrorKind.UNKNOWN.value, "availability_state": "unavailable"}


def _exception_payload(request: Request, exc: Exception, status_code: int, message: str, *, code: str) -> dict:
    return {
        "detail": {
            "code": code,
            "message": message,
            "technical_details": {
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query or ""),
            },
            "exception_type": type(exc).__name__,
        },
        "ok": False,
        "code": code,
        "message": message,
        "http_status": status_code,
        "technical_details": {
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query or ""),
            "exception_type": type(exc).__name__,
        },
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    payload = _exception_payload(request, exc, exc.status_code, detail, code=f"http_{exc.status_code}")
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    payload = _exception_payload(request, exc, 422, "Request validation failed", code="validation_error")
    payload["validation_errors"] = exc.errors()
    return JSONResponse(status_code=422, content=payload)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled backend exception on %s %s", request.method, request.url.path)
    payload = _exception_payload(request, exc, 500, str(exc) or "Unhandled backend exception", code="backend_exception")
    return JSONResponse(status_code=500, content=payload)


@app.exception_handler(ProviderError)
async def provider_error_handler(request, exc: ProviderError):
    logger.warning("Provider error: %s", exc)
    payload = _exception_payload(request, exc, 502, str(exc) or "A provider service failed. Please try again later.", code="provider_error")
    return JSONResponse(status_code=502, content=payload)


@app.exception_handler(ProviderTimeoutError)
async def provider_timeout_handler(request, exc: ProviderTimeoutError):
    logger.warning("Provider timeout: %s", exc)
    payload = _exception_payload(request, exc, 504, str(exc) or "The image provider timed out. Please try again in a moment.", code="provider_timeout")
    return JSONResponse(status_code=504, content=payload)


# ---------- Health / providers ----------
@api.get("/health")
async def health() -> dict:
    statuses = await provider_manager.statuses()
    return {
        "status": "ok",
        "backend": "ok",
        "timestamp": now_iso(),
        "version": APP_VERSION,
        "database": persistence_provider.diagnostics(),
        "provider_active": os.environ.get("IMAGE_PROVIDER", "gemini"),
        "providers_available": available_providers(),
        "provider_statuses": statuses,
        "provider_routing": await provider_manager.health_summary(),
    }


@api.get("/system/status")
async def system_status(owner: str = Depends(require_owner)) -> dict:
    active = 0
    try:
        image_q = jobs_coll.count_documents(
            {"owner_email": owner, "status": {"$in": ["queued", "processing"]}}
        )
        video_q = video_generation_jobs_coll.count_documents(
            {
                "owner_email": owner,
                "status": {"$in": ["queued", "preparing", "uploading", "processing", "rendering"]},
            }
        )
        voice_q = voice_jobs_coll.count_documents(
            {"owner_email": owner, "status": {"$in": ["queued", "processing", "rendering"]}}
        )
        active = int(await image_q) + int(await video_q) + int(await voice_q)
    except Exception:
        logger.exception("Active job count unavailable for system status")
        active = 0
    return build_system_status(active_jobs=active)


@api.get("/system/environment")
async def system_environment(owner: str = Depends(require_owner)) -> dict:
    active = 0
    try:
        active = len([job for job in runtime_manager.list_jobs(owner) if job.get("status") in {"queued", "preparing", "running", "retrying", "waiting"}])
    except Exception:
        active = 0
    return detect_local_environment(active_jobs=active)


@api.get("/system/installation-center")
async def installation_center(owner: str = Depends(require_owner)) -> dict:
    active = 0
    try:
        active = len([job for job in runtime_manager.list_jobs(owner) if job.get("status") in {"queued", "preparing", "running", "retrying", "waiting"}])
    except Exception:
        active = 0
    return build_installation_center(active_jobs=active)


@api.get("/system/runtime-settings")
async def get_runtime_settings(owner: str = Depends(require_owner)) -> dict:
    del owner
    return load_runtime_config()


@api.put("/system/runtime-settings")
async def put_runtime_settings(body: dict, owner: str = Depends(require_owner)) -> dict:
    del owner
    try:
        validate_runtime_settings(body)
        return save_runtime_settings(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------- Developer Center (local owner-only monitoring) ----------
async def _developer_health() -> dict:
    checks = []
    try:
        await persistence_provider.verify()
        checks.append({"name": "Database", "status": "ready", "detail": "Local database connection is available."})
    except Exception:
        checks.append({"name": "Database", "status": "warning", "detail": "Database connection could not be verified."})
    try:
        storage_root = ROOT_DIR / "storage"
        storage_root.mkdir(exist_ok=True)
        checks.append({"name": "Media storage", "status": "ready", "detail": "Local media storage is available."})
    except OSError:
        checks.append({"name": "Media storage", "status": "error", "detail": "Local media storage is not writable."})
    try:
        provider_statuses = await provider_manager.statuses()
    except Exception:
        provider_statuses = []
    try:
        runtime_health = runtime_manager.health()
    except Exception:
        runtime_health = {"status": "degraded", "providers": {"providers": []}, "resources": {}, "jobs": {}}
    ready_providers = [item for item in provider_statuses if item.get("configured") and item.get("healthy")]
    checks.extend([
        {"name": "Backend", "status": "ready", "detail": "LUMINA backend is responding."},
        {"name": "Frontend", "status": "working", "detail": "Check the local browser address for frontend availability."},
        {"name": "Runtime Manager", "status": "ready" if runtime_health.get("status") == "ok" else "warning", "detail": f"Runtime jobs: {runtime_health.get('jobs', {}).get('total', 0)}."},
        {"name": "Model Manager", "status": "ready", "detail": f"{len(runtime_health.get('models', {}).get('available_models', []))} model registrations available."},
        {"name": "Runtime providers", "status": "ready" if runtime_health.get("providers", {}).get("ok") else "warning", "detail": f"{len(runtime_health.get('providers', {}).get('providers', []))} runtime providers registered."},
        {"name": "Job system", "status": "ready", "detail": "Runtime queue and legacy application jobs are available."},
        {"name": "Provider system", "status": "ready" if ready_providers else "warning", "detail": f"{len(ready_providers)} configured provider(s) ready."},
    ])
    env = detect_local_environment()
    installation = build_installation_center()
    checks.extend([
        {"name": "FFmpeg", "status": "ready" if env.get("ffmpeg", {}).get("available") and env.get("ffmpeg", {}).get("ffprobe_available") else "warning", "detail": "FFmpeg/FFprobe are available for local media processing." if env.get("ffmpeg", {}).get("available") else "FFmpeg is missing; Video and Voice export processing will be limited."},
        {"name": "GPU", "status": "ready" if env.get("gpu", {}).get("available") else "warning", "detail": "GPU detected." if env.get("gpu", {}).get("available") else "No GPU capability was detected; CPU workflows remain available."},
        {"name": "Node.js", "status": "ready" if env.get("node", {}).get("available") else "error", "detail": f"Node.js {env.get('node', {}).get('version') or 'not found'}."},
        {"name": "Git", "status": "ready" if env.get("git", {}).get("available") else "warning", "detail": env.get("git", {}).get("version") or "Git is unavailable."},
    ])
    return {"checks": checks, "metrics": {**local_system_metrics(), "runtime": runtime_health.get("resources", {}), "environment": env}, "runtime": runtime_health, "environment": env, "installation_center": installation, "refreshed_at": now_iso()}


@api.get("/developer/overview")
async def developer_overview(owner: str = Depends(require_owner)) -> dict:
    panel_errors: dict[str, str] = {}
    try:
        health = await _developer_health()
    except Exception:
        health = {"checks": [{"name": "System health", "status": "warning", "detail": "Local health information is unavailable."}], "metrics": {}, "refreshed_at": now_iso()}
        panel_errors["health"] = "Local health information is unavailable."
    try:
        repository = await repository_status()
    except Exception:
        repository = {"branch": "Unavailable", "clean": False, "changed_files": [], "uncommitted_count": 0, "recent_commits": [], "last_commit": "Repository information is unavailable."}
        panel_errors["repository"] = "Repository information is unavailable."
    try:
        image_jobs = [GenerationJob(**doc) async for doc in jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(30)]
        video_jobs = [VideoGenerationJob(**doc) async for doc in video_generation_jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(30)]
        portrait_jobs = [TalkingPortraitJob(**doc) async for doc in talking_portrait_jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(30)]
    except Exception:
        image_jobs, video_jobs, portrait_jobs = [], [], []
        panel_errors["media_jobs"] = "Application job information is unavailable."
    active_media_jobs = [
        {"id": job.id, "kind": "image", "title": job.prompt or "Image generation", "status": job.status, "created_at": job.created_at}
        for job in image_jobs if job.status in {"queued", "processing"}
    ] + [
        {"id": job.id, "kind": "video", "title": job.title or "Video generation", "status": job.status, "progress": job.progress, "created_at": job.created_at}
        for job in video_jobs if job.status in {"queued", "preparing", "uploading", "processing", "rendering"}
    ] + [
        {"id": job.id, "kind": "talking-portrait", "title": job.title or "Talking portrait", "status": job.status, "progress": job.progress, "created_at": job.created_at}
        for job in portrait_jobs if job.status in TALKING_PORTRAIT_ACTIVE
    ]
    return {"health": health, "runtime": health.get("runtime", {}), "repository": repository, "talking_portrait": {"providers": talking_portrait_catalog(), "active": auto_detect_talking_portrait_provider()}, "tasks": developer_manager.list_tasks(), "logs": developer_manager.list_logs(), "media_jobs": active_media_jobs[:20], "runtime_jobs": runtime_manager.list_jobs(owner)[:30], "panel_errors": panel_errors, "refreshed_at": now_iso(), "scope": "Local LUMINA Runtime and application activity on this computer."}


@api.get("/developer/tasks")
async def developer_tasks(owner: str = Depends(require_owner)) -> dict:
    del owner
    return {"available": [{"type": key, **value} for key, value in DEVELOPER_TASKS.items()], "tasks": developer_manager.list_tasks()}


@api.post("/developer/tasks")
async def developer_start_task(body: dict, owner: str = Depends(require_owner)) -> dict:
    del owner
    task_type = str(body.get("task_type", ""))
    try:
        return await developer_manager.start(task_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/developer/tasks/{task_id}/cancel")
async def developer_cancel_task(task_id: str, owner: str = Depends(require_owner)) -> dict:
    del owner
    try:
        return await developer_manager.cancel(task_id)
    except KeyError as exc:
        raise HTTPException(404, "Developer task not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/developer/logs")
async def developer_logs(severity: str = "", source: str = "", owner: str = Depends(require_owner)) -> dict:
    del owner
    return {"logs": developer_manager.list_logs(severity=severity, source=source)}


@api.get("/developer/events")
async def developer_events(owner: str = Depends(require_owner)) -> StreamingResponse:
    del owner
    return StreamingResponse(developer_manager.events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@api.get("/providers")
async def providers(_: str = Depends(require_owner)) -> dict:
    statuses = await provider_manager.statuses()
    return {
        "active": os.environ.get("IMAGE_PROVIDER", "gemini"),
        "available": available_providers(),
        "status": statuses,
        "providers": statuses,
    }


# ---------- Auth ----------
@api.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    client_key = request.client.host if request.client else "unknown"
    retry_after = login_limiter.retry_after(client_key)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    if not verify_credentials(body.email, body.password):
        retry_after = login_limiter.record_failure(client_key)
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        status_code = 429 if retry_after else 401
        detail = (
            "Too many login attempts. Try again later."
            if retry_after
            else "Invalid credentials"
        )
        raise HTTPException(status_code, detail, headers=headers)
    login_limiter.record_success(client_key)
    email = body.email.strip().lower()
    return TokenResponse(access_token=issue_token(email), email=email)


@api.get("/auth/me")
async def me(owner: str = Depends(require_owner)) -> dict:
    return {"email": owner}


# ---------- Identity Packs ----------
@api.post("/identity-packs", response_model=IdentityPack)
async def create_pack(body: IdentityPackCreate, owner: str = Depends(require_owner)) -> IdentityPack:
    pack = IdentityPack(owner_email=owner, name=body.name.strip() or "Untitled", description=body.description or "")
    await packs_coll.insert_one(pack.model_dump())
    return pack


@api.get("/identity-packs", response_model=List[IdentityPack])
async def list_packs(owner: str = Depends(require_owner)) -> List[IdentityPack]:
    cursor = packs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1)
    return [IdentityPack(**d) async for d in cursor]


async def _get_pack(pack_id: str, owner: str) -> IdentityPack:
    doc = await packs_coll.find_one({
        "id": pack_id,
        "owner_email": owner,
    })

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Identity pack not found",
        )

    return IdentityPack(**doc)


@api.get("/identity-packs/{pack_id}", response_model=IdentityPack)
async def get_pack(
    pack_id: str,
    owner: str = Depends(require_owner),
) -> IdentityPack:
    return await _get_pack(pack_id, owner)

@api.patch("/identity-packs/{pack_id}", response_model=IdentityPack)
async def update_pack(pack_id: str, body: IdentityPackUpdate, owner: str = Depends(require_owner)) -> IdentityPack:
    pack = await _get_pack(pack_id, owner)
    data = body.model_dump(exclude_unset=True)
    if "photo_ids" in data:
        pack.photo_ids = data["photo_ids"]
    if "primary_photo_id" in data:
        pack.primary_photo_id = data["primary_photo_id"]
    if "name" in data and data["name"]:
        pack.name = data["name"]
    if "description" in data:
        pack.description = data["description"] or ""
    pack.updated_at = now_iso()
    await packs_coll.replace_one({"id": pack.id}, pack.model_dump())
    return pack


@api.delete("/identity-packs/{pack_id}")
async def delete_pack(pack_id: str, owner: str = Depends(require_owner)) -> dict:
    pack = await _get_pack(pack_id, owner)
    # Delete all reference photos owned by this pack
    for pid in pack.photo_ids:
        mdoc = await media_coll.find_one({"id": pid, "owner_email": owner})
        if mdoc:
            try:
                delete_file(mdoc["filename"], kind="reference")
            except Exception:
                pass
            await media_coll.delete_one({"id": pid})
    await packs_coll.delete_one({"id": pack_id})
    return {"ok": True}


@api.post("/identity-packs/{pack_id}/photos", response_model=IdentityPack)
async def upload_photos(
    pack_id: str,
    files: List[UploadFile] = File(...),
    owner: str = Depends(require_owner),
) -> IdentityPack:
    if not files:
        raise HTTPException(400, "No multipart file parts named 'files' were received")
    pack = await get_pack(pack_id, owner)
    remaining = MAX_PHOTOS_PER_PACK - len(pack.photo_ids)
    if remaining <= 0:
        raise HTTPException(400, f"Identity Pack already has {MAX_PHOTOS_PER_PACK} photos")

    accepted = files[:remaining]
    for f in accepted:
        mime = (f.content_type or "").lower()
        if mime not in ALLOWED_MIMES:
            raise HTTPException(400, f"Unsupported file type: {mime}")
        data = await f.read()
        if len(data) == 0:
            raise HTTPException(400, "Empty file")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB")
        filename, _abs, size = save_bytes(data, mime, kind="reference")
        media = MediaAsset(
            owner_email=owner,
            filename=filename,
            mime_type=mime,
            kind="reference",
            size_bytes=size,
        )
        await media_coll.insert_one(media.model_dump())
        pack.photo_ids.append(media.id)
        if not pack.primary_photo_id:
            pack.primary_photo_id = media.id

    pack.updated_at = now_iso()
    await packs_coll.replace_one({"id": pack.id}, pack.model_dump())
    return pack


@api.delete("/identity-packs/{pack_id}/photos/{photo_id}", response_model=IdentityPack)
async def delete_photo(pack_id: str, photo_id: str, owner: str = Depends(require_owner)) -> IdentityPack:
    pack = await _get_pack(pack_id, owner)
    if photo_id not in pack.photo_ids:
        raise HTTPException(404, "Photo not in pack")
    pack.photo_ids = [p for p in pack.photo_ids if p != photo_id]
    if pack.primary_photo_id == photo_id:
        pack.primary_photo_id = pack.photo_ids[0] if pack.photo_ids else None
    pack.updated_at = now_iso()
    await packs_coll.replace_one({"id": pack.id}, pack.model_dump())
    # remove media
    mdoc = await media_coll.find_one({"id": photo_id, "owner_email": owner})
    if mdoc:
        try:
            delete_file(mdoc["filename"], kind="reference")
        except Exception:
            pass
        await media_coll.delete_one({"id": photo_id})
    return pack

async def _get_media(media_id: str, owner: str) -> MediaAsset:
    doc = await media_coll.find_one(
        {"id": media_id, "owner_email": owner},
        {"_id": 0},
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Media not found")

    return MediaAsset(**doc)


# ---------- Media ----------
@api.get("/media/{media_id}")
async def get_media_file(media_id: str, owner: str = Depends(require_owner)):
    media = await _get_media(media_id, owner)
    kind = "reference" if media.kind == "reference" else "generated"
    try:
        data = read_bytes(media.filename, kind=kind)
    except FileNotFoundError:
        raise HTTPException(404, "File missing")
    else:
        return Response(content=data, media_type=media.mime_type)


# ---------- Generation ----------
async def _run_generation(job_id: str, owner: str, spec: GenerationRequest) -> None:
    """Background task to execute an image generation job."""
    await jobs_coll.update_one(
        {"id": job_id}, {"$set": {"status": "processing", "progress": 10, "estimated_seconds_remaining": None, "updated_at": now_iso()}}
    )
    try:
        # Load reference photos from selected identity pack (if any).
        ref_bytes: list[bytes] = []
        ref_mimes: list[str] = []
        if spec.identity_pack_id:
            pack_doc = await packs_coll.find_one(
                {"id": spec.identity_pack_id, "owner_email": owner}, {"_id": 0}
            )
            if pack_doc:
                pack = IdentityPack(**pack_doc)
                for pid in pack.photo_ids:
                    mdoc = await media_coll.find_one({"id": pid, "owner_email": owner}, {"_id": 0})
                    if not mdoc:
                        continue
                    try:
                        b = read_bytes(mdoc["filename"], kind="reference")
                        ref_bytes.append(b)
                        ref_mimes.append(mdoc.get("mime_type", "image/png"))
                    except Exception as e:
                        logger.warning("Missing reference file: %s", e)
        for ref_id in [*(spec.reference_media_ids or []), spec.style_reference_id, spec.composition_reference_id]:
            if not ref_id:
                continue
            mdoc = await media_coll.find_one({"id": ref_id, "owner_email": owner}, {"_id": 0})
            if mdoc:
                ref_bytes.append(read_bytes(mdoc["filename"], kind="reference" if mdoc.get("kind") == "reference" else "generated"))
                ref_mimes.append(mdoc.get("mime_type", "image/png"))

        if spec.identity_pack_id and not ref_bytes:
            raise RuntimeError("Identity Pack has no readable reference images")

        gen_in = GenerationInput(
            prompt=f"{_image_studio_prompt_context(spec.identity_lock, {**(spec.metadata or {}), 'style_reference_id': spec.style_reference_id, 'composition_reference_id': spec.composition_reference_id})}\n\nUser prompt: {spec.prompt}",
            negative_prompt=spec.negative_prompt or "",
            scene=spec.scene or "",
            outfit=spec.outfit or "",
            aspect_ratio=spec.aspect_ratio or "1:1",
            resolution=spec.resolution or "1024",
            quality=spec.quality or "standard",
            seed=spec.seed,
            mode=spec.mode or "text-to-image",
            identity_lock=spec.identity_lock or "high",
            metadata=spec.metadata or {},
            count=max(1, min(4, spec.count or 1)),
            reference_images=ref_bytes,
            reference_mimes=ref_mimes,
        )

        async def image_executor(runtime_job, progress):
            await progress(runtime_job, RuntimeJobStatus.RUNNING, 45, "Routing image generation provider")
            try:
                routed = await provider_manager.generate_result(gen_in, requested=spec.provider)
            except ProviderError as exc:
                runtime_job.metadata["provider_error"] = _safe_provider_failure(exc, provider=spec.provider or os.environ.get("IMAGE_PROVIDER", "gemini"))
                raise
            await progress(runtime_job, RuntimeJobStatus.RUNNING, 85, "Image provider returned results")
            return routed

        route, runtime_job = await _runtime_execute(owner, "photo", "image_generation", spec.provider, {"prompt": spec.prompt, "aspect_ratio": spec.aspect_ratio, "count": spec.count}, image_executor)
        provider_name, results = route.provider, route.images

        output_ids: list[str] = []
        for img in results:
            filename, _abs, size = save_bytes(img.data, img.mime_type, kind="generated")
            media = MediaAsset(
                owner_email=owner,
                filename=filename,
                mime_type=img.mime_type,
                kind="generated",
                size_bytes=size,
                project_id=spec.project_id,
                job_id=job_id,
                identity_pack_id=spec.identity_pack_id,
                provider=provider_name,
                metadata=_metadata_payload(provider=provider_name, prompt=spec.prompt, negative_prompt=spec.negative_prompt or "", seed=spec.seed, resolution=spec.resolution or "1024", quality=spec.quality or "standard", aspect_ratio=spec.aspect_ratio or "1:1", generation_time_ms=route.generation_duration_ms, extra={"mode": spec.mode, "identity_lock": spec.identity_lock, "scene": spec.scene, "outfit": spec.outfit, **(spec.metadata or {})}),
            )
            await media_coll.insert_one(media.model_dump())
            output_ids.append(media.id)

            gallery = GalleryItem(
                owner_email=owner,
                media_id=media.id,
                job_id=job_id,
                identity_pack_id=spec.identity_pack_id,
                project_id=spec.project_id,
                prompt=spec.prompt,
                scene=spec.scene or "",
                outfit=spec.outfit or "",
                aspect_ratio=spec.aspect_ratio or "1:1",
                provider=provider_name,
            )
            await gallery_coll.insert_one(gallery.model_dump())

        await jobs_coll.update_one(
            {"id": job_id},
            {
                "$set": {
                    "status": "completed",
                    "progress": 100,
                    "estimated_seconds_remaining": 0,
                    "output_media_ids": output_ids,
                    "provider": provider_name,
                    "selected_provider": provider_name,
                    "attempted_providers": route.attempted_providers,
                    "provider_failures": route.provider_failures,
                    "fallback_used": route.fallback_used,
                    "generation_duration_ms": route.generation_duration_ms,
                    "runtime_job_id": runtime_job.id,
                    "updated_at": now_iso(),
                }
            },
        )
        await _attach_to_project(owner, spec.project_id, media_ids=output_ids, job_id=job_id, activity="Image generation completed")
    except Exception as e:
        logger.exception("Generation failed: %s", e)
        safe_failure = _safe_provider_failure(e, provider=spec.provider or os.environ.get("IMAGE_PROVIDER", "gemini"))
        await jobs_coll.update_one(
            {"id": job_id},
            {"$set": {"status": "failed", "progress": 0, "estimated_seconds_remaining": None, "error": safe_failure["message"], "provider_failures": [safe_failure], "attempted_providers": [safe_failure["provider"]], "fallback_used": False, "updated_at": now_iso()}},
        )


@api.post("/generate", response_model=GenerationJob)
async def generate(
    body: GenerationRequest,
    background: BackgroundTasks,
    owner: str = Depends(require_owner),
) -> GenerationJob:
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(400, "Prompt is required")
    if body.aspect_ratio not in IMAGE_STUDIO_RATIOS:
        raise HTTPException(400, "Unsupported aspect ratio")
    if body.quality not in IMAGE_STUDIO_QUALITIES:
        raise HTTPException(400, "Unsupported quality preset")
    if body.identity_lock not in IMAGE_STUDIO_IDENTITY_LOCKS:
        raise HTTPException(400, "Unsupported Identity Lock level")
    if body.identity_pack_id:
        pack_doc = await packs_coll.find_one(
            {"id": body.identity_pack_id, "owner_email": owner}, {"_id": 0}
        )
        if not pack_doc:
            raise HTTPException(404, "Identity Pack not found")
        if not pack_doc.get("photo_ids"):
            raise HTTPException(400, "Identity Pack has no reference photos")
    if body.project_id:
        await _attach_to_project(owner, body.project_id, activity="Image generation queued")
    provider_name = (body.provider or os.environ.get("IMAGE_PROVIDER") or "gemini").lower()

    job = GenerationJob(
        owner_email=owner,
        provider=provider_name,
        identity_pack_id=body.identity_pack_id,
        project_id=body.project_id,
        prompt=body.prompt.strip(),
        negative_prompt=body.negative_prompt or "",
        scene=body.scene or "",
        outfit=body.outfit or "",
        aspect_ratio=body.aspect_ratio or "1:1",
        resolution=body.resolution or "1024",
        quality=body.quality or "standard",
        seed=body.seed,
        mode=body.mode or "text-to-image",
        identity_lock=body.identity_lock or "high",
        count=max(1, min(4, body.count or 1)),
    )
    await jobs_coll.insert_one(job.model_dump())
    if body.project_id:
        await _attach_to_project(owner, body.project_id, job_id=job.id, activity="Image generation queued")
    background.add_task(_run_generation, job.id, owner, body)
    return job


@api.get("/jobs/{job_id}", response_model=GenerationJob)
async def get_job(job_id: str, owner: str = Depends(require_owner)) -> GenerationJob:
    doc = await jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job not found")
    return GenerationJob(**doc)


@api.get("/jobs", response_model=List[GenerationJob])
async def list_jobs(owner: str = Depends(require_owner), limit: int = 50) -> List[GenerationJob]:
    cursor = jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(limit)
    return [GenerationJob(**d) async for d in cursor]


# ---------- Gallery ----------
@api.get("/gallery", response_model=List[GalleryItem])
async def list_gallery(
    owner: str = Depends(require_owner),
    favorite: Optional[bool] = None,
    limit: int = 200,
) -> List[GalleryItem]:
    q: dict = {"owner_email": owner}
    if favorite is not None:
        q["favorite"] = favorite
    cursor = gallery_coll.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    return [GalleryItem(**d) async for d in cursor]


@api.patch("/gallery/{item_id}", response_model=GalleryItem)
async def update_gallery(item_id: str, body: dict, owner: str = Depends(require_owner)) -> GalleryItem:
    doc = await gallery_coll.find_one({"id": item_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Gallery item not found")
    if "favorite" in body:
        doc["favorite"] = bool(body["favorite"])
    await gallery_coll.replace_one({"id": item_id}, doc)
    return GalleryItem(**doc)


@api.delete("/gallery/{item_id}")
async def delete_gallery_item(item_id: str, owner: str = Depends(require_owner)) -> dict:
    doc = await gallery_coll.find_one({"id": item_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Gallery item not found")
    # Delete underlying media file + record
    mdoc = await media_coll.find_one({"id": doc["media_id"], "owner_email": owner})
    if mdoc:
        try:
            delete_file(mdoc["filename"], kind="generated")
        except Exception:
            pass
        await media_coll.delete_one({"id": mdoc["id"]})
    await gallery_coll.delete_one({"id": item_id})
    return {"ok": True}


@api.post("/media/upload")
async def upload_image_media(
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    edit_note: str = Form("uploaded-image"),
    tags: str = Form(""),
    owner: str = Depends(require_owner),
) -> dict:
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIMES:
        raise HTTPException(400, f"Unsupported file type: {mime}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB")
    filename, _, size = save_bytes(data, mime, kind="generated")
    media = MediaAsset(owner_email=owner, filename=filename, mime_type=mime, kind="reference", size_bytes=size, project_id=project_id, edit_note=edit_note, tags=_clean_tags([t for t in re.split(r"[,\n]", tags) if t.strip()]), metadata={"original_name": file.filename or "image"})
    await media_coll.insert_one(media.model_dump())
    gallery = GalleryItem(owner_email=owner, media_id=media.id, project_id=project_id, prompt=edit_note, provider="upload", tags=media.tags)
    await gallery_coll.insert_one(gallery.model_dump())
    await _attach_to_project(owner, project_id, media_ids=[media.id], activity="Image uploaded")
    return {"media": media.model_dump(), "gallery": gallery.model_dump()}


# ---------- Editor: versions + sessions ----------
sessions_coll = LocalPersistenceCollection(persistence_provider, "editor_sessions")
ai_edit_jobs_coll = LocalPersistenceCollection(persistence_provider, "ai_edit_jobs")
photo_collections_coll = LocalPersistenceCollection(persistence_provider, "photo_collections")
photo_batch_jobs_coll = LocalPersistenceCollection(persistence_provider, "photo_batch_jobs")
_configure_local_first_collections()

AI_EDIT_TO_JOB_STATUS = {"queued": "queued", "processing": "processing", "completed": "completed", "failed": "failed", "canceled": "cancelled"}


# Prompt scaffolding per AI editing tool. Frontend passes the tool key.
AI_TOOL_PROMPTS = {
    "retouch": (
        "Perform an identity-safe retouch. Remove distracting temporary blemishes "
        "only (dust, stray hairs); PRESERVE natural age, skin texture, pores, "
        "wrinkles, freckles, moles, and asymmetry. Do NOT smooth skin. Do NOT "
        "beautify. Do NOT make the person younger."
    ),
    "enhance": (
        "Improve overall image quality: subtle contrast and color balance, restore "
        "natural tones. Do NOT beautify the person, do NOT alter identity."
    ),
    "upscale": (
        "Reconstruct a higher-resolution version of this image with faithful "
        "detail. Preserve every identity feature and every existing element."
    ),
    "sharpen": (
        "Improve perceived sharpness and micro-detail without introducing halos. "
        "Preserve identity and natural skin texture."
    ),
    "remove_bg": (
        "Isolate the main subject from the background. Return the subject on a "
        "clean transparent or neutral background (transparent PNG if supported). "
        "Preserve hair edges precisely and identity exactly."
    ),
    "replace_bg": (
        "Replace ONLY the background. Keep the subject, their pose, their clothes "
        "and their identity untouched. Adapt lighting and shadows to match the "
        "new background naturally."
    ),
    "blur_bg": (
        "Apply a natural photographic depth-of-field blur to the background only. "
        "Keep the subject fully sharp. Preserve identity."
    ),
    "change_clothes": (
        "Change only the person's clothing to match the description. Keep face, "
        "hair, skin, body, pose, background, and lighting unchanged. Preserve "
        "identity exactly."
    ),
    "change_location": (
        "Place the same person into the described new location. Preserve identity, "
        "pose, and outfit unless the instruction says otherwise. Adapt lighting."
    ),
    "remove_object": (
        "Remove the object indicated by the mask (or described) and fill the area "
        "seamlessly to match surrounding geometry, textures, and lighting."
    ),
    "replace_object": (
        "Replace the masked or described object with the requested replacement. "
        "Match surrounding lighting, geometry, and perspective."
    ),
    "outpaint": (
        "Extend the image beyond its current borders. Only generate new content "
        "in the empty extension area; keep the original pixels of the source "
        "image exactly. Preserve style, lighting, perspective, and identity."
    ),
    "relight": (
        "Relight the scene according to the instruction while preserving identity, "
        "outfit, background elements, and composition."
    ),
    "restore": (
        "Restore this low-resolution or degraded image. Reconstruct sharp, "
        "photorealistic detail. Preserve identity and every existing element."
    ),
    "generate": (
        "Generate a production-quality photorealistic image from the prompt. "
        "Use all provided reference images for subject consistency, style, and composition."
    ),
    "inpaint": (
        "Edit only the masked area using the instruction. Preserve unmasked pixels, "
        "composition, lighting, and identity exactly."
    ),
    "expand": (
        "Expand the canvas to the requested size and synthesize only missing areas. "
        "Keep original pixels unchanged and preserve perspective."
    ),
    "face_restore": (
        "Restore facial detail while preserving exact identity, age, expression, moles, "
        "skin texture, and natural asymmetry. Do not beautify."
    ),
    "identity_preserve": (
        "Use all reference photos to preserve the person's consistent facial identity "
        "across the requested generated or edited scene."
    ),
    "style_transfer": (
        "Transfer the requested visual style while preserving subject identity, structure, "
        "composition, and important content."
    ),
    "color_correct": (
        "Perform professional color correction with neutral white balance, accurate skin "
        "tones, clean contrast, and natural saturation."
    ),
    "hdr": (
        "Create a natural HDR enhancement by recovering highlight and shadow detail "
        "without halos or oversaturation."
    ),
    "skin_cleanup": (
        "Clean only temporary skin distractions. Preserve real skin texture, pores, age, "
        "freckles, scars, moles, and identity."
    ),
    "portrait_enhance": (
        "Enhance portrait lighting, catchlights, tone, and detail naturally while preserving "
        "identity, age, expression, and skin realism."
    ),
    "watermark_remove_legal": (
        "Remove only watermarks or marks the user owns or is legally authorized to remove. "
        "Fill the region naturally while preserving surrounding content."
    ),
    "perspective_correct": (
        "Correct perspective and lens distortion while preserving image content, framing, "
        "straight architectural lines, and natural proportions."
    ),
}
AI_TOOLS = list(AI_TOOL_PROMPTS.keys())


def _clean_tags(raw) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for tag in raw or []:
        cleaned = str(tag).strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        tags.append(cleaned)
    return tags[:30]


async def _run_ai_edit(job_id: str, owner: str) -> None:
    """Background task: run one AI edit job."""
    doc = await ai_edit_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        return
    job = AiEditJob(**doc)
    await ai_edit_jobs_coll.update_one(
        {"id": job_id}, {"$set": {"status": "processing", "updated_at": now_iso()}}
    )
    await jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "processing", "progress": 20, "updated_at": now_iso()}})
    try:
        # Load source
        src_doc = await media_coll.find_one({"id": job.source_media_id, "owner_email": owner}, {"_id": 0})
        if not src_doc:
            raise RuntimeError("Source media not found")
        src_kind = "reference" if src_doc.get("kind") == "reference" else "generated"
        src_bytes = read_bytes(src_doc["filename"], kind=src_kind)
        src_mime = src_doc.get("mime_type", "image/png")

        # Load mask if any
        mask_bytes: Optional[bytes] = None
        mask_mime: Optional[str] = None
        if job.mask_media_id:
            m_doc = await media_coll.find_one({"id": job.mask_media_id, "owner_email": owner}, {"_id": 0})
            if m_doc:
                m_kind = "reference" if m_doc.get("kind") == "reference" else "generated"
                mask_bytes = read_bytes(m_doc["filename"], kind=m_kind)
                mask_mime = m_doc.get("mime_type", "image/png")

        # Load identity refs
        identity_refs: list[bytes] = []
        if job.identity_pack_id:
            pack = await packs_coll.find_one({"id": job.identity_pack_id, "owner_email": owner}, {"_id": 0})
            if pack:
                for pid in pack.get("photo_ids", []):
                    md = await media_coll.find_one({"id": pid, "owner_email": owner}, {"_id": 0})
                    if md:
                        try:
                            identity_refs.append(read_bytes(md["filename"], kind="reference"))
                        except Exception:
                            pass
        for ref_id in job.reference_media_ids:
            md = await media_coll.find_one({"id": ref_id, "owner_email": owner}, {"_id": 0})
            if md:
                try:
                    identity_refs.append(read_bytes(md["filename"], kind="reference" if md.get("kind") == "reference" else "generated"))
                except Exception:
                    pass

        base_prompt = AI_TOOL_PROMPTS.get(job.tool, AI_TOOL_PROMPTS["enhance"])
        full_instruction = f"{_image_studio_prompt_context(job.identity_lock, job.export_options)}\n{base_prompt}\nUser instruction: {job.instruction}" if job.instruction else f"{_image_studio_prompt_context(job.identity_lock, job.export_options)}\n{base_prompt}"

        async def image_edit_executor(runtime_job, progress):
            await progress(runtime_job, RuntimeJobStatus.RUNNING, 45, "Routing image editing provider")
            routed = await provider_manager.edit_result(
                source_bytes=src_bytes,
                source_mime=src_mime,
                instruction=full_instruction,
                mask_bytes=mask_bytes,
                mask_mime=mask_mime,
                identity_refs=identity_refs or None,
                requested=job.provider,
            )
            await progress(runtime_job, RuntimeJobStatus.RUNNING, 85, "Image edit provider returned result")
            return routed

        route, runtime_job = await _runtime_execute(owner, "photo", "image_editing", job.provider, {"tool": job.tool, "source_media_id": job.source_media_id}, image_edit_executor)
        result = route.images[0]

        # Claim the short persistence phase atomically. If cancellation won the
        # race while the provider was running, do not write any output media.
        finalize = await ai_edit_jobs_coll.update_one(
            {"id": job_id, "owner_email": owner, "status": "processing"},
            {"$set": {"status": "finalizing", "updated_at": now_iso()}},
        )
        if not finalize.modified_count:
            current = await ai_edit_jobs_coll.find_one(
                {"id": job_id, "owner_email": owner}, {"_id": 0}
            )
            if not current or current.get("status") == "canceled":
                await jobs_coll.update_one(
                    {"id": job_id, "owner_email": owner},
                    {"$set": {"status": "cancelled", "updated_at": now_iso()}},
                )
                return
            raise RuntimeError("AI edit could not enter final persistence phase")

        filename, _abs, size = save_bytes(result.data, result.mime_type, kind="generated")
        out_media = MediaAsset(
            owner_email=owner,
            filename=filename,
            mime_type=result.mime_type,
            kind="edited",
            parent_media_id=job.source_media_id,
            edit_note=f"AI: {job.tool}",
            size_bytes=size,
            project_id=job.project_id or src_doc.get("project_id"),
            job_id=job.id,
            identity_pack_id=job.identity_pack_id or src_doc.get("identity_pack_id"),
            provider=route.provider,
            metadata=_metadata_payload(provider=route.provider, prompt=job.instruction or AI_TOOL_PROMPTS.get(job.tool, ""), seed=job.export_options.get("seed"), resolution=str(job.export_options.get("resolution") or "source"), quality=str(job.export_options.get("quality") or "standard"), generation_time_ms=route.generation_duration_ms, extra={"tool": job.tool, "identity_lock": job.identity_lock, "source_media_id": job.source_media_id, "references": job.reference_media_ids, "export": job.export_options}),
        )
        await media_coll.insert_one(out_media.model_dump())

        parent_gallery = await gallery_coll.find_one(
            {"media_id": job.source_media_id, "owner_email": owner}, {"_id": 0}
        )
        gallery = GalleryItem(
            owner_email=owner,
            media_id=out_media.id,
            job_id=job.id,
            identity_pack_id=job.identity_pack_id or (parent_gallery or {}).get("identity_pack_id"),
            project_id=job.project_id or (parent_gallery or {}).get("project_id") or src_doc.get("project_id"),
            prompt=f"AI {job.tool}: {job.instruction}"[:500],
            scene=(parent_gallery or {}).get("scene", ""),
            outfit=(parent_gallery or {}).get("outfit", ""),
            aspect_ratio=(parent_gallery or {}).get("aspect_ratio", "1:1"),
            provider=f"{route.provider}:{job.tool}",
            tags=_clean_tags((parent_gallery or {}).get("tags", []) + [job.tool.replace("_", "-")]),
            collection_ids=(parent_gallery or {}).get("collection_ids", []),
        )
        await gallery_coll.insert_one(gallery.model_dump())

        await ai_edit_jobs_coll.update_one(
            {"id": job_id, "status": {"$ne": "canceled"}},
            {
                "$set": {
                    "status": "completed",
                    "output_media_id": out_media.id,
                    "provider": route.provider,
                    "selected_provider": route.provider,
                    "attempted_providers": route.attempted_providers,
                    "provider_failures": route.provider_failures,
                    "fallback_used": route.fallback_used,
                    "generation_duration_ms": route.generation_duration_ms,
                    "runtime_job_id": runtime_job.id,
                    "updated_at": now_iso(),
                }
            },
        )
        await jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "completed", "progress": 100, "estimated_seconds_remaining": 0, "output_media_ids": [out_media.id], "provider": route.provider, "selected_provider": route.provider, "attempted_providers": route.attempted_providers, "provider_failures": route.provider_failures, "fallback_used": route.fallback_used, "generation_duration_ms": route.generation_duration_ms, "runtime_job_id": runtime_job.id, "updated_at": now_iso()}})
        await _attach_to_project(owner, job.project_id or src_doc.get("project_id"), media_ids=[out_media.id], job_id=job.id, activity=f"Image edit completed: {job.tool}")
    except Exception as e:
        logger.exception("AI edit failed: %s", e)
        await ai_edit_jobs_coll.update_one(
            {"id": job_id, "status": {"$ne": "canceled"}},
            {"$set": {"status": "failed", "error": getattr(e, "safe_message", None) or str(e), "updated_at": now_iso()}},
        )
        await jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "failed", "progress": 0, "error": getattr(e, "safe_message", None) or str(e), "updated_at": now_iso()}})


@api.get("/editor/ai-tools")
async def list_ai_tools(_: str = Depends(require_owner)) -> dict:
    """Return the tool catalog + which tools are supported by the active provider."""
    active = os.environ.get("IMAGE_PROVIDER", "gemini")
    return {
        "active_provider": active,
        "tools": [
            {"key": k, "description": AI_TOOL_PROMPTS[k].split(".")[0]} for k in AI_TOOLS
        ],
    }


@api.post("/editor/ai-edit", response_model=AiEditJob)
async def create_ai_edit(
    background: BackgroundTasks,
    source_media_id: str = Form(...),
    tool: str = Form(...),
    instruction: str = Form(""),
    project_id: Optional[str] = Form(None),
    identity_pack_id: Optional[str] = Form(None),
    identity_lock: str = Form("high"),
    reference_media_ids: str = Form(""),
    export_options: str = Form(""),
    mask: Optional[UploadFile] = File(None),
    provider: Optional[str] = Form(None),
    owner: str = Depends(require_owner),
) -> AiEditJob:
    if tool not in AI_TOOL_PROMPTS:
        raise HTTPException(400, f"Unknown tool: {tool}")
    if identity_lock not in IMAGE_STUDIO_IDENTITY_LOCKS:
        raise HTTPException(400, "Unsupported Identity Lock level")

    src = await media_coll.find_one({"id": source_media_id, "owner_email": owner}, {"_id": 0})
    if not src:
        raise HTTPException(404, "Source media not found")

    refs = [r.strip() for r in reference_media_ids.split(",") if r.strip()][:12]
    for ref_id in refs:
        if not await media_coll.find_one({"id": ref_id, "owner_email": owner}, {"_id": 0}):
            raise HTTPException(400, f"Reference media not found: {ref_id}")

    parsed_export_options: dict = {}
    if export_options.strip():
        try:
            import json
            parsed_export_options = json.loads(export_options)
        except Exception:
            raise HTTPException(400, "Invalid export_options JSON")

    provider_name = (provider or os.environ.get("IMAGE_PROVIDER") or "gemini").lower()

    mask_media_id: Optional[str] = None
    if mask is not None:
        m_mime = (mask.content_type or "").lower()
        if m_mime not in ALLOWED_MIMES:
            raise HTTPException(400, f"Unsupported mask mime: {m_mime}")
        m_data = await mask.read()
        if not m_data:
            raise HTTPException(400, "Empty mask")
        if len(m_data) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Mask too large")
        m_filename, _, m_size = save_bytes(m_data, m_mime, kind="reference")
        m_media = MediaAsset(
            owner_email=owner, filename=m_filename, mime_type=m_mime,
            kind="reference", size_bytes=m_size, edit_note="mask",
        )
        await media_coll.insert_one(m_media.model_dump())
        mask_media_id = m_media.id

    job = AiEditJob(
        owner_email=owner,
        provider=provider_name,
        tool=tool,
        source_media_id=source_media_id,
        project_id=project_id or src.get("project_id"),
        identity_pack_id=identity_pack_id,
        instruction=instruction or "",
        identity_lock=identity_lock,
        mask_media_id=mask_media_id,
        reference_media_ids=refs,
        export_options=parsed_export_options,
    )
    await ai_edit_jobs_coll.insert_one(job.model_dump())
    generation_job = GenerationJob(owner_email=owner, id=job.id, provider=provider_name, project_id=job.project_id, identity_pack_id=identity_pack_id, prompt=f"AI {tool}: {instruction}"[:500], negative_prompt="", scene="", outfit="", aspect_ratio=str(parsed_export_options.get("aspect_ratio") or "1:1"), resolution=str(parsed_export_options.get("resolution") or "source"), quality=str(parsed_export_options.get("quality") or "standard"), mode=f"edit:{tool}", identity_lock=identity_lock, count=1)
    await jobs_coll.insert_one(generation_job.model_dump())
    if job.project_id:
        await _attach_to_project(owner, job.project_id, job_id=job.id, activity=f"Image edit queued: {tool}")
    background.add_task(_run_ai_edit, job.id, owner)
    return job


@api.get("/editor/ai-jobs/{job_id}", response_model=AiEditJob)
async def get_ai_job(job_id: str, owner: str = Depends(require_owner)) -> AiEditJob:
    doc = await ai_edit_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job not found")
    return AiEditJob(**doc)


@api.get("/editor/ai-jobs", response_model=List[AiEditJob])
async def list_ai_jobs(
    owner: str = Depends(require_owner),
    source_media_id: Optional[str] = None,
    limit: int = 50,
) -> List[AiEditJob]:
    q: dict = {"owner_email": owner}
    if source_media_id:
        q["source_media_id"] = source_media_id
    cursor = ai_edit_jobs_coll.find(q, {"_id": 0}).sort("created_at", -1).limit(limit)
    return [AiEditJob(**d) async for d in cursor]


@api.post("/editor/ai-jobs/{job_id}/retry", response_model=AiEditJob)
async def retry_ai_job(job_id: str, background: BackgroundTasks, owner: str = Depends(require_owner)) -> AiEditJob:
    doc = await ai_edit_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job not found")
    original = AiEditJob(**doc)
    if original.status not in ("failed", "canceled"):
        raise HTTPException(400, "Only failed or canceled jobs can be retried")
    new_job = AiEditJob(
        owner_email=owner,
        provider=original.provider,
        tool=original.tool,
        source_media_id=original.source_media_id,
        project_id=original.project_id,
        identity_pack_id=original.identity_pack_id,
        instruction=original.instruction,
        identity_lock=original.identity_lock,
        mask_media_id=original.mask_media_id,
        reference_media_ids=original.reference_media_ids,
        export_options=original.export_options,
        retry_of=original.id,
    )
    await ai_edit_jobs_coll.insert_one(new_job.model_dump())
    generation_job = GenerationJob(owner_email=owner, id=new_job.id, provider=new_job.provider, project_id=new_job.project_id, identity_pack_id=new_job.identity_pack_id, prompt=f"AI {new_job.tool}: {new_job.instruction}"[:500], aspect_ratio=str(new_job.export_options.get("aspect_ratio") or "1:1"), resolution=str(new_job.export_options.get("resolution") or "source"), quality=str(new_job.export_options.get("quality") or "standard"), mode=f"edit:{new_job.tool}", identity_lock=new_job.identity_lock, count=1)
    await jobs_coll.insert_one(generation_job.model_dump())
    background.add_task(_run_ai_edit, new_job.id, owner)
    return new_job


@api.post("/editor/ai-jobs/{job_id}/cancel", response_model=AiEditJob)
async def cancel_ai_job(job_id: str, owner: str = Depends(require_owner)) -> AiEditJob:
    doc = await ai_edit_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job not found")
    job = AiEditJob(**doc)
    if job.status not in ("queued", "processing"):
        raise HTTPException(400, "Only queued or processing jobs can be canceled")
    await ai_edit_jobs_coll.update_one(
        {"id": job_id}, {"$set": {"status": "canceled", "updated_at": now_iso()}}
    )
    await jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "cancelled", "updated_at": now_iso()}})
    return AiEditJob(**{**job.model_dump(), "status": "canceled", "updated_at": now_iso()})


@api.post("/editor/versions")
async def save_edited_version(
    source_media_id: str = Form(...),
    edit_note: str = Form(""),
    tags: str = Form(""),
    collection_ids: str = Form(""),
    metadata_json: str = Form(""),
    file: UploadFile = File(...),
    owner: str = Depends(require_owner),
) -> dict:
    """Persist a canvas-rendered edited image as a new MediaAsset + Gallery item.

    The frontend flattens all non-destructive edits (transform + adjustments +
    filter + text layers) into a single blob and uploads it here. The original
    MediaAsset is never modified; the new asset is linked via parent_media_id.
    """
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIMES:
        raise HTTPException(400, f"Unsupported file type: {mime}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB")

    # Verify parent exists and is owned by requester.
    parent = await media_coll.find_one({"id": source_media_id, "owner_email": owner}, {"_id": 0})
    if not parent:
        raise HTTPException(404, "Source media not found")

    metadata = {}
    if metadata_json.strip():
        try:
            import json
            metadata = json.loads(metadata_json)
        except Exception:
            raise HTTPException(400, "Invalid metadata_json")
    tag_list = _clean_tags([t for t in re.split(r"[,\n]", tags) if t.strip()])
    coll_ids = [c.strip() for c in collection_ids.split(",") if c.strip()][:20]

    filename, _abs, size = save_bytes(data, mime, kind="generated")  # store next to generated
    media = MediaAsset(
        owner_email=owner,
        filename=filename,
        mime_type=mime,
        kind="edited",
        parent_media_id=source_media_id,
        edit_note=edit_note or None,
        size_bytes=size,
        tags=tag_list or _clean_tags(parent.get("tags", [])),
        collection_ids=coll_ids or parent.get("collection_ids", []),
        project_id=parent.get("project_id"),
        identity_pack_id=parent.get("identity_pack_id"),
        metadata=metadata,
    )
    await media_coll.insert_one(media.model_dump())

    # Copy relevant context from parent gallery entry (prompt/scene/pack) if present.
    parent_gallery = await gallery_coll.find_one(
        {"media_id": source_media_id, "owner_email": owner}, {"_id": 0}
    )
    gallery = GalleryItem(
        owner_email=owner,
        media_id=media.id,
        job_id=None,
        identity_pack_id=(parent_gallery or {}).get("identity_pack_id"),
        prompt=(edit_note or (parent_gallery or {}).get("prompt", "")),
        scene=(parent_gallery or {}).get("scene", ""),
        outfit=(parent_gallery or {}).get("outfit", ""),
        aspect_ratio=(parent_gallery or {}).get("aspect_ratio", "1:1"),
        provider="editor",
        tags=media.tags,
        collection_ids=media.collection_ids,
    )
    await gallery_coll.insert_one(gallery.model_dump())
    return {"media": media.model_dump(), "gallery": gallery.model_dump()}


@api.get("/editor/versions/{media_id}")
async def list_versions(media_id: str, owner: str = Depends(require_owner)) -> List[dict]:
    """Return all edited versions descended from a source media id."""
    cursor = media_coll.find(
        {"parent_media_id": media_id, "owner_email": owner}, {"_id": 0}
    ).sort("created_at", -1)
    return [d async for d in cursor]


@api.patch("/editor/versions/{version_id}")
async def update_version(version_id: str, body: dict, owner: str = Depends(require_owner)) -> dict:
    update = {k: v for k, v in body.items() if k in {"edit_note", "tags", "favorite", "collection_ids", "project_id", "metadata"}}
    if "tags" in update:
        update["tags"] = _clean_tags(update["tags"])
    if "collection_ids" in update:
        update["collection_ids"] = [str(x).strip() for x in update["collection_ids"] if str(x).strip()][:20]
    doc = await media_coll.find_one_and_update({"id": version_id, "owner_email": owner}, {"$set": update}, return_document=True, projection={"_id": 0})
    if not doc:
        raise HTTPException(404, "Version not found")
    await gallery_coll.update_many({"media_id": version_id, "owner_email": owner}, {"$set": {k: v for k, v in update.items() if k in {"tags", "favorite", "collection_ids"}}})
    return doc


@api.post("/editor/versions/{version_id}/duplicate")
async def duplicate_version(version_id: str, owner: str = Depends(require_owner)) -> dict:
    doc = await media_coll.find_one({"id": version_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Version not found")
    data = read_bytes(doc["filename"], kind="reference" if doc.get("kind") == "reference" else "generated")
    filename, _, size = save_bytes(data, doc.get("mime_type", "image/png"), kind="generated")
    duplicate = MediaAsset(**{k: v for k, v in doc.items() if k not in {"id", "filename", "created_at", "size_bytes"}}, filename=filename, size_bytes=size, parent_media_id=doc.get("parent_media_id") or version_id, edit_note=f"{doc.get('edit_note') or 'Version'} copy")
    await media_coll.insert_one(duplicate.model_dump())
    gallery = GalleryItem(owner_email=owner, media_id=duplicate.id, job_id=duplicate.job_id, identity_pack_id=duplicate.identity_pack_id, project_id=duplicate.project_id, prompt=duplicate.edit_note or "Duplicated version", provider=duplicate.provider or "editor", tags=duplicate.tags, collection_ids=duplicate.collection_ids)
    await gallery_coll.insert_one(gallery.model_dump())
    return {"media": duplicate.model_dump(), "gallery": gallery.model_dump()}


@api.delete("/editor/versions/{version_id}")
async def delete_version(version_id: str, owner: str = Depends(require_owner)) -> dict:
    doc = await media_coll.find_one({"id": version_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Version not found")
    try:
        delete_file(doc["filename"], kind="reference" if doc.get("kind") == "reference" else "generated")
    except Exception:
        logger.warning("Unable to delete version file %s", version_id)
    await media_coll.delete_one({"id": version_id, "owner_email": owner})
    await gallery_coll.delete_many({"media_id": version_id, "owner_email": owner})
    return {"ok": True}


@api.get("/editor/sessions/{media_id}")
async def get_session(media_id: str, owner: str = Depends(require_owner)) -> dict:
    doc = await sessions_coll.find_one({"media_id": media_id, "owner_email": owner}, {"_id": 0})
    return doc or {}


@api.put("/editor/sessions/{media_id}")
async def put_session(media_id: str, body: dict, owner: str = Depends(require_owner)) -> dict:
    doc = {
        "owner_email": owner,
        "media_id": media_id,
        "state": body.get("state") or {},
        "updated_at": now_iso(),
    }
    await sessions_coll.replace_one(
        {"media_id": media_id, "owner_email": owner}, doc, upsert=True
    )
    return {"ok": True}


@api.delete("/editor/sessions/{media_id}")
async def clear_session(media_id: str, owner: str = Depends(require_owner)) -> dict:
    await sessions_coll.delete_one({"media_id": media_id, "owner_email": owner})
    return {"ok": True}


@api.get("/photo-studio/library")
async def photo_library(
    q: str = "",
    favorite: Optional[bool] = None,
    tags: str = "",
    collection_id: str = "",
    owner: str = Depends(require_owner),
) -> dict:
    query: dict = {"owner_email": owner, "mime_type": {"$regex": "^image/", "$options": "i"}}
    if favorite is not None:
        query["favorite"] = favorite
    if collection_id:
        query["collection_ids"] = collection_id
    wanted_tags = _clean_tags([t for t in re.split(r"[,\s]+", tags) if t.strip()])
    if wanted_tags:
        query["tags"] = {"$all": wanted_tags}
    if q.strip():
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"edit_note": pattern}, {"tags": pattern}, {"metadata.title": pattern}, {"metadata.description": pattern}]
    items = [doc async for doc in media_coll.find(query, {"_id": 0}).sort("created_at", -1).limit(250)]
    collections = [PhotoCollection(**doc) async for doc in photo_collections_coll.find({"owner_email": owner}, {"_id": 0}).sort("updated_at", -1)]
    return {"items": items, "collections": [c.model_dump() for c in collections], "count": len(items)}


@api.post("/photo-studio/collections", response_model=PhotoCollection)
async def create_photo_collection(body: dict, owner: str = Depends(require_owner)) -> PhotoCollection:
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Collection name is required")
    collection = PhotoCollection(owner_email=owner, name=name, description=str(body.get("description") or ""), tags=_clean_tags(body.get("tags", [])))
    await photo_collections_coll.insert_one(collection.model_dump())
    return collection


@api.patch("/photo-studio/collections/{collection_id}", response_model=PhotoCollection)
async def update_photo_collection(collection_id: str, body: dict, owner: str = Depends(require_owner)) -> PhotoCollection:
    doc = await photo_collections_coll.find_one({"id": collection_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Collection not found")
    for field in ("name", "description", "media_ids"):
        if field in body:
            doc[field] = body[field]
    if "tags" in body:
        doc["tags"] = _clean_tags(body["tags"])
    doc["updated_at"] = now_iso()
    await photo_collections_coll.replace_one({"id": collection_id, "owner_email": owner}, doc)
    return PhotoCollection(**doc)


@api.patch("/photo-studio/media/{media_id}")
async def update_photo_media(media_id: str, body: dict, owner: str = Depends(require_owner)) -> dict:
    allowed = {"favorite", "tags", "collection_ids", "project_id", "edit_note", "metadata"}
    update = {k: v for k, v in body.items() if k in allowed}
    if "tags" in update:
        update["tags"] = _clean_tags(update["tags"])
    if "collection_ids" in update:
        update["collection_ids"] = [str(x).strip() for x in update["collection_ids"] if str(x).strip()][:20]
    if "metadata" in update and not isinstance(update["metadata"], dict):
        raise HTTPException(400, "metadata must be an object")
    doc = await media_coll.find_one_and_update({"id": media_id, "owner_email": owner}, {"$set": update}, return_document=True, projection={"_id": 0})
    if not doc:
        raise HTTPException(404, "Media not found")
    await gallery_coll.update_many({"media_id": media_id, "owner_email": owner}, {"$set": {k: v for k, v in update.items() if k in {"favorite", "tags", "collection_ids"}}})
    return doc


@api.get("/photo-studio/media/{media_id}/metadata")
async def photo_metadata(media_id: str, owner: str = Depends(require_owner)) -> dict:
    media = await media_coll.find_one({"id": media_id, "owner_email": owner}, {"_id": 0})
    if not media:
        raise HTTPException(404, "Media not found")
    lineage = []
    parent = media.get("parent_media_id")
    while parent:
        doc = await media_coll.find_one({"id": parent, "owner_email": owner}, {"_id": 0})
        if not doc:
            break
        lineage.append(doc)
        parent = doc.get("parent_media_id")
    versions = [doc async for doc in media_coll.find({"parent_media_id": media_id, "owner_email": owner}, {"_id": 0}).sort("created_at", -1)]
    jobs = [AiEditJob(**doc).model_dump() async for doc in ai_edit_jobs_coll.find({"source_media_id": media_id, "owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(50)]
    return {"media": media, "lineage": lineage, "versions": versions, "ai_jobs": jobs}


@api.post("/photo-studio/batch", response_model=PhotoBatchJob)
async def create_photo_batch(body: dict, background: BackgroundTasks, owner: str = Depends(require_owner)) -> PhotoBatchJob:
    source_ids = [str(x).strip() for x in body.get("source_media_ids", []) if str(x).strip()][:100]
    if not source_ids:
        raise HTTPException(400, "source_media_ids are required")
    for media_id in source_ids:
        if not await media_coll.find_one({"id": media_id, "owner_email": owner}, {"_id": 0}):
            raise HTTPException(404, f"Media not found: {media_id}")
    operations = body.get("operations") or {}
    batch = PhotoBatchJob(owner_email=owner, source_media_ids=source_ids, operations=operations, status="processing" if operations.get("ai_tool") else "completed")
    updates = {}
    if "tags" in operations:
        updates["tags"] = _clean_tags(operations.get("tags"))
    if "collection_ids" in operations:
        updates["collection_ids"] = [str(x).strip() for x in operations.get("collection_ids", []) if str(x).strip()][:20]
    if "favorite" in operations:
        updates["favorite"] = bool(operations["favorite"])
    if updates:
        await media_coll.update_many({"id": {"$in": source_ids}, "owner_email": owner}, {"$set": updates})
        await gallery_coll.update_many({"media_id": {"$in": source_ids}, "owner_email": owner}, {"$set": {k: v for k, v in updates.items() if k in {"favorite", "tags", "collection_ids"}}})
    batch.output_media_ids = source_ids
    await photo_batch_jobs_coll.insert_one(batch.model_dump())
    if operations.get("ai_tool"):
        output_ids: list[str] = []
        for media_id in source_ids:
            job = AiEditJob(owner_email=owner, provider=str(operations.get("provider") or os.environ.get("IMAGE_PROVIDER") or "gemini").lower(), tool=str(operations.get("ai_tool")), source_media_id=media_id, project_id=operations.get("project_id"), identity_pack_id=operations.get("identity_pack_id"), instruction=str(operations.get("instruction") or ""), identity_lock=str(operations.get("identity_lock") or "high"), reference_media_ids=[str(x) for x in operations.get("reference_media_ids", []) if str(x)], export_options={k: v for k, v in operations.items() if k not in {"ai_tool", "instruction", "reference_media_ids"}})
            await ai_edit_jobs_coll.insert_one(job.model_dump())
            gen_job = GenerationJob(owner_email=owner, id=job.id, provider=job.provider, project_id=job.project_id, identity_pack_id=job.identity_pack_id, prompt=f"Batch AI {job.tool}: {job.instruction}"[:500], mode=f"batch-edit:{job.tool}", identity_lock=job.identity_lock, count=1)
            await jobs_coll.insert_one(gen_job.model_dump())
            background.add_task(_run_ai_edit, job.id, owner)
            output_ids.append(job.id)
        batch.output_media_ids = output_ids
        await photo_batch_jobs_coll.replace_one({"id": batch.id, "owner_email": owner}, batch.model_dump())
    return batch


# ---------- Video Editor: projects + asset uploads ----------
video_projects_coll = LocalPersistenceCollection(persistence_provider, "video_projects")


# ---------- Video Studio: provider-neutral image-to-video generation ----------
async def _run_video_generation(job_id: str, owner: str) -> None:
    async def stage(status: str, progress: int, eta: int) -> bool:
        doc = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
        if not doc or doc.get("status") == "cancelled":
            return False
        await video_generation_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": status, "progress": progress, "estimated_seconds_remaining": eta, "updated_at": now_iso()}})
        await asyncio.sleep(0.05)
        return True
    if not await stage("preparing", 10, 4) or not await stage("uploading", 25, 3) or not await stage("processing", 55, 2):
        return
    try:
        job_doc = await video_generation_jobs_coll.find_one(
            {"id": job_id, "owner_email": owner}, {"_id": 0}
        )
        if not job_doc:
            return
        job = VideoGenerationJob(**job_doc)
        source_bytes, source_mimes = [], []
        for source_id in job.source_media_ids or ([job.source_media_id] if job.source_media_id else []):
            source = await media_coll.find_one({"id": source_id, "owner_email": owner}, {"_id": 0})
            if not source:
                raise VideoProviderError(job.provider, "Source image is missing", "A source image is no longer available.")
            source_bytes.append(read_bytes(source["filename"], kind="reference"))
            source_mimes.append(source.get("mime_type", "image/png"))
        provider = get_video_provider(job.provider)
        source_urls = []
        image_url_base = os.environ.get("LUMA_IMAGE_URL_BASE", "").strip().rstrip("/")
        if image_url_base:
            source_urls = [f"{image_url_base}/{(await media_coll.find_one({'id': source_id, 'owner_email': owner}, {'filename': 1, '_id': 0}))['filename']}" for source_id in job.source_media_ids]
        spec = VideoGenerationInput(
                mode=job.mode,
                prompt=job.prompt,
                negative_prompt=job.negative_prompt,
                duration_seconds=job.duration_seconds,
                aspect_ratio=job.aspect_ratio,
                resolution=job.resolution, fps=job.fps, quality=job.quality,
                camera_motion=job.camera_motion, style=job.style, seed=job.seed,
                source_images=source_bytes, source_mimes=source_mimes,
                source_urls=source_urls,
            )
        async def video_executor(runtime_job, progress):
            await progress(runtime_job, RuntimeJobStatus.RUNNING, 35, "Video provider execution started")
            if getattr(provider, "supports_async_jobs", False):
                submitted = await provider.submit(spec)
                await video_generation_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "processing", "progress": 35, "estimated_seconds_remaining": None, "metadata.provider_job_id": submitted.id, "metadata.provider_status": submitted.state, "updated_at": now_iso()}})
                poll_interval = max(1, int(os.environ.get("VIDEO_PROVIDER_POLL_INTERVAL_SECONDS", "5")))
                max_wait = max(poll_interval, int(os.environ.get("VIDEO_PROVIDER_MAX_POLL_SECONDS", "600")))
                elapsed = 0
                while elapsed < max_wait:
                    await asyncio.sleep(poll_interval); elapsed += poll_interval
                    current = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
                    if not current or current.get("status") == "cancelled": raise VideoProviderError(job.provider, "Cancelled", "Video generation was cancelled.")
                    remote = await provider.poll(submitted.id)
                    raw_state = remote.state.lower()
                    if raw_state in {"failed", "error"}:
                        raise VideoProviderError(job.provider, "Provider generation failed", "The video provider could not complete this generation.")
                    if raw_state in {"completed", "complete", "succeeded"}:
                        await progress(runtime_job, RuntimeJobStatus.RUNNING, 90, "Downloading video result")
                        return await provider.download(remote)
                    runtime_progress = 60 if raw_state in {"dreaming", "processing", "generating"} else 45
                    await progress(runtime_job, RuntimeJobStatus.WAITING, runtime_progress, f"Provider status: {remote.state}")
                    await video_generation_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "processing", "progress": runtime_progress, "metadata.provider_status": remote.state, "updated_at": now_iso()}})
                raise VideoProviderError(job.provider, "Provider polling timed out", "The video provider took too long. You can retry this job.", retryable=True)
            if not await stage("rendering", 82, 1):
                raise VideoProviderError(job.provider, "Cancelled", "Video generation was cancelled.")
            result_value = await provider.generate(spec)
            await progress(runtime_job, RuntimeJobStatus.RUNNING, 90, "Video provider returned result")
            return result_value

        result, runtime_job = await _runtime_execute(owner, "video", "video", job.provider, {"mode": job.mode, "prompt": job.prompt, "duration_seconds": job.duration_seconds}, video_executor)
        filename, _abs, size = save_bytes(result.data, result.mime_type, kind="generated")
        output = MediaAsset(
            owner_email=owner,
            filename=filename,
            mime_type=result.mime_type,
            kind="generated",
            parent_media_id=job.source_media_id,
            edit_note=f"video-studio:{job.provider}",
            size_bytes=size,
        )
        await media_coll.insert_one(output.model_dump())
        await video_generation_jobs_coll.update_one(
            {"id": job_id, "owner_email": owner},
            {"$set": {
                "status": "completed",
                "progress": 100,
                "estimated_seconds_remaining": 0,
                "output_media_id": output.id,
                "output_mime_type": result.mime_type,
                "preview_kind": result.preview_kind,
                "metadata.provider_output": result.metadata,
                "metadata.output_duration_seconds": result.duration_seconds or job.duration_seconds,
                "metadata.output_resolution": result.resolution or job.resolution,
                "metadata.runtime_job_id": runtime_job.id,
                "updated_at": now_iso(),
            }},
        )
    except Exception as exc:
        logger.exception("Video generation failed: %s", exc)
        await video_generation_jobs_coll.update_one(
            {"id": job_id, "owner_email": owner},
            {"$set": {
                "status": "failed",
                "error": getattr(exc, "safe_message", None) or "Video generation could not be completed.", "progress": 0, "estimated_seconds_remaining": None,
                "updated_at": now_iso(),
            }},
        )


@api.get("/video/providers")
async def list_video_providers(_: str = Depends(require_owner)) -> dict:
    return {"active": os.environ.get("VIDEO_PROVIDER", "mock"), "available": available_video_providers(), "providers": video_provider_catalog()}


@api.post("/video/generate", response_model=VideoGenerationJob)
async def create_video_generation(
    background: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    files: List[UploadFile] = File([]),
    prompt: str = Form(...),
    mode: str = Form("image-to-video"),
    negative_prompt: str = Form(""),
    duration_seconds: int = Form(5),
    aspect_ratio: str = Form("16:9"),
    resolution: str = Form("720p"), fps: int = Form(24), quality: str = Form("standard"),
    camera_motion: str = Form("auto"), style: str = Form("cinematic"), seed: Optional[int] = Form(None),
    source_job_id: Optional[str] = Form(None), priority: int = Form(0),
    provider: Optional[str] = Form(None),
    owner: str = Depends(require_owner),
) -> VideoGenerationJob:
    if mode not in {"text-to-video", "image-to-video", "multi-image", "extend", "variation", "interpolation", "edit"}:
        raise HTTPException(400, "Unsupported video generation mode.")
    if not prompt or not prompt.strip():
        raise HTTPException(400, "Describe the movement or scene you want to create.")
    if duration_seconds not in VIDEO_STUDIO_DURATIONS:
        raise HTTPException(400, "Choose a duration of 3, 5, or 8 seconds.")
    if aspect_ratio not in VIDEO_STUDIO_ASPECT_RATIOS:
        raise HTTPException(400, "Choose either vertical or horizontal format.")
    uploads = ([file] if file else []) + files
    if mode != "text-to-video" and not uploads and not source_job_id:
        raise HTTPException(400, "Upload at least one image for this generation mode.")

    selected_provider = (provider or os.environ.get("VIDEO_PROVIDER") or "mock").strip().lower()
    try:
        get_video_provider(selected_provider)
    except VideoProviderError as exc:
        raise HTTPException(400, exc.safe_message) from exc
    provider_instance = get_video_provider(selected_provider)
    caps = provider_instance.capabilities
    supported_modes = {"text-to-video": caps.text_to_video, "image-to-video": caps.image_to_video, "multi-image": caps.multiple_images, "extend": caps.extension, "variation": caps.variation, "interpolation": caps.interpolation, "edit": caps.editing}
    if not supported_modes.get(mode, False): raise HTTPException(400, "The selected video provider does not support this generation mode.")
    if duration_seconds not in caps.durations or resolution not in caps.resolutions or aspect_ratio not in caps.aspect_ratios: raise HTTPException(400, "The selected provider does not support one or more selected video settings.")
    if len(prompt.strip()) > caps.max_prompt_length: raise HTTPException(400, "The prompt is too long for the selected video provider.")

    source_ids = []
    if len(uploads) > caps.max_image_inputs: raise HTTPException(400, "The selected video provider accepts fewer source images.")
    for upload in uploads[:caps.max_image_inputs]:
        mime = (upload.content_type or "").lower()
        if mime not in ALLOWED_MIMES:
            raise HTTPException(400, "Upload PNG, JPEG, or WebP source images only.")
        source_bytes = await upload.read()
        if not source_bytes or len(source_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Each source image must be between 1 byte and 15 MB.")
        filename, _abs, size = save_bytes(source_bytes, mime, kind="reference")
        source = MediaAsset(owner_email=owner, filename=filename, mime_type=mime, kind="reference", size_bytes=size, edit_note="video-studio-source")
        await media_coll.insert_one(source.model_dump())
        source_ids.append(source.id)
    job = VideoGenerationJob(
        owner_email=owner,
        provider=selected_provider,
        mode=mode, prompt=prompt.strip(), negative_prompt=negative_prompt.strip(),
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution, fps=fps if fps in {12, 24, 30, 60} else 24,
        quality=quality, camera_motion=camera_motion, style=style, seed=seed,
        source_media_id=source_ids[0] if source_ids else None, source_media_ids=source_ids,
        source_job_id=source_job_id, priority=max(-10, min(priority, 10)),
        title=(prompt.strip()[:80] or "Untitled video"),
    )
    await video_generation_jobs_coll.insert_one(job.model_dump())
    background.add_task(_run_video_generation, job.id, owner)
    return job


@api.get("/video/jobs", response_model=List[VideoGenerationJob])
async def list_video_generation_jobs(owner: str = Depends(require_owner), limit: int = 50, search: str = "", status: str = "", folder: str = "", collection: str = "", favorite: Optional[bool] = None, sort: str = "recent") -> List[VideoGenerationJob]:
    safe_limit = max(1, min(limit, 100))
    query: dict = {"owner_email": owner}
    if search.strip(): query["$or"] = [{"title": {"$regex": search.strip(), "$options": "i"}}, {"prompt": {"$regex": search.strip(), "$options": "i"}}]
    if status: query["status"] = status
    if folder: query["folder"] = folder
    if collection: query["collection_ids"] = collection
    if favorite is not None: query["favorite"] = favorite
    sort_field, sort_direction = ("created_at", -1) if sort == "recent" else (("title", 1) if sort == "title" else ("favorite", -1))
    cursor = video_generation_jobs_coll.find(query, {"_id": 0}).sort(sort_field, sort_direction).limit(safe_limit)
    return [VideoGenerationJob(**doc) async for doc in cursor]


@api.get("/video/library/facets")
async def video_library_facets(owner: str = Depends(require_owner)) -> dict:
    docs = [VideoLibraryOrganization(**doc) async for doc in video_library_orgs_coll.find({"owner_email": owner}, {"_id": 0}).sort("name", 1)]
    return {"folders": [doc.model_dump() for doc in docs if doc.kind == "folder"], "collections": [doc.model_dump() for doc in docs if doc.kind == "collection"]}


@api.post("/video/library/organizations", response_model=VideoLibraryOrganization)
async def create_video_organization(body: dict, owner: str = Depends(require_owner)) -> VideoLibraryOrganization:
    kind, name = body.get("kind"), (body.get("name") or "").strip()
    if kind not in {"folder", "collection"} or not name: raise HTTPException(400, "Choose an organization type and name.")
    if await video_library_orgs_coll.find_one({"owner_email": owner, "kind": kind, "name": name}, {"_id": 0}): raise HTTPException(409, "An item with that name already exists.")
    item = VideoLibraryOrganization(owner_email=owner, kind=kind, name=name)
    await video_library_orgs_coll.insert_one(item.model_dump())
    return item


@api.patch("/video/library/organizations/{organization_id}", response_model=VideoLibraryOrganization)
async def rename_video_organization(organization_id: str, body: dict, owner: str = Depends(require_owner)) -> VideoLibraryOrganization:
    doc = await video_library_orgs_coll.find_one({"id": organization_id, "owner_email": owner}, {"_id": 0})
    name = (body.get("name") or "").strip()
    if not doc: raise HTTPException(404, "Organization not found")
    if not name: raise HTTPException(400, "Name is required")
    doc.update({"name": name, "updated_at": now_iso()}); await video_library_orgs_coll.replace_one({"id": organization_id}, doc)
    return VideoLibraryOrganization(**doc)


@api.delete("/video/library/organizations/{organization_id}")
async def delete_video_organization(organization_id: str, owner: str = Depends(require_owner)) -> dict:
    doc = await video_library_orgs_coll.find_one({"id": organization_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Organization not found")
    await video_library_orgs_coll.delete_one({"id": organization_id, "owner_email": owner})
    if doc["kind"] == "folder": await video_generation_jobs_coll.update_many({"owner_email": owner, "folder": organization_id}, {"$set": {"folder": ""}})
    else: await video_generation_jobs_coll.update_many({"owner_email": owner}, {"$pull": {"collection_ids": organization_id}})
    return {"ok": True}


@api.get("/video/jobs/{job_id}", response_model=VideoGenerationJob)
async def get_video_generation_job(job_id: str, owner: str = Depends(require_owner)) -> VideoGenerationJob:
    doc = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Video job not found")
    return VideoGenerationJob(**doc)


@api.patch("/video/jobs/{job_id}", response_model=VideoGenerationJob)
async def update_video_generation_job(job_id: str, body: dict, owner: str = Depends(require_owner)) -> VideoGenerationJob:
    doc = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Video job not found")
    for field in ("title", "folder", "collection_ids", "favorite", "priority"):
        if field in body:
            doc[field] = bool(body[field]) if field == "favorite" else body[field]
    doc["updated_at"] = now_iso()
    await video_generation_jobs_coll.replace_one({"id": job_id, "owner_email": owner}, doc)
    return VideoGenerationJob(**doc)


@api.post("/video/jobs/{job_id}/cancel", response_model=VideoGenerationJob)
async def cancel_video_generation_job(job_id: str, owner: str = Depends(require_owner)) -> VideoGenerationJob:
    doc = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Video job not found")
    if doc.get("status") in {"completed", "failed", "cancelled"}: raise HTTPException(400, "This video job can no longer be cancelled.")
    provider_job_id = (doc.get("metadata") or {}).get("provider_job_id")
    if provider_job_id:
        try:
            provider = get_video_provider(doc.get("provider"))
            if provider.capabilities.cancellation: await provider.cancel(provider_job_id)
        except VideoProviderError as exc:
            logger.warning("Video provider cancellation failed for job %s: %s", job_id, exc.safe_message)
    doc.update({"status": "cancelled", "cancelled_at": now_iso(), "estimated_seconds_remaining": None, "updated_at": now_iso()})
    await video_generation_jobs_coll.replace_one({"id": job_id, "owner_email": owner}, doc)
    return VideoGenerationJob(**doc)


@api.post("/video/jobs/{job_id}/retry", response_model=VideoGenerationJob)
async def retry_video_generation_job(job_id: str, background: BackgroundTasks, owner: str = Depends(require_owner)) -> VideoGenerationJob:
    doc = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Video job not found")
    if doc.get("status") not in {"failed", "cancelled"}: raise HTTPException(400, "Only failed or cancelled video jobs can be retried.")
    payload = {k: v for k, v in doc.items() if k not in {"id", "_id", "owner_email", "output_media_id", "output_mime_type", "preview_kind", "error", "created_at", "updated_at", "cancelled_at", "progress", "estimated_seconds_remaining"}}
    retry = VideoGenerationJob(**payload, owner_email=owner, retry_of=job_id, status="queued", progress=0)
    await video_generation_jobs_coll.insert_one(retry.model_dump())
    background.add_task(_run_video_generation, retry.id, owner)
    return retry


@api.post("/video/jobs/{job_id}/duplicate", response_model=VideoGenerationJob)
async def duplicate_video_generation_job(job_id: str, owner: str = Depends(require_owner)) -> VideoGenerationJob:
    doc = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Video job not found")
    payload = {k: v for k, v in doc.items() if k not in {"id", "_id", "owner_email", "output_media_id", "output_mime_type", "preview_kind", "error", "created_at", "updated_at", "cancelled_at", "progress", "estimated_seconds_remaining", "status"}}
    duplicate = VideoGenerationJob(**payload, owner_email=owner, status="queued", title=f"{doc.get('title', 'Video')} copy")
    await video_generation_jobs_coll.insert_one(duplicate.model_dump())
    return duplicate


@api.get("/video/results/{job_id}")
async def get_video_generation_result(job_id: str, owner: str = Depends(require_owner)) -> Response:
    job = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not job or not job.get("output_media_id"):
        raise HTTPException(404, "Video result is not ready yet")
    media = await media_coll.find_one({"id": job["output_media_id"], "owner_email": owner}, {"_id": 0})
    if not media:
        raise HTTPException(404, "Video result is missing")
    try:
        return Response(content=read_bytes(media["filename"], kind="generated"), media_type=media["mime_type"])
    except FileNotFoundError as exc:
        raise HTTPException(404, "Video result file is missing") from exc


@api.delete("/video/jobs/{job_id}")
async def delete_video_generation_job(job_id: str, owner: str = Depends(require_owner)) -> dict:
    job = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Video job not found")
    for media_id in (job.get("source_media_id"), job.get("output_media_id")):
        if not media_id:
            continue
        media = await media_coll.find_one({"id": media_id, "owner_email": owner}, {"_id": 0})
        if media:
            try:
                delete_file(media["filename"], kind="reference" if media["kind"] == "reference" else "generated")
            except Exception:
                logger.warning("Unable to remove Video Studio media %s", media_id)
            await media_coll.delete_one({"id": media_id, "owner_email": owner})
    await video_generation_jobs_coll.delete_one({"id": job_id, "owner_email": owner})
    return {"ok": True}


@api.get("/video/projects", response_model=List[VideoProject])
async def list_video_projects(owner: str = Depends(require_owner)) -> List[VideoProject]:
    cursor = video_projects_coll.find({"owner_email": owner}, {"_id": 0}).sort("updated_at", -1)
    return [VideoProject(**d) async for d in cursor]


@api.post("/video/projects", response_model=VideoProject)
async def create_video_project(body: dict, owner: str = Depends(require_owner)) -> VideoProject:
    proj = VideoProject(
        owner_email=owner,
        name=(body.get("name") or "Untitled Video").strip() or "Untitled Video",
        aspect_ratio=body.get("aspect_ratio") or "16:9",
        fps=int(body.get("fps") or 30),
        resolution=body.get("resolution") or "1080p",
        state=_normalize_video_project_state(body.get("state") or {}),
        tags=body.get("tags") or [],
        collection_ids=body.get("collection_ids") or [],
    )
    await video_projects_coll.insert_one(proj.model_dump())
    return proj


@api.get("/video/projects/{project_id}", response_model=VideoProject)
async def get_video_project(project_id: str, owner: str = Depends(require_owner)) -> VideoProject:
    doc = await video_projects_coll.find_one({"id": project_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Video project not found")
    return VideoProject(**doc)


@api.put("/video/projects/{project_id}", response_model=VideoProject)
async def update_video_project(project_id: str, body: dict, owner: str = Depends(require_owner)) -> VideoProject:
    doc = await video_projects_coll.find_one({"id": project_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Video project not found")
    for field in ("name", "aspect_ratio", "fps", "resolution", "state", "exported_media_id", "tags", "favorite", "collection_ids", "ai_generation_history", "template_ids"):
        if field in body:
            doc[field] = _normalize_video_project_state(body[field]) if field == "state" else body[field]
    doc["version"] = int(doc.get("version") or 1) + 1
    doc.setdefault("history", []).append({"version": doc["version"], "at": now_iso(), "note": body.get("note") or "Project saved"})
    doc["history"] = doc["history"][-100:]
    doc["updated_at"] = now_iso()
    await video_projects_coll.replace_one({"id": project_id}, doc)
    return VideoProject(**doc)


def _normalize_video_project_state(state: dict) -> dict:
    if not isinstance(state, dict):
        return {}
    normalized = dict(state)
    normalized.setdefault("tracks", [
        {"id": "video-1", "type": "video", "name": "Video 1", "locked": False, "muted": False, "visible": True},
        {"id": "overlay-1", "type": "overlay", "name": "Overlays", "locked": False, "muted": False, "visible": True},
        {"id": "audio-1", "type": "audio", "name": "Music", "locked": False, "muted": False, "visible": True},
        {"id": "voice-1", "type": "audio", "name": "Voice Over", "locked": False, "muted": False, "visible": True},
    ])
    normalized.setdefault("clips", [])
    normalized.setdefault("textOverlays", [])
    normalized.setdefault("subtitles", [])
    normalized.setdefault("templates", [])
    normalized.setdefault("promptHistory", [])
    normalized.setdefault("reusablePrompts", [])
    normalized.setdefault("aiGenerationHistory", [])
    normalized.setdefault("branding", {"logos": [], "colors": ["#D4AF37", "#0B0B0F"], "fonts": ["Inter", "Playfair Display"], "animations": ["fade", "slide-up"]})
    normalized.setdefault("export", {"format": "mp4", "resolution": "1080p", "fps": 30, "codec": "h264", "bitrate": 12000, "quality": "high"})
    return normalized


def _generate_video_template_from_brief(brief: str, brand: dict | None = None) -> dict:
    text = (brief or "").lower()
    luxury = any(token in text for token in ["luxury", "hotel", "premium", "resort", "villa"])
    energetic = any(token in text for token in ["tiktok", "reel", "launch", "sport", "sale"])
    palette = ["#0B0B0F", "#D4AF37", "#F8F2DF"] if luxury else (["#111827", "#F97316", "#22D3EE"] if energetic else (brand or {}).get("colors", ["#D4AF37", "#0B0B0F"]))
    return {
        "brief": brief,
        "intro": {"duration": 2.5 if luxury else 1.5, "typography": "elegant serif reveal" if luxury else "bold kinetic title"},
        "colorPalette": palette,
        "animations": ["slow fade", "parallax gold lines", "cinematic dissolve"] if luxury else ["snap zoom", "kinetic text", "beat cuts"],
        "cameraMotions": ["dolly-in", "orbit", "crane"] if luxury else ["push-in", "whip-pan", "handheld"],
        "musicStyle": "cinematic lounge, warm piano, soft strings" if luxury else "modern upbeat electronic with clear beat markers",
        "sceneTiming": [2.5, 3.5, 3, 2] if luxury else [1, 1.2, 1.5, 1],
        "outro": {"duration": 2, "callToAction": "Book now" if luxury else "Learn more"},
        "workflow": ["apply-branding", "generate-storyboard", "assemble-scenes", "add-typography", "color-grade", "duck-voiceover", "export-social-pack"],
    }


@api.get("/video/templates", response_model=List[VideoTemplate])
async def list_video_templates(owner: str = Depends(require_owner), scope: str = "") -> List[VideoTemplate]:
    query = {"owner_email": owner}
    if scope:
        query["scope"] = scope
    cursor = video_templates_coll.find(query, {"_id": 0}).sort("updated_at", -1).limit(100)
    return [VideoTemplate(**doc) async for doc in cursor]


@api.post("/video/templates/ai", response_model=VideoTemplate)
async def create_ai_video_template(body: dict, owner: str = Depends(require_owner)) -> VideoTemplate:
    brief = (body.get("brief") or body.get("prompt") or "").strip()
    if not brief:
        raise HTTPException(400, "Template brief is required")
    brand = body.get("brand") or {}
    generated = _generate_video_template_from_brief(brief, brand)
    template = VideoTemplate(
        owner_email=owner,
        name=(body.get("name") or generated.get("name") or f"AI Template · {brief[:40]}").strip()[:120],
        scope=body.get("scope") or "ai-generated",
        brief=brief,
        template=generated,
        tags=body.get("tags") or ["ai-generated"],
    )
    await video_templates_coll.insert_one(template.model_dump())
    return template


@api.patch("/video/templates/{template_id}", response_model=VideoTemplate)
async def update_video_template(template_id: str, body: dict, owner: str = Depends(require_owner)) -> VideoTemplate:
    doc = await video_templates_coll.find_one({"id": template_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Video template not found")
    for field in ("name", "scope", "favorite", "template", "tags", "preference_score"):
        if field in body:
            doc[field] = body[field]
    doc["updated_at"] = now_iso()
    await video_templates_coll.replace_one({"id": template_id, "owner_email": owner}, doc)
    return VideoTemplate(**doc)


@api.get("/video/brand-kits", response_model=List[VideoBrandKit])
async def list_video_brand_kits(owner: str = Depends(require_owner)) -> List[VideoBrandKit]:
    cursor = video_brand_kits_coll.find({"owner_email": owner}, {"_id": 0}).sort("updated_at", -1).limit(50)
    return [VideoBrandKit(**doc) async for doc in cursor]


@api.post("/video/brand-kits", response_model=VideoBrandKit)
async def save_video_brand_kit(body: dict, owner: str = Depends(require_owner)) -> VideoBrandKit:
    kit = VideoBrandKit(owner_email=owner, **{k: v for k, v in body.items() if k in {"name", "logos", "colors", "fonts", "intro_media_id", "outro_media_id", "watermark_media_id", "animations"}})
    await video_brand_kits_coll.insert_one(kit.model_dump())
    return kit


@api.delete("/video/projects/{project_id}")
async def delete_video_project(project_id: str, owner: str = Depends(require_owner)) -> dict:
    r = await video_projects_coll.delete_one({"id": project_id, "owner_email": owner})
    if r.deleted_count == 0:
        raise HTTPException(404, "Video project not found")
    return {"ok": True}


@api.post("/video/assets")
async def upload_video_asset(
    file: UploadFile = File(...),
    owner: str = Depends(require_owner),
) -> dict:
    """Upload a video / image / audio asset for the video editor.

    Returns a MediaAsset row; the frontend uses `/api/media/{id}` to stream it back.
    """
    mime = (file.content_type or "").lower()
    allowed = ALLOWED_MIMES | ALLOWED_VIDEO_MIMES | ALLOWED_AUDIO_MIMES
    if mime not in allowed:
        raise HTTPException(400, f"Unsupported file type: {mime}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > MAX_VIDEO_ASSET_BYTES:
        raise HTTPException(400, f"File exceeds {MAX_VIDEO_ASSET_BYTES // (1024*1024)} MB")

    kind = "reference" if mime in ALLOWED_MIMES else "generated"
    filename, _abs, size = save_bytes(data, mime, kind=kind)
    asset = MediaAsset(
        owner_email=owner,
        filename=filename,
        mime_type=mime,
        kind=kind,
        size_bytes=size,
        edit_note="video-asset",
    )
    await media_coll.insert_one(asset.model_dump())
    return {
        "id": asset.id,
        "mime_type": mime,
        "size_bytes": size,
        "kind": kind,
        "original_name": file.filename or "asset",
    }


@api.post("/video/projects/{project_id}/export")
async def save_video_export(
    project_id: str,
    file: UploadFile = File(...),
    owner: str = Depends(require_owner),
) -> dict:
    """Store the exported MP4 for a project (rendered client-side via FFmpeg.wasm).

    The frontend renders the final video with FFmpeg.wasm and POSTs the resulting
    MP4 here; we persist as a MediaAsset(kind='generated') and attach it to the
    project. Also creates a Gallery entry.
    """
    doc = await video_projects_coll.find_one({"id": project_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Video project not found")
    mime = (file.content_type or "video/mp4").lower()
    if not mime.startswith("video/"):
        raise HTTPException(400, "Only video/* mime types accepted for export")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty export")
    if len(data) > MAX_VIDEO_ASSET_BYTES:
        raise HTTPException(400, "Export exceeds max size")

    filename, _abs, size = save_bytes(data, mime, kind="generated")
    media = MediaAsset(
        owner_email=owner, filename=filename, mime_type=mime,
        kind="edited", size_bytes=size, edit_note=f"video-export:{project_id}",
    )
    await media_coll.insert_one(media.model_dump())

    doc["exported_media_id"] = media.id
    doc["updated_at"] = now_iso()
    await video_projects_coll.replace_one({"id": project_id}, doc)

    gallery = GalleryItem(
        owner_email=owner,
        media_id=media.id,
        prompt=doc.get("name") or "Video export",
        aspect_ratio=doc.get("aspect_ratio") or "16:9",
        provider="video-editor",
    )
    await gallery_coll.insert_one(gallery.model_dump())
    return {"media_id": media.id, "project_id": project_id}


# ---------- Voice Studio ----------
VOICE_MODES = {"text-to-speech", "speech-to-text", "speech-to-speech", "live-voice-conversion", "voice-style-transfer", "voice-clone", "enhance", "noise-reduction", "echo-removal", "click-removal", "pop-removal", "breath-control", "de-esser", "normalize", "compressor", "equalizer", "limiter", "reverb", "delay", "stereo-enhancement", "loudness-correction", "singing-conversion", "vocal-isolation", "instrumental-separation", "stem-separation", "pitch-detection", "pitch-correction", "timing-correction", "harmony-generation", "vocal-layering", "backing-vocals", "podcast-mastering", "silence-detection", "automatic-cleanup", "intro", "outro", "chapters", "cut", "trim", "split", "merge", "fade-in", "fade-out", "silence-removal", "volume", "convert", "batch"}
VOICE_STYLES = {"cinematic", "documentary", "podcast", "audiobook", "radio", "commercial", "calm", "emotional", "corporate", "energetic", "motivational", "luxury"}
VOICE_EXPORT_FORMATS = {"wav", "mp3", "flac", "aac"}
VOICE_PRO_PRESETS = [
    VoicePreset(id="podcast", name="Podcast", category="spoken", description="Dialogue cleanup, warm compression and -16 LUFS mastering.", chain=["noise-removal", "de-esser", "compressor", "equalizer", "limiter", "loudness-correction"], settings={"presence": 58, "warmth": 64, "breath_control": 38}, export={"format": "mp3", "sample_rate": 48000, "bitrate": "192k", "loudness_lufs": -16}),
    VoicePreset(id="youtube", name="YouTube", category="spoken", description="Clear creator narration with energetic transient control.", chain=["noise-removal", "compressor", "equalizer", "stereo-enhancement", "limiter"], settings={"energy": 70, "clarity": 76}, export={"format": "aac", "sample_rate": 48000, "bitrate": "256k", "loudness_lufs": -14}),
    VoicePreset(id="documentary", name="Documentary", category="narration", description="Cinematic narration tone preserving the user's identity.", chain=["voice-style-transfer", "equalizer", "reverb", "limiter"], settings={"gravity": 72, "room": 18}, export={"format": "wav", "sample_rate": 48000, "bit_depth": 24, "loudness_lufs": -18}),
    VoicePreset(id="audiobook", name="Audiobook", category="narration", description="Long-form narration mastering with consistent pacing.", chain=["breath-control", "de-esser", "normalize", "compressor"], settings={"pacing": "steady", "fatigue_reduction": True}, export={"format": "flac", "sample_rate": 44100, "bit_depth": 24, "loudness_lufs": -18}),
    VoicePreset(id="radio", name="Radio", category="broadcast", description="Broadcast-ready voice with dense compression.", chain=["compressor", "equalizer", "limiter", "loudness-correction"], settings={"density": 82, "air": 40}, export={"format": "wav", "sample_rate": 48000, "bit_depth": 24, "loudness_lufs": -16}),
    VoicePreset(id="commercial", name="Commercial", category="advertising", description="Bright, confident commercial voice processing.", chain=["voice-style-transfer", "compressor", "equalizer", "limiter"], settings={"confidence": 80, "brightness": 68}, export={"format": "mp3", "sample_rate": 48000, "bitrate": "320k", "loudness_lufs": -14}),
    VoicePreset(id="corporate", name="Corporate", category="business", description="Polished professional speech for presentations and training.", chain=["noise-removal", "normalize", "de-esser", "compressor"], settings={"authority": 66, "calm": 54}, export={"format": "mp3", "sample_rate": 48000, "bitrate": "192k", "loudness_lufs": -16}),
    VoicePreset(id="cinematic", name="Cinematic", category="film", description="Trailer-style depth, air and controlled ambience.", chain=["voice-style-transfer", "equalizer", "reverb", "delay", "limiter"], settings={"depth": 84, "ambience": 28}, export={"format": "wav", "sample_rate": 48000, "bit_depth": 24, "loudness_lufs": -20}),
    VoicePreset(id="motivation", name="Motivation", category="spoken", description="Energetic inspirational delivery with tight loudness.", chain=["compressor", "equalizer", "stereo-enhancement", "limiter"], settings={"energy": 86, "impact": 78}, export={"format": "aac", "sample_rate": 48000, "bitrate": "256k", "loudness_lufs": -14}),
    VoicePreset(id="luxury", name="Luxury", category="brand", description="Smooth premium voice tone with subtle room polish.", chain=["de-esser", "equalizer", "reverb", "limiter"], settings={"silk": 80, "space": 20}, export={"format": "flac", "sample_rate": 48000, "bit_depth": 24, "loudness_lufs": -18}),
]

def _default_personal_voice_model(owner: str) -> PersonalVoiceModel:
    return PersonalVoiceModel(owner_email=owner, profile={"voice_identity": {"identity_lock": True, "timbre_preservation": 96, "default_voice": "personal-user"}, "speaking_profile": {"pace": "natural", "tone": "warm", "articulation": "clear"}, "singing_profile": {"supported": True, "vibrato_preservation": True, "emotion_preservation": True}, "emotion_profiles": [{"name": "calm", "intensity": 45}, {"name": "emotional", "intensity": 62}, {"name": "energetic", "intensity": 70}], "vocal_range": {"spoken_low_hz": 90, "spoken_high_hz": 280, "singing_low_note": "A2", "singing_high_note": "E5"}, "accent_profile": {"primary": "personal", "strength": "preserve"}, "pronunciation_profile": {"custom_dictionary": [], "phoneme_lock": True}, "breathing_profile": {"natural_breaths": True, "breath_reduction": 35}, "quality_score": 82})

async def _get_or_create_personal_voice_model(owner: str) -> PersonalVoiceModel:
    doc = await voice_personal_models_coll.find_one({"owner_email": owner, "status": "active"}, {"_id": 0})
    if doc: return PersonalVoiceModel(**doc)
    model = _default_personal_voice_model(owner)
    await voice_personal_models_coll.insert_one(model.model_dump())
    return model

def _audio_capability_matrix() -> dict:
    return {"recording": ["microphone-selection", "input-level-monitoring", "waveform", "timer", "pause", "resume", "retake", "history", "monitoring", "quality-presets"], "speech": sorted([m for m in VOICE_MODES if "speech" in m or "voice" in m]), "enhancement": ["noise-removal", "echo-removal", "click-removal", "pop-removal", "breath-control", "de-esser", "normalize", "compressor", "equalizer", "limiter", "reverb", "delay", "stereo-enhancement", "loudness-correction"], "singing": ["singing-conversion", "vocal-isolation", "instrumental-separation", "stem-separation", "pitch-detection", "pitch-correction", "timing-correction", "harmony-generation", "vocal-layering", "backing-vocals", "vibrato-preservation", "emotion-preservation"], "podcast": ["intro", "outro", "chapters", "silence-detection", "automatic-cleanup", "podcast-mastering"], "editor": ["cut", "trim", "split", "merge", "fade-in", "fade-out", "timeline", "undo", "redo", "non-destructive-editing"], "library": ["projects", "versions", "favorites", "tags", "search", "presets", "voice-models", "recordings", "songs"], "video_integration": ["replace-narration", "replace-voice", "lip-sync-preparation", "voice-export", "audio-import"], "exports": sorted(VOICE_EXPORT_FORMATS)}

async def _run_voice_job(job_id: str, owner: str) -> None:
    try:
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "preparing", "progress": 15, "updated_at": now_iso()}})
        await asyncio.sleep(.03)
        doc = await voice_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
        if not doc or doc.get("status") == "cancelled": return
        job = VoiceJob(**doc)
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "processing", "progress": 55, "updated_at": now_iso()}})
        provider = get_voice_provider(job.provider)
        async def voice_executor(runtime_job, progress):
            await progress(runtime_job, RuntimeJobStatus.RUNNING, 50, "Voice provider execution started")
            generated = await provider.generate(job.text or job.title, job.voice, job.output_format, style=job.style, mode=job.mode, preset_id=job.preset_id, sample_rate=job.sample_rate, bit_depth=job.bit_depth, bitrate=job.bitrate, loudness_lufs=job.loudness_lufs)
            await progress(runtime_job, RuntimeJobStatus.RUNNING, 90, "Voice provider returned audio")
            return generated
        (data, mime, metadata), runtime_job = await _runtime_execute(owner, "voice", "speech", job.provider, {"mode": job.mode, "title": job.title, "format": job.output_format}, voice_executor)
        filename, _, size = save_bytes(data, mime, kind="generated")
        media = MediaAsset(owner_email=owner, filename=filename, mime_type=mime, kind="generated", size_bytes=size, edit_note=f"voice-studio:{job.provider}")
        await media_coll.insert_one(media.model_dump())
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "completed", "progress": 100, "output_media_id": media.id, "metadata": {**metadata, "runtime_job_id": runtime_job.id}, "updated_at": now_iso()}})
    except Exception as exc:
        logger.exception("Voice job failed: %s", exc)
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "failed", "error": "Audio processing could not be completed.", "updated_at": now_iso()}})

@api.get("/voice/providers")
async def list_voice_providers(_: str = Depends(require_owner)) -> dict:
    return {"active": os.environ.get("VOICE_PROVIDER", "mock"), "providers": voice_provider_catalog(), "styles": sorted(VOICE_STYLES), "capabilities": _audio_capability_matrix()}

@api.get("/voice/studio")
async def voice_studio_bootstrap(owner: str = Depends(require_owner)) -> dict:
    model = await _get_or_create_personal_voice_model(owner)
    projects = [VoiceProject(**doc).model_dump() async for doc in voice_projects_coll.find({"owner_email": owner}, {"_id": 0}).sort("updated_at", -1).limit(50)]
    recordings = [VoiceRecordingSession(**doc).model_dump() async for doc in voice_recordings_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(50)]
    return {"personal_model": model.model_dump(), "presets": [p.model_dump() for p in VOICE_PRO_PRESETS], "capabilities": _audio_capability_matrix(), "projects": projects, "recordings": recordings, "styles": sorted(VOICE_STYLES)}

@api.get("/voice/personal-model", response_model=PersonalVoiceModel)
async def get_personal_voice_model(owner: str = Depends(require_owner)) -> PersonalVoiceModel:
    return await _get_or_create_personal_voice_model(owner)

@api.post("/voice/personal-model/improve", response_model=PersonalVoiceModel)
async def improve_personal_voice_model(body: dict, owner: str = Depends(require_owner)) -> PersonalVoiceModel:
    model = await _get_or_create_personal_voice_model(owner)
    doc = model.model_dump(); approved = [str(x) for x in body.get("recording_ids", []) if str(x)]
    if not approved: raise HTTPException(400, "Select at least one approved recording.")
    existing = set(doc.get("approved_recording_ids", [])); existing.update(approved)
    doc["approved_recording_ids"] = sorted(existing); doc["version"] = int(doc.get("version", 1)) + 1
    profile = doc.get("profile", {}); profile["quality_score"] = min(99, int(profile.get("quality_score", 82)) + max(1, len(approved)))
    doc["profile"] = profile; doc["improvement_events"].append({"recording_ids": approved, "created_at": now_iso(), "notes": str(body.get("notes") or "Approved model improvement")}); doc["updated_at"] = now_iso()
    await voice_personal_models_coll.replace_one({"id": doc["id"], "owner_email": owner}, doc)
    return PersonalVoiceModel(**doc)

@api.get("/voice/presets", response_model=List[VoicePreset])
async def list_voice_presets(_: str = Depends(require_owner)) -> List[VoicePreset]:
    return VOICE_PRO_PRESETS

@api.post("/voice/recordings", response_model=VoiceRecordingSession)
async def create_voice_recording(body: dict, owner: str = Depends(require_owner)) -> VoiceRecordingSession:
    item = VoiceRecordingSession(owner_email=owner, title=str(body.get("title") or "Studio recording"), microphone_label=str(body.get("microphone_label") or "Default microphone"), quality_preset=str(body.get("quality_preset") or "studio"), duration_seconds=float(body.get("duration_seconds") or 0), sample_rate=int(body.get("sample_rate") or 48000), bit_depth=int(body.get("bit_depth") or 24), monitoring_enabled=bool(body.get("monitoring_enabled", True)), waveform=[float(x) for x in body.get("waveform", [])][:512], media_id=body.get("media_id"), take_history=body.get("take_history", []), approved_for_model=bool(body.get("approved_for_model", False)))
    await voice_recordings_coll.insert_one(item.model_dump())
    return item

@api.get("/voice/recordings", response_model=List[VoiceRecordingSession])
async def list_voice_recordings(owner: str = Depends(require_owner)) -> List[VoiceRecordingSession]:
    return [VoiceRecordingSession(**doc) async for doc in voice_recordings_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(100)]

@api.post("/voice/projects", response_model=VoiceProject)
async def create_voice_project(body: dict, owner: str = Depends(require_owner)) -> VoiceProject:
    title = str(body.get("title") or "Untitled voice project").strip() or "Untitled voice project"
    state = body.get("state") if isinstance(body.get("state"), dict) else {"tracks": [], "timeline": [], "edits": [], "mix": {}, "non_destructive": True}
    project = VoiceProject(owner_email=owner, title=title, project_type=str(body.get("project_type") or "production"), state=state, tags=[str(x).strip() for x in body.get("tags", []) if str(x).strip()][:12], versions=[VoiceProjectVersion(label="Initial version", state=state)])
    await voice_projects_coll.insert_one(project.model_dump())
    return project

@api.get("/voice/projects", response_model=List[VoiceProject])
async def list_voice_projects(owner: str = Depends(require_owner), search: str = "", favorite: Optional[bool] = None) -> List[VoiceProject]:
    query = {"owner_email": owner}
    if search: query["$or"] = [{"title": {"$regex": search, "$options": "i"}}, {"tags": search}]
    if favorite is not None: query["favorite"] = favorite
    return [VoiceProject(**doc) async for doc in voice_projects_coll.find(query, {"_id": 0}).sort("updated_at", -1).limit(100)]

@api.post("/voice/generate", response_model=VoiceJob)
async def create_voice_job(background: BackgroundTasks, text: str = Form(""), mode: str = Form("text-to-speech"), voice: str = Form("personal-user"), style: str = Form("podcast"), preset_id: Optional[str] = Form(None), output_format: str = Form("wav"), sample_rate: int = Form(48000), bit_depth: int = Form(24), bitrate: str = Form("192k"), loudness_lufs: float = Form(-16), title: str = Form(""), tags: str = Form(""), provider: Optional[str] = Form(None), owner: str = Depends(require_owner)) -> VoiceJob:
    if mode not in VOICE_MODES: raise HTTPException(400, "Unsupported voice operation.")
    if style not in VOICE_STYLES: raise HTTPException(400, "Unsupported voice style.")
    selected = (provider or os.environ.get("VOICE_PROVIDER", "mock")).lower()
    try: engine = get_voice_provider(selected)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    if mode not in engine.capabilities["modes"]: raise HTTPException(400, "The selected voice provider does not support this operation.")
    if output_format not in engine.capabilities["formats"]: raise HTTPException(400, "The selected voice provider does not support this output format.")
    if mode == "text-to-speech" and not text.strip(): raise HTTPException(400, "Enter text to generate speech.")
    personal_model = await _get_or_create_personal_voice_model(owner)
    job = VoiceJob(owner_email=owner, provider=selected, mode=mode, text=text.strip(), voice=voice, style=style, preset_id=preset_id, personal_model_id=personal_model.id, output_format=output_format, sample_rate=sample_rate, bit_depth=bit_depth, bitrate=bitrate, loudness_lufs=loudness_lufs, title=(title.strip() or text.strip()[:80] or f"{style.title()} voice production"), tags=[tag.strip() for tag in tags.split(",") if tag.strip()][:12], metadata={"identity_preservation": True, "personal_model_version": personal_model.version})
    await voice_jobs_coll.insert_one(job.model_dump()); background.add_task(_run_voice_job, job.id, owner)
    return job

@api.post("/voice/export")
async def export_voice_audio(body: VoiceExportRequest, owner: str = Depends(require_owner)) -> dict:
    if body.format not in VOICE_EXPORT_FORMATS: raise HTTPException(400, "Unsupported export format.")
    if body.job_id:
        job = await voice_jobs_coll.find_one({"id": body.job_id, "owner_email": owner}, {"_id": 0})
        if not job: raise HTTPException(404, "Voice job not found")
    if body.project_id and not await voice_projects_coll.find_one({"id": body.project_id, "owner_email": owner}, {"_id": 0}): raise HTTPException(404, "Voice project not found")
    return {"ok": True, "format": body.format, "sample_rate": body.sample_rate, "bit_depth": body.bit_depth, "bitrate": body.bitrate, "loudness_lufs": body.loudness_lufs, "metadata": body.metadata, "status": "export-prepared"}

@api.post("/voice/video-integration")
async def prepare_voice_video_integration(body: VideoVoiceIntegrationRequest, owner: str = Depends(require_owner)) -> dict:
    if body.action not in {"replace-narration", "replace-voice", "lip-sync-preparation", "voice-export", "audio-import"}: raise HTTPException(400, "Unsupported Video Studio voice action.")
    if body.video_project_id and not await video_generation_jobs_coll.find_one({"id": body.video_project_id, "owner_email": owner}, {"_id": 0}):
        await video_generation_jobs_coll.find_one({"id": body.video_project_id, "owner_email": owner}, {"_id": 0})
    if body.audio_media_id and not await media_coll.find_one({"id": body.audio_media_id, "owner_email": owner}, {"_id": 0}): raise HTTPException(404, "Audio media not found")
    return {"ok": True, "action": body.action, "lip_sync_preparation": body.lip_sync_preparation, "handoff": {"audio_media_id": body.audio_media_id, "video_project_id": body.video_project_id, "sync_markers": [0.0], "metadata": body.metadata}}

@api.get("/voice/jobs", response_model=List[VoiceJob])
async def list_voice_jobs(owner: str = Depends(require_owner), search: str = "", status: str = "", folder: str = "", collection: str = "", favorite: Optional[bool] = None) -> List[VoiceJob]:
    query: dict = {"owner_email": owner}
    if search: query["$or"] = [{"title": {"$regex": search, "$options": "i"}}, {"text": {"$regex": search, "$options": "i"}}, {"tags": {"$regex": search, "$options": "i"}}]
    if status: query["status"] = status
    if folder: query["folder"] = folder
    if collection: query["collection_ids"] = collection
    if favorite is not None: query["favorite"] = favorite
    return [VoiceJob(**doc) async for doc in voice_jobs_coll.find(query, {"_id": 0}).sort("created_at", -1).limit(100)]

@api.patch("/voice/jobs/{job_id}", response_model=VoiceJob)
async def update_voice_job(job_id: str, body: dict, owner: str = Depends(require_owner)) -> VoiceJob:
    doc = await voice_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Voice job not found")
    for field in ("title", "tags", "folder", "collection_ids", "favorite"):
        if field in body: doc[field] = bool(body[field]) if field == "favorite" else body[field]
    doc["updated_at"] = now_iso(); await voice_jobs_coll.replace_one({"id": job_id, "owner_email": owner}, doc); return VoiceJob(**doc)

@api.post("/voice/jobs/{job_id}/cancel", response_model=VoiceJob)
async def cancel_voice_job(job_id: str, owner: str = Depends(require_owner)) -> VoiceJob:
    doc = await voice_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Voice job not found")
    if doc["status"] in {"completed", "failed", "cancelled"}: raise HTTPException(400, "This voice job can no longer be cancelled.")
    doc.update({"status": "cancelled", "updated_at": now_iso()}); await voice_jobs_coll.replace_one({"id": job_id, "owner_email": owner}, doc); return VoiceJob(**doc)

@api.delete("/voice/jobs/{job_id}")
async def delete_voice_job(job_id: str, owner: str = Depends(require_owner)) -> dict:
    doc = await voice_jobs_coll.find_one_and_delete({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Voice job not found")
    return {"ok": True}

@api.get("/voice/results/{job_id}")
async def voice_result(job_id: str, owner: str = Depends(require_owner)) -> Response:
    job = await voice_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not job or not job.get("output_media_id"): raise HTTPException(404, "Audio result is not ready yet")
    media = await media_coll.find_one({"id": job["output_media_id"], "owner_email": owner}, {"_id": 0})
    if not media: raise HTTPException(404, "Audio file is unavailable")
    return Response(read_bytes(media["filename"], kind="generated"), media_type=media["mime_type"])

@api.get("/voice/library/facets")
async def voice_facets(owner: str = Depends(require_owner)) -> dict:
    items = [VoiceLibraryOrganization(**doc) async for doc in voice_library_orgs_coll.find({"owner_email": owner}, {"_id": 0})]
    return {"folders": [x.model_dump() for x in items if x.kind == "folder"], "collections": [x.model_dump() for x in items if x.kind == "collection"]}

@api.post("/voice/library/organizations", response_model=VoiceLibraryOrganization)
async def create_voice_org(body: dict, owner: str = Depends(require_owner)) -> VoiceLibraryOrganization:
    kind, name = body.get("kind"), str(body.get("name") or "").strip()
    if kind not in {"folder", "collection"} or not name: raise HTTPException(400, "Choose an organization type and name.")
    item = VoiceLibraryOrganization(owner_email=owner, kind=kind, name=name); await voice_library_orgs_coll.insert_one(item.model_dump()); return item

# ---------- Central platform: projects, unified work, search and settings ----------
@api.get("/projects", response_model=List[Project])
async def list_projects(include_archived: bool = False, owner: str = Depends(require_owner)) -> List[Project]:
    query = {"owner_email": owner}
    if not include_archived:
        query["status"] = {"$ne": "archived"}
    return [Project(**doc) async for doc in projects_coll.find(query, {"_id": 0}).sort("updated_at", -1).limit(100)]


@api.post("/projects", response_model=Project)
async def create_project(body: ProjectCreate, owner: str = Depends(require_owner)) -> Project:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "A project name is required.")
    project = Project(owner_email=owner, name=name, description=body.description.strip(), activity=[{"at": now_iso(), "type": "created", "message": "Project created"}])
    await projects_coll.insert_one(project.model_dump())
    return project


@api.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, body: dict, owner: str = Depends(require_owner)) -> Project:
    doc = await projects_coll.find_one({"id": project_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Project not found.")
    for field in ("name", "description", "media_ids", "job_ids", "identity_pack_ids", "notes", "status", "tags", "cover_media_id", "export_media_ids"):
        if field in body:
            doc[field] = body[field]
    doc["name"] = str(doc.get("name", "")).strip()
    if not doc["name"]:
        raise HTTPException(400, "A project name is required.")
    if doc.get("status") not in {"active", "paused", "completed", "archived"}:
        raise HTTPException(400, "Invalid project status.")
    doc["tags"] = [str(tag).strip() for tag in doc.get("tags", []) if str(tag).strip()][:20]
    doc["archived_at"] = now_iso() if doc.get("status") == "archived" else None
    doc.setdefault("activity", []).insert(0, {"at": now_iso(), "type": "updated", "message": "Project updated"})
    doc["activity"] = doc["activity"][:50]
    doc["updated_at"] = now_iso()
    await projects_coll.replace_one({"id": project_id, "owner_email": owner}, doc)
    await emit_notification(notifications_coll, owner, "project_updated", "Project updated", doc["name"], "project", project_id)
    return Project(**doc)


@api.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str, owner: str = Depends(require_owner)) -> Project:
    doc = await projects_coll.find_one({"id": project_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Project not found.")
    return Project(**doc)


@api.delete("/projects/{project_id}")
async def delete_project(project_id: str, owner: str = Depends(require_owner)) -> dict:
    result = await projects_coll.delete_one({"id": project_id, "owner_email": owner})
    if not result.deleted_count:
        raise HTTPException(404, "Project not found.")
    return {"ok": True}


async def _central_jobs(owner: str) -> list[dict]:
    image = [dict(doc, module="image") async for doc in jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(100)]
    video = [dict(doc, module="video") async for doc in video_generation_jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(100)]
    voice = [dict(doc, module="voice") async for doc in voice_jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(100)]
    talking_portrait = [dict(doc, module="talking-portrait") async for doc in talking_portrait_jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(100)]
    return sorted(image + video + voice + talking_portrait, key=lambda item: item.get("updated_at") or item.get("created_at", ""), reverse=True)[:200]


@api.get("/workspace/overview")
async def workspace_overview(owner: str = Depends(require_owner)) -> dict:
    errors: dict[str, str] = {}
    try:
        jobs = await _central_jobs(owner)
    except Exception:
        jobs = []
        errors["jobs"] = "Job information is unavailable."
    try:
        for job in jobs:
            state = job.get("status")
            if state in {"completed", "failed", "cancelled"}:
                await emit_notification(
                    notifications_coll,
                    owner,
                    f"job_{state}",
                    f"Job {state}",
                    str(job.get("title") or job.get("prompt") or "Workspace job"),
                    "job",
                    str(job.get("id")),
                    str(job.get("module") or "workspace"),
                )
    except Exception:
        logger.exception("Workspace notification sync failed")
        errors["notifications"] = "Job notifications could not be refreshed."
    try:
        media = [doc async for doc in media_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(12)]
    except Exception:
        media = []
        errors["media"] = "Recent media is unavailable."
    try:
        projects = [doc async for doc in projects_coll.find({"owner_email": owner}, {"_id": 0}).sort("updated_at", -1).limit(6)]
    except Exception:
        projects = []
        errors["projects"] = "Recent projects are unavailable."
    try:
        readiness = await settings_readiness(owner)
    except Exception:
        readiness = {"providers": [], "storage": {"available": False}, "security": {}}
        errors["readiness"] = "System readiness is unavailable."
    # Non-critical optional panels should not dominate Control Center warnings.
    critical = {k: v for k, v in errors.items() if k in {"jobs", "media", "projects", "readiness"}}
    return {
        "jobs": jobs,
        "media": media,
        "projects": projects,
        "readiness": readiness,
        "notifications": [job for job in jobs if job.get("status") == "failed"][:5],
        "panel_errors": critical,
        "panel_warnings": errors,
        "refreshed_at": now_iso(),
    }


@api.get("/workspace/search")
async def workspace_search(q: str = "", owner: str = Depends(require_owner)) -> dict:
    term = q.strip()
    if not term:
        return {"media": [], "projects": [], "jobs": [], "identity_packs": [], "modules": []}
    pattern = {"$regex": re.escape(term), "$options": "i"}
    media = [doc async for doc in media_coll.find({"owner_email": owner, "edit_note": pattern}, {"_id": 0}).limit(20)]
    projects = [doc async for doc in projects_coll.find({"owner_email": owner, "$or": [{"name": pattern}, {"description": pattern}, {"notes": pattern}]}, {"_id": 0}).limit(20)]
    packs = [doc async for doc in packs_coll.find({"owner_email": owner, "$or": [{"name": pattern}, {"description": pattern}]}, {"_id": 0}).limit(20)]
    jobs = [job for job in await _central_jobs(owner) if term.lower() in str(job.get("title") or job.get("prompt") or job.get("text") or "").lower()][:20]
    modules = [{"id": item, "name": name, "route": route} for item, name, route in [("image", "Image Studio", "/studio/generate"), ("video", "Video Studio", "/studio/video-studio"), ("voice", "Voice Studio", "/studio/voice-studio"), ("talking-portrait", "Talking Portrait", "/studio/talking-portrait"), ("projects", "Projects", "/studio/projects") ] if term.lower() in name.lower()]
    return {"media": media, "projects": projects, "jobs": jobs, "identity_packs": packs, "modules": modules}


@api.get("/settings/readiness")
async def settings_readiness(_: str = Depends(require_owner)) -> dict:
    statuses = await provider_manager.statuses()
    env = detect_local_environment()
    installation = build_installation_center()
    return {"security": {"owner_configured": bool(os.environ.get("OWNER_EMAIL")), "jwt_configured": bool(os.environ.get("JWT_SECRET")), "secrets_exposed": False}, "storage": local_system_metrics().get("disk", {"available": False}), "providers": [{"id": item.get("id"), "configured": bool(item.get("configured")), "healthy": bool(item.get("healthy")), "state": "Ready" if item.get("configured") and item.get("healthy") else "Requires API key" if not item.get("configured") else "Failed"} for item in statuses], "defaults": {"image_provider": os.environ.get("IMAGE_PROVIDER", "mock"), "video_provider": os.environ.get("VIDEO_PROVIDER", "mock"), "voice_provider": os.environ.get("VOICE_PROVIDER", "mock")}, "environment": env, "installation_center": installation, "first_run": {"works_now": ["Dashboard", "Developer Center", "Document Studio local text extraction", "Photo Studio non-generative editing", "Code Builder safety workflows"], "needs_installation": [item for item in installation["dependencies"] if item["status"] in {"missing", "optional_missing"}], "needs_configuration": [item for item in statuses if not item.get("configured")], "optional": ["Cloud image/video/voice providers", "Ollama coding model"], "unavailable": [cap for cap, state in env.get("capabilities", {}).items() if state not in {"ready"}]}}


@api.get("/settings/preferences")
async def get_preferences(owner: str = Depends(require_owner)) -> dict:
    doc = await preferences_coll.find_one({"owner_email": owner}, {"_id": 0})
    return doc or {"theme": "dark", "default_output": "png", "dashboard_compact": False}


@api.put("/settings/preferences")
async def save_preferences(body: dict, owner: str = Depends(require_owner)) -> dict:
    allowed = {"theme", "default_output", "dashboard_compact", "image_provider", "image_resolution", "image_quality", "image_aspect_ratio", "identity_lock", "output_folder"}
    update = {key: value for key, value in body.items() if key in allowed}
    if update.get("theme", "dark") not in {"dark", "system"} or update.get("default_output", "png") not in {"png", "jpeg", "webp"}:
        raise HTTPException(400, "Invalid application preference.")
    if "image_quality" in update and update["image_quality"] not in IMAGE_STUDIO_QUALITIES:
        raise HTTPException(400, "Invalid image quality preference.")
    if "image_aspect_ratio" in update and update["image_aspect_ratio"] not in IMAGE_STUDIO_RATIOS:
        raise HTTPException(400, "Invalid image aspect ratio preference.")
    if "identity_lock" in update and update["identity_lock"] not in IMAGE_STUDIO_IDENTITY_LOCKS:
        raise HTTPException(400, "Invalid Identity Lock preference.")
    update["owner_email"], update["updated_at"] = owner, now_iso()
    await preferences_coll.update_one({"owner_email": owner}, {"$set": update}, upsert=True)
    return await get_preferences(owner)


@api.get("/media-library")
async def media_library(q: str = "", media_type: str = "", favorite: Optional[bool] = None, project_id: str = "", owner: str = Depends(require_owner)) -> dict:
    query: dict = {"owner_email": owner}
    if favorite is not None: query["favorite"] = favorite
    if project_id: query["project_id"] = project_id
    if media_type: query["mime_type"] = {"$regex": f"^{re.escape(media_type)}/", "$options": "i"}
    if q.strip(): query["$or"] = [{"edit_note": {"$regex": re.escape(q.strip()), "$options": "i"}}, {"tags": {"$regex": re.escape(q.strip()), "$options": "i"}}]
    items = [doc async for doc in media_coll.find(query, {"_id": 0}).sort("created_at", -1).limit(100)]
    return {"items": items, "count": len(items)}


@api.patch("/media-library/{media_id}")
async def update_media_library(media_id: str, body: dict, owner: str = Depends(require_owner)) -> dict:
    allowed = {"favorite", "tags", "folder", "collection_ids", "project_id", "edit_note"}
    update = {key: body[key] for key in allowed if key in body}
    if "tags" in update: update["tags"] = [str(tag).strip() for tag in update["tags"] if str(tag).strip()][:20]
    result = await media_coll.find_one_and_update({"id": media_id, "owner_email": owner}, {"$set": update}, return_document=True, projection={"_id": 0})
    if not result: raise HTTPException(404, "Media not found.")
    return result


@api.get("/media-library/{media_id}/actions")
async def media_actions(media_id: str, owner: str = Depends(require_owner)) -> dict:
    media = await media_coll.find_one({"id": media_id, "owner_email": owner}, {"_id": 0})
    if not media: raise HTTPException(404, "Media not found.")
    return {"preview": True, "download": True, "rename": True, "favorite": True, "delete": False, "reason": "Delete is kept inside the source module to preserve its safeguards."}


@api.get("/workspace/jobs/{module}/{job_id}/actions")
async def workspace_job_actions(module: str, job_id: str, owner: str = Depends(require_owner)) -> dict:
    collections = {"image": jobs_coll, "video": video_generation_jobs_coll, "voice": voice_jobs_coll, "talking-portrait": talking_portrait_jobs_coll}
    coll = collections.get(module)
    if not coll: raise HTTPException(400, "Unsupported job module.")
    job = await coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not job: raise HTTPException(404, "Job not found.")
    active = job.get("status") in {"queued", "preparing", "uploading", "processing", "rendering"}
    retry = module == "video" and job.get("status") in {"failed", "cancelled"}
    return {"cancel": active and module in {"video", "voice", "talking-portrait"}, "retry": retry or (module == "talking-portrait" and job.get("status") in {"failed", "cancelled"}), "output_media_id": job.get("output_media_id") or (job.get("output_media_ids") or [None])[0], "failure_reason": job.get("error")}


@api.get("/workspace/jobs")
async def workspace_jobs(status: str = "", owner: str = Depends(require_owner)) -> dict:
    jobs = await _central_jobs(owner)
    if status: jobs = [job for job in jobs if job.get("status") == status]
    active = {"queued", "preparing", "uploading", "processing", "rendering"}
    return {"jobs": jobs, "active_count": len([job for job in jobs if job.get("status") in active]), "failed_count": len([job for job in jobs if job.get("status") == "failed"])}


@api.get("/notifications", response_model=List[WorkspaceNotification])
async def list_notifications(owner: str = Depends(require_owner)) -> List[WorkspaceNotification]:
    return [WorkspaceNotification(**doc) async for doc in notifications_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1).limit(100)]


@api.patch("/notifications/{notification_id}", response_model=WorkspaceNotification)
async def update_notification(notification_id: str, body: dict, owner: str = Depends(require_owner)) -> WorkspaceNotification:
    doc = await notifications_coll.find_one_and_update({"id": notification_id, "owner_email": owner}, {"$set": {"read": bool(body.get("read", True))}}, return_document=True, projection={"_id": 0})
    if not doc: raise HTTPException(404, "Notification not found.")
    return WorkspaceNotification(**doc)


@api.post("/notifications/mark-all-read")
async def mark_all_notifications_read(owner: str = Depends(require_owner)) -> dict:
    result = await notifications_coll.update_many({"owner_email": owner, "read": False}, {"$set": {"read": True}})
    return {"updated": result.modified_count}


@api.delete("/notifications/{notification_id}")
async def delete_notification(notification_id: str, owner: str = Depends(require_owner)) -> dict:
    result = await notifications_coll.delete_one({"id": notification_id, "owner_email": owner})
    if not result.deleted_count: raise HTTPException(404, "Notification not found.")
    return {"ok": True}


# ---------- Voice Pack / Digital Human contracts ----------
MAX_VOICE_SAMPLE_BYTES = 25 * 1024 * 1024

@api.get("/voice/packs", response_model=List[VoicePack])
async def list_voice_packs(owner: str = Depends(require_owner), include_archived: bool = False) -> List[VoicePack]:
    query = {"owner_email": owner}
    if not include_archived: query["readiness_status"] = {"$ne": "archived"}
    return [VoicePack(**doc) async for doc in voice_packs_coll.find(query, {"_id": 0}).sort("updated_at", -1)]

@api.post("/voice/packs", response_model=VoicePack)
async def create_voice_pack(body: dict, owner: str = Depends(require_owner)) -> VoicePack:
    name = str(body.get("name") or "").strip()
    if not name: raise HTTPException(400, "Voice Pack name is required.")
    if not body.get("consent_confirmed") or not str(body.get("ownership_declaration") or "").strip():
        raise HTTPException(400, "Confirm ownership and consent before creating a Voice Pack.")
    item = VoicePack(owner_email=owner, name=name, description=str(body.get("description") or ""), language=str(body.get("language") or "en"), accent=str(body.get("accent") or ""), gender=str(body.get("gender") or "unspecified"), provider=str(body.get("provider") or "mock"), consent_confirmed=True, consent_at=now_iso(), ownership_declaration=str(body["ownership_declaration"]).strip(), tags=[str(x).strip() for x in body.get("tags", []) if str(x).strip()][:12])
    await voice_packs_coll.insert_one(item.model_dump()); return item

@api.get("/voice/packs/{pack_id}", response_model=VoicePack)
async def get_voice_pack(pack_id: str, owner: str = Depends(require_owner)) -> VoicePack:
    doc = await voice_packs_coll.find_one({"id": pack_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Voice Pack not found")
    return VoicePack(**doc)

@api.patch("/voice/packs/{pack_id}", response_model=VoicePack)
async def update_voice_pack(pack_id: str, body: dict, owner: str = Depends(require_owner)) -> VoicePack:
    doc = await voice_packs_coll.find_one({"id": pack_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Voice Pack not found")
    for field in ("name", "description", "language", "accent", "gender", "favorite", "tags"):
        if field in body: doc[field] = body[field]
    doc["updated_at"] = now_iso(); await voice_packs_coll.replace_one({"id": pack_id, "owner_email": owner}, doc); return VoicePack(**doc)

@api.post("/voice/packs/{pack_id}/archive", response_model=VoicePack)
async def archive_voice_pack(pack_id: str, owner: str = Depends(require_owner)) -> VoicePack:
    return await _voice_pack_status(pack_id, owner, "archived")

@api.post("/voice/packs/{pack_id}/restore", response_model=VoicePack)
async def restore_voice_pack(pack_id: str, owner: str = Depends(require_owner)) -> VoicePack:
    return await _voice_pack_status(pack_id, owner, "draft")

async def _voice_pack_status(pack_id: str, owner: str, status: str) -> VoicePack:
    doc = await voice_packs_coll.find_one({"id": pack_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Voice Pack not found")
    doc.update({"readiness_status": status, "archived_at": now_iso() if status == "archived" else None, "updated_at": now_iso()}); await voice_packs_coll.replace_one({"id": pack_id, "owner_email": owner}, doc); return VoicePack(**doc)

@api.delete("/voice/packs/{pack_id}")
async def delete_voice_pack(pack_id: str, owner: str = Depends(require_owner)) -> dict:
    doc = await voice_packs_coll.find_one_and_delete({"id": pack_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Voice Pack not found")
    for media_id in doc.get("sample_media_ids", []):
        media = await media_coll.find_one_and_delete({"id": media_id, "owner_email": owner}, {"_id": 0})
        if media:
            try: delete_file(media["filename"], "reference")
            except OSError: pass
    return {"ok": True}

@api.post("/voice/packs/{pack_id}/samples")
async def upload_voice_sample(pack_id: str, file: UploadFile = File(...), owner: str = Depends(require_owner)) -> dict:
    pack = await voice_packs_coll.find_one({"id": pack_id, "owner_email": owner}, {"_id": 0})
    if not pack: raise HTTPException(404, "Voice Pack not found")
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_AUDIO_MIMES: raise HTTPException(400, "Upload WAV, MP3, OGG, or WebM audio samples only.")
    data = await file.read()
    if not data or len(data) > MAX_VOICE_SAMPLE_BYTES: raise HTTPException(400, "Audio sample must be between 1 byte and 25 MB.")
    metadata = _inspect_voice_sample(data, mime)
    filename, _, size = save_bytes(data, mime, "reference"); media = MediaAsset(owner_email=owner, filename=filename, mime_type=mime, kind="reference", size_bytes=size, edit_note="voice-pack-sample")
    await media_coll.insert_one(media.model_dump()); pack["sample_media_ids"].append(media.id); pack["sample_count"] = len(pack["sample_media_ids"]); pack["total_sample_duration_seconds"] = round(float(pack.get("total_sample_duration_seconds", 0)) + metadata["duration_seconds"], 3); pack["updated_at"] = now_iso(); await voice_packs_coll.replace_one({"id": pack_id, "owner_email": owner}, pack)
    return {"media_id": media.id, "mime_type": mime, "size_bytes": size, "metadata": metadata}

def _inspect_voice_sample(data: bytes, mime: str) -> dict:
    """Reject empty/disguised content; extract reliable WAV details locally."""
    if mime in {"audio/wav", "audio/x-wav"}:
        try:
            with wave.open(io.BytesIO(data), "rb") as audio:
                rate, channels, frames = audio.getframerate(), audio.getnchannels(), audio.getnframes()
                duration = frames / max(rate, 1)
        except (wave.Error, EOFError) as exc: raise HTTPException(400, "The WAV audio sample is corrupted or unreadable.") from exc
        if not 0 < duration <= 300: raise HTTPException(400, "Voice samples must be no longer than 5 minutes.")
        return {"duration_seconds": round(duration, 3), "sample_rate": rate, "channels": channels}
    signatures = {"audio/webm": b"\x1aE\xdf\xa3", "audio/ogg": b"OggS", "audio/mpeg": b"\xff", "audio/mp3": b"\xff"}
    signature = signatures.get(mime)
    if not signature or not data.startswith(signature): raise HTTPException(400, "The file contents do not match the declared audio format.")
    return {"duration_seconds": 0, "sample_rate": None, "channels": None}

@api.delete("/voice/packs/{pack_id}/samples/{media_id}")
async def remove_voice_sample(pack_id: str, media_id: str, owner: str = Depends(require_owner)) -> dict:
    pack = await voice_packs_coll.find_one({"id": pack_id, "owner_email": owner}, {"_id": 0})
    if not pack or media_id not in pack.get("sample_media_ids", []): raise HTTPException(404, "Voice sample not found")
    media = await media_coll.find_one_and_delete({"id": media_id, "owner_email": owner}, {"_id": 0})
    if media:
        try: delete_file(media["filename"], "reference")
        except OSError: pass
    pack["sample_media_ids"].remove(media_id); pack["sample_count"] = len(pack["sample_media_ids"]); pack["updated_at"] = now_iso(); await voice_packs_coll.replace_one({"id": pack_id, "owner_email": owner}, pack); return {"ok": True}

@api.get("/voice/transcription/providers")
async def transcription_providers(_: str = Depends(require_owner)) -> dict:
    return {"active": os.environ.get("STT_PROVIDER", "mock"), "providers": stt_provider_catalog()}

@api.post("/voice/transcriptions", response_model=TranscriptionJob)
async def create_transcription(background: BackgroundTasks, file: UploadFile = File(...), language: str = Form("auto"), owner: str = Depends(require_owner)) -> TranscriptionJob:
    mime = (file.content_type or "").lower(); data = await file.read()
    if mime not in ALLOWED_AUDIO_MIMES or not data or len(data) > MAX_VOICE_SAMPLE_BYTES: raise HTTPException(400, "Provide a supported audio file up to 25 MB.")
    filename, _, size = save_bytes(data, mime, "reference"); media = MediaAsset(owner_email=owner, filename=filename, mime_type=mime, kind="reference", size_bytes=size, edit_note="transcription-source"); await media_coll.insert_one(media.model_dump())
    job = TranscriptionJob(owner_email=owner, source_media_id=media.id, language=language); await transcription_jobs_coll.insert_one(job.model_dump())
    async def run():
        await transcription_jobs_coll.update_one({"id": job.id}, {"$set": {"status": "processing", "updated_at": now_iso()}})
        try:
            result = await get_stt_provider("mock").transcribe(data, language)
            await transcription_jobs_coll.update_one({"id": job.id}, {"$set": {"status": "completed", "transcript": result["text"], "timestamps": result["timestamps"], "updated_at": now_iso()}})
        except Exception: await transcription_jobs_coll.update_one({"id": job.id}, {"$set": {"status": "failed", "error": "Transcription could not be completed.", "updated_at": now_iso()}})
    background.add_task(run); return job

@api.patch("/voice/transcriptions/{job_id}", response_model=TranscriptionJob)
async def update_transcription(job_id: str, body: dict, owner: str = Depends(require_owner)) -> TranscriptionJob:
    doc = await transcription_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Transcription not found")
    if "transcript" in body: doc["transcript"] = str(body["transcript"])
    doc["updated_at"] = now_iso(); await transcription_jobs_coll.replace_one({"id": job_id, "owner_email": owner}, doc); return TranscriptionJob(**doc)

@api.get("/voice/transcriptions/{job_id}", response_model=TranscriptionJob)
async def get_transcription(job_id: str, owner: str = Depends(require_owner)) -> TranscriptionJob:
    doc = await transcription_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Transcription not found")
    return TranscriptionJob(**doc)

@api.post("/voice/transcriptions/{job_id}/cancel", response_model=TranscriptionJob)
async def cancel_transcription(job_id: str, owner: str = Depends(require_owner)) -> TranscriptionJob:
    doc = await transcription_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Transcription not found")
    if doc["status"] in {"completed", "failed", "cancelled"}: raise HTTPException(400, "This transcription can no longer be cancelled.")
    doc.update({"status": "cancelled", "updated_at": now_iso()}); await transcription_jobs_coll.replace_one({"id": job_id, "owner_email": owner}, doc); return TranscriptionJob(**doc)

@api.get("/voice/talking-video/providers")
async def list_talking_providers(_: str = Depends(require_owner)) -> dict:
    return {"active": os.environ.get("TALKING_FACE_PROVIDER", "mock"), "providers": talking_face_catalog()}

@api.post("/voice/talking-video", response_model=TalkingFaceJob)
async def create_talking_video(background: BackgroundTasks, body: dict, owner: str = Depends(require_owner)) -> TalkingFaceJob:
    if not body.get("consent_confirmed") or not str(body.get("ownership_declaration") or "").strip(): raise HTTPException(400, "Confirm ownership and consent before generating a Digital Human simulation.")
    identity_id, voice_id, audio_id = body.get("identity_pack_id"), body.get("voice_pack_id"), body.get("audio_media_id")
    if identity_id and not await packs_coll.find_one({"id": identity_id, "owner_email": owner}, {"_id": 0}): raise HTTPException(400, "Selected Identity Pack is unavailable.")
    if voice_id and not await voice_packs_coll.find_one({"id": voice_id, "owner_email": owner}, {"_id": 0}): raise HTTPException(400, "Selected Voice Pack is unavailable.")
    if audio_id and not await media_coll.find_one({"id": audio_id, "owner_email": owner}, {"_id": 0}): raise HTTPException(400, "Selected audio is unavailable.")
    if not identity_id: raise HTTPException(400, "Select an Identity Pack for the mock talking video.")
    job = TalkingFaceJob(owner_email=owner, identity_pack_id=identity_id, voice_pack_id=voice_id, audio_media_id=audio_id, script=str(body.get("script") or ""), provider="mock", consent_confirmed=True, consent_at=now_iso(), ownership_declaration=str(body["ownership_declaration"]).strip(), metadata={"simulation": True})
    await talking_face_jobs_coll.insert_one(job.model_dump())
    async def run():
        await talking_face_jobs_coll.update_one({"id": job.id}, {"$set": {"status": "processing", "updated_at": now_iso()}})
        try:
            identity = await packs_coll.find_one({"id": identity_id, "owner_email": owner}, {"_id": 0})
            portrait_id = (identity or {}).get("photo_ids", [None])[0]
            portrait = await media_coll.find_one({"id": portrait_id, "owner_email": owner}, {"_id": 0}) if portrait_id else None
            if not portrait: raise ValueError("Identity Pack has no portrait")
            result = await get_talking_face_provider().generate(job.script, read_bytes(portrait["filename"], "reference"), b"")
            filename, _, size = save_bytes(result.data, result.mime_type, "generated"); media = MediaAsset(owner_email=owner, filename=filename, mime_type=result.mime_type, kind="generated", size_bytes=size, edit_note="digital-human:mock-simulation"); await media_coll.insert_one(media.model_dump())
            await talking_face_jobs_coll.update_one({"id": job.id}, {"$set": {"status": "completed", "output_media_id": media.id, "updated_at": now_iso()}})
        except Exception: await talking_face_jobs_coll.update_one({"id": job.id}, {"$set": {"status": "failed", "error": "The local talking-video simulation could not be completed.", "updated_at": now_iso()}})
    background.add_task(run); return job

@api.get("/voice/talking-video/jobs", response_model=List[TalkingFaceJob])
async def list_talking_jobs(owner: str = Depends(require_owner)) -> List[TalkingFaceJob]:
    return [TalkingFaceJob(**doc) async for doc in talking_face_jobs_coll.find({"owner_email": owner}, {"_id": 0}).sort("created_at", -1)]


# ---------- Talking Portrait Studio ----------
TALKING_PORTRAIT_ACTIVE = {"queued", "preparing", "processing", "rendering", "installing"}


def _validate_talking_portrait_image_upload(photo_bytes: bytes) -> None:
    try:
        with Image.open(io.BytesIO(photo_bytes)) as image:
            image.verify()
        with Image.open(io.BytesIO(photo_bytes)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(400, "Reference photo could not be decoded as a valid image.") from exc
    if width <= 0 or height <= 0:
        raise HTTPException(400, "Reference photo must have positive width and height.")


def _validate_talking_portrait_audio_upload(audio_bytes: bytes, audio_mime: str) -> None:
    ffmpeg = LivePortraitProvider._find_ffmpeg()
    if not ffmpeg:
        raise HTTPException(409, "FFmpeg/FFprobe is required to validate Talking Portrait audio uploads.")
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    if not Path(ffprobe).exists():
        ffprobe = shutil.which("ffprobe") or ffprobe
    suffix = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/webm": ".webm", "audio/ogg": ".ogg"}.get(audio_mime, ".audio")
    with tempfile.TemporaryDirectory(prefix="lumina_talking_portrait_audio_probe_") as temp_dir:
        audio_path = Path(temp_dir) / f"upload{suffix}"
        audio_path.write_bytes(audio_bytes)
        result = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(audio_path)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, shell=False)
    if result.returncode != 0:
        raise HTTPException(400, "Audio file could not be probed or decoded as valid audio.")
    try:
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        duration = float((payload.get("format") or {}).get("duration") or "nan")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Audio duration could not be validated.") from exc
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise HTTPException(400, "Audio file must contain an audio stream.")
    if not math.isfinite(duration) or duration <= 0:
        raise HTTPException(400, "Audio file must have a positive finite duration.")


async def _run_talking_portrait_job(job_id: str, owner: str) -> None:
    async def is_cancelled() -> bool:
        doc = await talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
        return bool(doc and doc.get("status") == "cancelled")

    def should_cancel() -> bool:
        import asyncio as _asyncio
        current = _asyncio.run(talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0}))
        return bool(current and current.get("status") == "cancelled")

    async def stage(status: str, progress: int, eta: Optional[int], message: str = "") -> bool:
        doc = await talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
        if not doc or doc.get("status") == "cancelled":
            return False
        update = {"status": status, "progress": progress, "estimated_seconds_remaining": eta, "updated_at": now_iso()}
        if message:
            update["metadata.stage"] = message
        await talking_portrait_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": update})
        await asyncio.sleep(0.05)
        return True
    try:
        if not await stage("preparing", 10, 8, "Validating media"):
            return
        doc = await talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
        if not doc:
            return
        job = TalkingPortraitJob(**doc)
        provider = get_talking_portrait_provider(job.provider, require_installed=False)
        if not provider.is_installed():
            await stage("installing", 12, None, "LivePortrait not installed. Running automatic installer.")

            def install_update(payload: dict) -> None:
                import asyncio as _asyncio
                message = payload.get("current_message") or payload.get("step") or payload.get("stage") or "Installing LivePortrait"
                progress = min(34, 12 + int((payload.get("progress") or 0) * 0.22))
                _asyncio.run(talking_portrait_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "installing", "progress": progress, "metadata.install_stage": payload.get("stage"), "metadata.install_details": payload, "metadata.stage": message, "updated_at": now_iso()}}))

            def should_cancel_install() -> bool:
                import asyncio as _asyncio
                current = _asyncio.run(talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0}))
                return bool(current and current.get("status") == "cancelled")

            await asyncio.to_thread(LivePortraitInstaller(f"generate-{job_id}", install_update, should_cancel_install).run)
            provider = get_talking_portrait_provider(job.provider, require_installed=True)
        portrait = await media_coll.find_one({"id": job.portrait_media_id, "owner_email": owner}, {"_id": 0})
        audio = await media_coll.find_one({"id": job.audio_media_id, "owner_email": owner}, {"_id": 0})
        if not portrait or not audio:
            raise TalkingPortraitProviderError(job.provider, "Missing source media", "The source photo or audio is no longer available.")
        import tempfile
        with tempfile.TemporaryDirectory(prefix="lumina_talking_portrait_") as temp_dir:
            temp = Path(temp_dir)
            portrait_path = temp / f"portrait{Path(portrait['filename']).suffix or '.png'}"
            audio_path = temp / f"audio{Path(audio['filename']).suffix or '.wav'}"
            output_path = temp / "lumina_talking_portrait.mp4"
            portrait_path.write_bytes(read_bytes(portrait["filename"], "reference"))
            audio_path.write_bytes(read_bytes(audio["filename"], "reference"))
            if not await stage("processing", 35, 12, "Starting provider"):
                return
            async def provider_progress(progress: int, message: str) -> None:
                if await is_cancelled():
                    raise TalkingPortraitCancelledError(job.provider)
                await talking_portrait_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "rendering", "progress": max(35, min(progress, 95)), "metadata.stage": message, "metadata.progress_stage": message, "updated_at": now_iso()}})
            spec = TalkingPortraitInput(portrait_path=portrait_path, portrait_mime=portrait.get("mime_type", "image/png"), audio_path=audio_path, audio_mime=audio.get("mime_type", "audio/wav"), output_path=output_path, identity_lock=job.identity_lock, natural_blinking=job.natural_blinking, head_motion=job.head_motion, expression_intensity=job.expression_intensity, fps=job.fps, resolution=job.resolution, seed=job.seed, should_cancel=should_cancel)
            result = await provider.generate(spec, provider_progress)
        if await is_cancelled():
            return
        filename, _, size = save_bytes(result.data, result.mime_type, "generated")
        if await is_cancelled():
            return
        media = MediaAsset(owner_email=owner, filename=filename, mime_type=result.mime_type, kind="generated", size_bytes=size, parent_media_id=job.portrait_media_id, source_module="talking-portrait", job_id=job.id, provider=job.provider, edit_note=f"talking-portrait:{job.provider}", metadata=result.metadata)
        await media_coll.insert_one(media.model_dump())
        if await is_cancelled():
            return
        await talking_portrait_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "completed", "progress": 100, "estimated_seconds_remaining": 0, "output_media_id": media.id, "output_mime_type": result.mime_type, "metadata.provider_output": result.metadata, "updated_at": now_iso()}})
    except TalkingPortraitCancelledError:
        return
    except Exception as exc:
        if await is_cancelled():
            return
        logger.exception("Talking portrait generation failed: %s", exc)
        technical = {"exception": repr(exc), "exception_type": type(exc).__name__, "stage": getattr(exc, "stage", None), "stdout": getattr(exc, "stdout", None), "stderr": getattr(exc, "stderr", None), "technical_details": getattr(exc, "technical_details", None)}
        if await is_cancelled():
            return
        await talking_portrait_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "failed", "progress": 0, "estimated_seconds_remaining": None, "error": getattr(exc, "safe_message", None) or str(exc), "metadata.error_details": technical, "updated_at": now_iso()}})


@api.get("/talking-portrait/diagnostics")
async def talking_portrait_diagnostics(_: str = Depends(require_owner)) -> dict:
    provider_name = (os.environ.get("TALKING_PORTRAIT_PROVIDER") or auto_detect_talking_portrait_provider()).strip().lower()
    if provider_name == "mock":
        provider_name = "liveportrait"
    provider = get_talking_portrait_provider(provider_name, require_installed=False)
    diagnostics = provider.diagnostics()
    readiness = provider.generation_readiness(diagnostics)
    return {
        "active_provider": provider_name,
        "provider_operational": bool(readiness.get("operational")),
        "operational": bool(readiness.get("operational")),
        "readiness": readiness,
        "readiness_reason": readiness.get("reason"),
        "liveportrait_installation_path": diagnostics.get("repository_path"),
        "python_executable": diagnostics.get("python"),
        "torch_version": diagnostics.get("torch_version"),
        "cuda_available": bool(diagnostics.get("gpu")),
        "selected_device": diagnostics.get("compute_mode"),
        "checkpoint_paths": diagnostics.get("checkpoint_inventory"),
        "ffmpeg_path": diagnostics.get("ffmpeg_path"),
        "ffmpeg_ready": diagnostics.get("ffmpeg_ready"),
        "running_inference": diagnostics.get("running_inference"),
        "latest_log_lines": latest_talking_portrait_log_lines(120),
        "diagnostics": diagnostics,
    }


async def _run_talking_portrait_install(install_id: str, owner: str, provider_name: str) -> None:
    if provider_name != "liveportrait":
        await talking_portrait_installs_coll.update_one({"id": install_id, "owner_email": owner}, {"$set": {"status": "failed", "stage": "failed", "error": "Only LivePortrait installation is supported.", "error_code": "unsupported_provider", "updated_at": now_iso()}})
        return

    def update(payload: dict) -> None:
        payload = dict(payload)
        payload["recent_log_lines"] = recent_log_lines(install_id)
        payload["log"] = payload["recent_log_lines"][-30:]
        payload.setdefault("install_job_id", install_id)
        import asyncio as _asyncio
        _asyncio.run(talking_portrait_installs_coll.update_one({"id": install_id, "owner_email": owner}, {"$set": payload}))

    def should_cancel() -> bool:
        import asyncio as _asyncio
        doc = _asyncio.run(talking_portrait_installs_coll.find_one({"id": install_id, "owner_email": owner}, {"_id": 0}))
        return bool(doc and doc.get("status") == "cancel_requested")

    await asyncio.to_thread(LivePortraitInstaller(install_id, update, should_cancel).run)


@api.get("/talking-portrait/providers")
async def list_talking_portrait_providers(_: str = Depends(require_owner)) -> dict:
    active = os.environ.get("TALKING_PORTRAIT_PROVIDER") or auto_detect_talking_portrait_provider()
    if active == "mock":
        active = "liveportrait"
    provider = get_talking_portrait_provider(active, require_installed=False)
    diagnostics = provider.diagnostics(quick=True)
    readiness = provider.generation_readiness(diagnostics)
    return {"active": active if readiness.get("operational") else None, "configured": active, "operational": bool(readiness.get("operational")), "readiness": readiness, "readiness_reason": readiness.get("reason"), "available": available_talking_portrait_providers(), "providers": talking_portrait_catalog(), "diagnostics": diagnostics}


@api.post("/talking-portrait/install", response_model=TalkingPortraitInstallJob, status_code=202)
async def install_talking_portrait_provider(background: BackgroundTasks, body: dict, owner: str = Depends(require_owner)) -> TalkingPortraitInstallJob:
    provider = str(body.get("provider") or "liveportrait").lower()
    if provider != "liveportrait":
        raise HTTPException(400, "Only LivePortrait can be installed by this installer.")
    active = await talking_portrait_installs_coll.find_one({"owner_email": owner, "provider": provider, "status": {"$in": list(ACTIVE_INSTALL_STATES)}}, {"_id": 0})
    if active:
        active["install_job_id"] = active.get("install_job_id") or active.get("id")
        return TalkingPortraitInstallJob(**active)
    install_id = new_id()
    install = TalkingPortraitInstallJob(**build_initial_install_payload(install_id, owner))
    await talking_portrait_installs_coll.insert_one(install.model_dump())
    background.add_task(_run_talking_portrait_install, install.id, owner, provider)
    return install


@api.get("/talking-portrait/install/{install_id}", response_model=TalkingPortraitInstallJob)
async def get_talking_portrait_install(install_id: str, owner: str = Depends(require_owner)) -> TalkingPortraitInstallJob:
    doc = await talking_portrait_installs_coll.find_one({"id": install_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Install job not found")
    doc["install_job_id"] = doc.get("install_job_id") or doc.get("id")
    doc["recent_log_lines"] = recent_log_lines(install_id)
    doc["log"] = doc["recent_log_lines"][-30:]
    return TalkingPortraitInstallJob(**doc)


@api.post("/talking-portrait/install/{install_id}/cancel", response_model=TalkingPortraitInstallJob)
async def cancel_talking_portrait_install(install_id: str, owner: str = Depends(require_owner)) -> TalkingPortraitInstallJob:
    doc = await talking_portrait_installs_coll.find_one({"id": install_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Install job not found")
    if doc.get("status") in {"queued", "running", "cancel_requested"}:
        await talking_portrait_installs_coll.update_one({"id": install_id, "owner_email": owner}, {"$set": {"status": "cancel_requested", "stage": "cancelled", "current_message": "Cancellation requested", "step": "Cancellation requested", "updated_at": now_iso()}})
    return await get_talking_portrait_install(install_id, owner)


@api.post("/talking-portrait/install/{install_id}/retry", response_model=TalkingPortraitInstallJob, status_code=202)
async def retry_talking_portrait_install(install_id: str, background: BackgroundTasks, owner: str = Depends(require_owner)) -> TalkingPortraitInstallJob:
    doc = await talking_portrait_installs_coll.find_one({"id": install_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Install job not found")
    active = await talking_portrait_installs_coll.find_one({"owner_email": owner, "provider": "liveportrait", "status": {"$in": list(ACTIVE_INSTALL_STATES)}}, {"_id": 0})
    if active:
        active["install_job_id"] = active.get("install_job_id") or active.get("id")
        return TalkingPortraitInstallJob(**active)
    retry_id = new_id()
    retry = TalkingPortraitInstallJob(**build_initial_install_payload(retry_id, owner, retry_of=install_id))
    await talking_portrait_installs_coll.insert_one(retry.model_dump())
    background.add_task(_run_talking_portrait_install, retry.id, owner, "liveportrait")
    return retry


@api.post("/talking-portrait/generate", response_model=TalkingPortraitJob)
async def create_talking_portrait_job(background: BackgroundTasks, photo: UploadFile = File(...), audio: UploadFile = File(...), identity_lock: bool = Form(True), natural_blinking: bool = Form(True), head_motion: float = Form(0.35), expression_intensity: float = Form(0.55), fps: int = Form(25), resolution: str = Form("512"), seed: Optional[int] = Form(None), title: str = Form("Talking portrait"), tags: str = Form(""), provider: Optional[str] = Form(None), owner: str = Depends(require_owner)) -> TalkingPortraitJob:
    selected_provider = (provider or os.environ.get("TALKING_PORTRAIT_PROVIDER") or auto_detect_talking_portrait_provider()).strip().lower()
    if selected_provider == "mock":
        selected_provider = "liveportrait"
    try:
        provider_instance = get_talking_portrait_provider(selected_provider, require_installed=False)
    except TalkingPortraitProviderError as exc:
        raise HTTPException(409, {"message": exc.safe_message, "stage": exc.stage, "stdout": exc.stdout, "stderr": exc.stderr, "technical_details": exc.technical_details}) from exc
    diagnostics = provider_instance.diagnostics(quick=True)
    readiness = provider_instance.generation_readiness(diagnostics)
    if not readiness.get("operational"):
        raise HTTPException(409, {"message": readiness.get("reason") or "Talking Portrait provider is not ready.", "stage": "provider_readiness", "technical_details": {"readiness": readiness, "diagnostics": diagnostics}})
    photo_mime = (photo.content_type or "").lower(); audio_mime = (audio.content_type or "").lower()
    if photo_mime not in ALLOWED_MIMES:
        raise HTTPException(400, "Upload a PNG, JPEG, JPG, or WebP reference photo.")
    if audio_mime not in ALLOWED_AUDIO_MIMES:
        raise HTTPException(400, "Upload WAV, MP3, WebM, OGG, or MPEG audio.")
    photo_bytes, audio_bytes = await photo.read(), await audio.read()
    if not photo_bytes or len(photo_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Reference photo must be between 1 byte and 15 MB.")
    if not audio_bytes or len(audio_bytes) > 75 * 1024 * 1024:
        raise HTTPException(400, "Audio file must be between 1 byte and 75 MB.")
    _validate_talking_portrait_image_upload(photo_bytes)
    _validate_talking_portrait_audio_upload(audio_bytes, audio_mime)
    photo_filename, _, photo_size = save_bytes(photo_bytes, photo_mime, "reference")
    audio_filename, _, audio_size = save_bytes(audio_bytes, audio_mime, "reference")
    photo_media = MediaAsset(owner_email=owner, filename=photo_filename, mime_type=photo_mime, kind="reference", size_bytes=photo_size, source_module="talking-portrait", edit_note="talking-portrait-photo")
    audio_media = MediaAsset(owner_email=owner, filename=audio_filename, mime_type=audio_mime, kind="reference", size_bytes=audio_size, source_module="talking-portrait", edit_note="talking-portrait-audio")
    await media_coll.insert_one(photo_media.model_dump()); await media_coll.insert_one(audio_media.model_dump())
    job = TalkingPortraitJob(owner_email=owner, provider=selected_provider, portrait_media_id=photo_media.id, audio_media_id=audio_media.id, identity_lock=identity_lock, natural_blinking=natural_blinking, head_motion=max(0, min(float(head_motion), 1)), expression_intensity=max(0, min(float(expression_intensity), 1)), fps=fps if fps in {24, 25, 30} else 25, resolution=resolution if resolution in {"256", "512", "768"} else "512", seed=seed, title=title.strip() or "Talking portrait", tags=[item.strip() for item in tags.split(",") if item.strip()][:12], metadata={"gpu_detection": get_talking_portrait_provider(selected_provider, require_installed=False).diagnostics()})
    await talking_portrait_jobs_coll.insert_one(job.model_dump())
    background.add_task(_run_talking_portrait_job, job.id, owner)
    return job


@api.get("/talking-portrait/jobs", response_model=List[TalkingPortraitJob])
async def list_talking_portrait_jobs(owner: str = Depends(require_owner), status: str = "", search: str = "", limit: int = 100) -> List[TalkingPortraitJob]:
    query = {"owner_email": owner}
    if status:
        query["status"] = status
    if search.strip():
        query["title"] = {"$regex": search.strip(), "$options": "i"}
    return [TalkingPortraitJob(**doc) async for doc in talking_portrait_jobs_coll.find(query, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 100)))]


@api.get("/talking-portrait/jobs/{job_id}", response_model=TalkingPortraitJob)
async def get_talking_portrait_job(job_id: str, owner: str = Depends(require_owner)) -> TalkingPortraitJob:
    doc = await talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Talking portrait job not found")
    return TalkingPortraitJob(**doc)


@api.post("/talking-portrait/jobs/{job_id}/cancel", response_model=TalkingPortraitJob)
async def cancel_talking_portrait_job(job_id: str, owner: str = Depends(require_owner)) -> TalkingPortraitJob:
    doc = await talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Talking portrait job not found")
    if doc.get("status") not in TALKING_PORTRAIT_ACTIVE:
        raise HTTPException(400, "This talking portrait job can no longer be cancelled.")
    doc.update({"status": "cancelled", "cancelled_at": now_iso(), "estimated_seconds_remaining": None, "updated_at": now_iso()})
    await talking_portrait_jobs_coll.replace_one({"id": job_id, "owner_email": owner}, doc)
    return TalkingPortraitJob(**doc)


@api.post("/talking-portrait/jobs/{job_id}/retry", response_model=TalkingPortraitJob)
async def retry_talking_portrait_job(job_id: str, background: BackgroundTasks, owner: str = Depends(require_owner)) -> TalkingPortraitJob:
    doc = await talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Talking portrait job not found")
    if doc.get("status") not in {"failed", "cancelled"}:
        raise HTTPException(400, "Only failed or cancelled jobs can be retried.")
    payload = {k: v for k, v in doc.items() if k not in {"id", "_id", "owner_email", "status", "progress", "estimated_seconds_remaining", "output_media_id", "output_mime_type", "error", "cancelled_at", "created_at", "updated_at"}}
    retry = TalkingPortraitJob(**payload, owner_email=owner, retry_of=job_id, status="queued", progress=0)
    await talking_portrait_jobs_coll.insert_one(retry.model_dump())
    background.add_task(_run_talking_portrait_job, retry.id, owner)
    return retry


@api.get("/talking-portrait/results/{job_id}")
async def get_talking_portrait_result(job_id: str, owner: str = Depends(require_owner)) -> Response:
    job = await talking_portrait_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not job or not job.get("output_media_id"):
        raise HTTPException(404, "Talking portrait result is not ready yet")
    media = await media_coll.find_one({"id": job["output_media_id"], "owner_email": owner}, {"_id": 0})
    if not media:
        raise HTTPException(404, "Talking portrait result is missing")
    return Response(content=read_bytes(media["filename"], "generated"), media_type=media.get("mime_type", "video/mp4"), headers={"Content-Disposition": f'attachment; filename="lumina-talking-portrait-{job_id}.mp4"'})

@api.get("/voice/talking-video/{job_id}", response_model=TalkingFaceJob)
async def get_talking_video(job_id: str, owner: str = Depends(require_owner)) -> TalkingFaceJob:
    doc = await talking_face_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Talking-video job not found")
    return TalkingFaceJob(**doc)

@api.post("/voice/talking-video/{job_id}/cancel", response_model=TalkingFaceJob)
async def cancel_talking_video(job_id: str, owner: str = Depends(require_owner)) -> TalkingFaceJob:
    doc = await talking_face_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc: raise HTTPException(404, "Talking-video job not found")
    if doc["status"] in {"completed", "failed", "cancelled"}: raise HTTPException(400, "This job can no longer be cancelled.")
    doc.update({"status": "cancelled", "updated_at": now_iso()}); await talking_face_jobs_coll.replace_one({"id": job_id, "owner_email": owner}, doc); return TalkingFaceJob(**doc)


# ---------- Code Creator (local projects + Ollama) ----------
@api.get("/code-creator/status")
async def code_creator_status(_: str = Depends(require_owner)) -> dict:
    return code_ollama_status()

@api.get("/code-creator/projects")
async def code_creator_projects(_: str = Depends(require_owner)) -> list[dict]:
    return code_list_projects()

@api.post("/code-creator/projects")
async def code_creator_create(body: dict, _: str = Depends(require_owner)) -> dict:
    name = str(body.get("name") or "").strip()
    description = str(body.get("description") or "").strip()
    if not name or not description:
        raise HTTPException(400, "Project name and description are required.")
    return code_create_project(name, description, str(body.get("stack") or "auto"))

@api.get("/code-creator/projects/{project_id}")
async def code_creator_get(project_id: str, _: str = Depends(require_owner)) -> dict:
    try:
        return code_get_project(project_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Code project not found.")

@api.post("/code-creator/projects/{project_id}/generate")
async def code_creator_generate(project_id: str, _: str = Depends(require_owner)) -> dict:
    try:
        return await asyncio.to_thread(code_generate_project, project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Code project not found.")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        logger.exception("Code generation failed")
        raise HTTPException(502, f"Code generation failed: {exc}")

@api.get("/code-creator/projects/{project_id}/file")
async def code_creator_file(project_id: str, path: str, _: str = Depends(require_owner)) -> dict:
    try:
        return code_read_file(project_id, path)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "File not found.")

@api.post("/code-creator/projects/{project_id}/check")
async def code_creator_check(project_id: str, _: str = Depends(require_owner)) -> dict:
    try:
        return await asyncio.to_thread(code_run_safe_check, project_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Code project not found.")

# ---------- Boot ----------
app.include_router(api)
app.include_router(code_builder_router)
app.include_router(document_studio_router)
app.include_router(runtime_router)


def _active_private_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
        ip = ipaddress.ip_address(candidate)
        if ip.version == 4 and ip.is_private and not ip.is_loopback:
            return candidate
    except OSError:
        return None
    return None


def _cors_origins() -> list[str]:
    configured = [origin.strip().rstrip("/") for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()]
    defaults = ["http://localhost:3000", "http://127.0.0.1:3000"]
    lan_ip = _active_private_lan_ip()
    if lan_ip:
        defaults.append(f"http://{lan_ip}:3000")
    return sorted(set(configured + defaults))


def _trusted_hosts() -> list[str]:
    configured = [host.strip() for host in os.environ.get("TRUSTED_HOSTS", "").split(",") if host.strip()]
    defaults = ["localhost", "127.0.0.1", socket.gethostname(), f"{socket.gethostname()}.local"]
    lan_ip = _active_private_lan_ip()
    if lan_ip:
        defaults.append(lan_ip)
    return sorted(set(configured + defaults))


app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=_trusted_hosts(),
)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins(),
    allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX", r"^http://(localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})(?::3000)?$"),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    global persistence_provider, talking_portrait_jobs_coll, talking_portrait_installs_coll
    await persistence_provider.initialize()
    await persistence_provider.verify()
    await persistence_provider.recover_active_jobs()
    talking_portrait_jobs_coll = TalkingPortraitCollection(persistence_provider, "talking_portrait_jobs")
    talking_portrait_installs_coll = TalkingPortraitCollection(persistence_provider, "talking_portrait_install_jobs")
    _configure_local_first_collections()
    logger.info("Persistence ready: %s", persistence_provider.diagnostics())


@app.on_event("shutdown")
async def _shutdown() -> None:
    return None
