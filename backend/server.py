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
import logging
import os
import io
import wave
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
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
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

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
    TokenResponse,
    VideoGenerationJob,
    VideoLibraryOrganization,
    VoiceJob,
    VoiceLibraryOrganization,
    VoicePack,
    TranscriptionJob,
    TalkingFaceJob,
    VideoProject,
    now_iso,
)
from providers import (  # noqa: E402
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
from fastapi import Depends  # noqa: E402
from code_creator import create_project as code_create_project, generate_project as code_generate_project, get_project as code_get_project, list_projects as code_list_projects, ollama_status as code_ollama_status, read_file as code_read_file, run_safe_check as code_run_safe_check  # noqa: E402
from runtime_info import (  # noqa: E402
    APP_VERSION,
    build_system_status,
    load_runtime_config,
    save_runtime_settings,
    validate_runtime_settings,
)

logger = logging.getLogger("lumina")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# ---------- Mongo ----------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

media_coll = db["lumina_media"]
packs_coll = db["lumina_identity_packs"]
jobs_coll = db["lumina_jobs"]
gallery_coll = db["lumina_gallery"]
video_generation_jobs_coll = db["lumina_video_generation_jobs"]
video_library_orgs_coll = db["lumina_video_library_organizations"]
voice_jobs_coll = db["lumina_voice_jobs"]
voice_library_orgs_coll = db["lumina_voice_library_organizations"]
voice_packs_coll = db["lumina_voice_packs"]
transcription_jobs_coll = db["lumina_transcription_jobs"]
talking_face_jobs_coll = db["lumina_talking_face_jobs"]
projects_coll = db["lumina_projects"]
preferences_coll = db["lumina_preferences"]
notifications_coll = db["lumina_notifications"]

ALLOWED_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
ALLOWED_VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm", "video/x-msvideo"}
ALLOWED_AUDIO_MIMES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB (images / mask)
MAX_VIDEO_ASSET_BYTES = 500 * 1024 * 1024  # 500 MB (video / audio for editor)
MAX_PHOTOS_PER_PACK = 5
VIDEO_STUDIO_DURATIONS = {3, 5, 8}
VIDEO_STUDIO_ASPECT_RATIOS = {"16:9", "9:16"}

app = FastAPI(title="Lumina AI Desktop API")
api = APIRouter(prefix="/api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ProviderError)
async def provider_error_handler(request, exc: ProviderError):
    logger.warning("Provider error: %s", exc)
    return Response(
        content="A provider service failed. Please try again later.",
        status_code=502,
        media_type="text/plain",
    )


@app.exception_handler(ProviderTimeoutError)
async def provider_timeout_handler(request, exc: ProviderTimeoutError):
    logger.warning("Provider timeout: %s", exc)
    return Response(
        content="The image provider timed out. Please try again in a moment.",
        status_code=504,
        media_type="text/plain",
    )


# ---------- Health / providers ----------
@api.get("/health")
async def health() -> dict:
    statuses = await provider_manager.statuses()
    return {
        "status": "ok",
        "backend": "ok",
        "timestamp": now_iso(),
        "version": APP_VERSION,
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
        await db.command("ping")
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
    ready_providers = [item for item in provider_statuses if item.get("configured") and item.get("healthy")]
    checks.extend([
        {"name": "Backend", "status": "ready", "detail": "LUMINA backend is responding."},
        {"name": "Frontend", "status": "working", "detail": "Check the local browser address for frontend availability."},
        {"name": "Job system", "status": "ready", "detail": "Local application jobs are available."},
        {"name": "Provider system", "status": "ready" if ready_providers else "warning", "detail": f"{len(ready_providers)} configured provider(s) ready."},
    ])
    return {"checks": checks, "metrics": local_system_metrics(), "refreshed_at": now_iso()}


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
    except Exception:
        image_jobs, video_jobs = [], []
        panel_errors["media_jobs"] = "Application job information is unavailable."
    active_media_jobs = [
        {"id": job.id, "kind": "image", "title": job.prompt or "Image generation", "status": job.status, "created_at": job.created_at}
        for job in image_jobs if job.status in {"queued", "processing"}
    ] + [
        {"id": job.id, "kind": "video", "title": job.title or "Video generation", "status": job.status, "progress": job.progress, "created_at": job.created_at}
        for job in video_jobs if job.status in {"queued", "preparing", "uploading", "processing", "rendering"}
    ]
    return {"health": health, "repository": repository, "tasks": developer_manager.list_tasks(), "logs": developer_manager.list_logs(), "media_jobs": active_media_jobs[:20], "panel_errors": panel_errors, "refreshed_at": now_iso(), "scope": "Local LUMINA activity only. External AI task activity is not monitored."}


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
    pack = await  get_pack(pack_id, owner)
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
        {"id": job_id}, {"$set": {"status": "processing", "updated_at": now_iso()}}
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

        gen_in = GenerationInput(
            prompt=spec.prompt,
            negative_prompt=spec.negative_prompt or "",
            scene=spec.scene or "",
            outfit=spec.outfit or "",
            aspect_ratio=spec.aspect_ratio or "1:1",
            count=max(1, min(4, spec.count or 1)),
            reference_images=ref_bytes,
            reference_mimes=ref_mimes,
        )

        route = await provider_manager.generate_result(gen_in, requested=spec.provider)
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
            )
            await media_coll.insert_one(media.model_dump())
            output_ids.append(media.id)

            gallery = GalleryItem(
                owner_email=owner,
                media_id=media.id,
                job_id=job_id,
                identity_pack_id=spec.identity_pack_id,
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
                    "output_media_ids": output_ids,
                    "provider": provider_name,
                    "selected_provider": provider_name,
                    "attempted_providers": route.attempted_providers,
                    "provider_failures": route.provider_failures,
                    "fallback_used": route.fallback_used,
                    "generation_duration_ms": route.generation_duration_ms,
                    "updated_at": now_iso(),
                }
            },
        )
    except Exception as e:
        logger.exception("Generation failed: %s", e)
        await jobs_coll.update_one(
            {"id": job_id},
            {"$set": {"status": "failed", "error": getattr(e, "safe_message", None) or str(e), "updated_at": now_iso()}},
        )


@api.post("/generate", response_model=GenerationJob)
async def generate(
    body: GenerationRequest,
    background: BackgroundTasks,
    owner: str = Depends(require_owner),
) -> GenerationJob:
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(400, "Prompt is required")
    provider_name = (body.provider or os.environ.get("IMAGE_PROVIDER") or "gemini").lower()

    job = GenerationJob(
        owner_email=owner,
        provider=provider_name,
        identity_pack_id=body.identity_pack_id,
        prompt=body.prompt.strip(),
        negative_prompt=body.negative_prompt or "",
        scene=body.scene or "",
        outfit=body.outfit or "",
        aspect_ratio=body.aspect_ratio or "1:1",
        count=max(1, min(4, body.count or 1)),
    )
    await jobs_coll.insert_one(job.model_dump())
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


# ---------- Editor: versions + sessions ----------
sessions_coll = db["lumina_editor_sessions"]
ai_edit_jobs_coll = db["lumina_ai_edit_jobs"]


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
}
AI_TOOLS = list(AI_TOOL_PROMPTS.keys())


async def _run_ai_edit(job_id: str, owner: str) -> None:
    """Background task: run one AI edit job."""
    doc = await ai_edit_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not doc:
        return
    job = AiEditJob(**doc)
    await ai_edit_jobs_coll.update_one(
        {"id": job_id}, {"$set": {"status": "processing", "updated_at": now_iso()}}
    )
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

        base_prompt = AI_TOOL_PROMPTS.get(job.tool, AI_TOOL_PROMPTS["enhance"])
        full_instruction = f"{base_prompt}\nUser instruction: {job.instruction}" if job.instruction else base_prompt

        route = await provider_manager.edit_result(
            source_bytes=src_bytes,
            source_mime=src_mime,
            instruction=full_instruction,
            mask_bytes=mask_bytes,
            mask_mime=mask_mime,
            identity_refs=identity_refs or None,
            requested=job.provider,
        )
        result = route.images[0]

        filename, _abs, size = save_bytes(result.data, result.mime_type, kind="generated")
        out_media = MediaAsset(
            owner_email=owner,
            filename=filename,
            mime_type=result.mime_type,
            kind="edited",
            parent_media_id=job.source_media_id,
            edit_note=f"AI: {job.tool}",
            size_bytes=size,
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
            prompt=f"AI {job.tool}: {job.instruction}"[:500],
            scene=(parent_gallery or {}).get("scene", ""),
            outfit=(parent_gallery or {}).get("outfit", ""),
            aspect_ratio=(parent_gallery or {}).get("aspect_ratio", "1:1"),
            provider=f"{route.provider}:{job.tool}",
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
                    "updated_at": now_iso(),
                }
            },
        )
    except Exception as e:
        logger.exception("AI edit failed: %s", e)
        await ai_edit_jobs_coll.update_one(
            {"id": job_id, "status": {"$ne": "canceled"}},
            {"$set": {"status": "failed", "error": getattr(e, "safe_message", None) or str(e), "updated_at": now_iso()}},
        )


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
    identity_pack_id: Optional[str] = Form(None),
    mask: Optional[UploadFile] = File(None),
    provider: Optional[str] = Form(None),
    owner: str = Depends(require_owner),
) -> AiEditJob:
    if tool not in AI_TOOL_PROMPTS:
        raise HTTPException(400, f"Unknown tool: {tool}")

    src = await media_coll.find_one({"id": source_media_id, "owner_email": owner}, {"_id": 0})
    if not src:
        raise HTTPException(404, "Source media not found")

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
        identity_pack_id=identity_pack_id,
        instruction=instruction or "",
        mask_media_id=mask_media_id,
    )
    await ai_edit_jobs_coll.insert_one(job.model_dump())
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
        identity_pack_id=original.identity_pack_id,
        instruction=original.instruction,
        mask_media_id=original.mask_media_id,
        retry_of=original.id,
    )
    await ai_edit_jobs_coll.insert_one(new_job.model_dump())
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
    return AiEditJob(**{**job.model_dump(), "status": "canceled", "updated_at": now_iso()})


@api.post("/editor/versions")
async def save_edited_version(
    source_media_id: str = Form(...),
    edit_note: str = Form(""),
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

    filename, _abs, size = save_bytes(data, mime, kind="generated")  # store next to generated
    media = MediaAsset(
        owner_email=owner,
        filename=filename,
        mime_type=mime,
        kind="edited",
        parent_media_id=source_media_id,
        edit_note=edit_note or None,
        size_bytes=size,
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


# ---------- Video Editor: projects + asset uploads ----------
video_projects_coll = db["lumina_video_projects"]


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
        if getattr(provider, "supports_async_jobs", False):
            submitted = await provider.submit(spec)
            await video_generation_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "processing", "progress": 35, "estimated_seconds_remaining": None, "metadata.provider_job_id": submitted.id, "metadata.provider_status": submitted.state, "updated_at": now_iso()}})
            poll_interval = max(1, int(os.environ.get("VIDEO_PROVIDER_POLL_INTERVAL_SECONDS", "5")))
            max_wait = max(poll_interval, int(os.environ.get("VIDEO_PROVIDER_MAX_POLL_SECONDS", "600")))
            elapsed = 0
            while elapsed < max_wait:
                await asyncio.sleep(poll_interval); elapsed += poll_interval
                current = await video_generation_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
                if not current or current.get("status") == "cancelled": return
                remote = await provider.poll(submitted.id)
                raw_state = remote.state.lower()
                if raw_state in {"failed", "error"}:
                    raise VideoProviderError(job.provider, "Provider generation failed", "The video provider could not complete this generation.")
                if raw_state in {"completed", "complete", "succeeded"}:
                    if not await stage("rendering", 90, 1): return
                    result = await provider.download(remote)
                    break
                progress = 60 if raw_state in {"dreaming", "processing", "generating"} else 45
                await video_generation_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "processing", "progress": progress, "metadata.provider_status": remote.state, "updated_at": now_iso()}})
            else:
                raise VideoProviderError(job.provider, "Provider polling timed out", "The video provider took too long. You can retry this job.", retryable=True)
        else:
            if not await stage("rendering", 82, 1): return
            result = await provider.generate(spec)
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
        state=body.get("state") or {},
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
    for field in ("name", "aspect_ratio", "fps", "resolution", "state", "exported_media_id"):
        if field in body:
            doc[field] = body[field]
    doc["updated_at"] = now_iso()
    await video_projects_coll.replace_one({"id": project_id}, doc)
    return VideoProject(**doc)


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
VOICE_MODES = {"text-to-speech", "speech-to-text", "voice-clone", "enhance", "noise-reduction", "trim", "normalize", "silence-removal", "volume", "convert", "batch"}

async def _run_voice_job(job_id: str, owner: str) -> None:
    try:
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "preparing", "progress": 15, "updated_at": now_iso()}})
        await asyncio.sleep(.03)
        doc = await voice_jobs_coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
        if not doc or doc.get("status") == "cancelled": return
        job = VoiceJob(**doc)
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "processing", "progress": 55, "updated_at": now_iso()}})
        provider = get_voice_provider(job.provider)
        data, mime, metadata = await provider.generate(job.text or job.title, job.voice, job.output_format)
        filename, _, size = save_bytes(data, mime, kind="generated")
        media = MediaAsset(owner_email=owner, filename=filename, mime_type=mime, kind="generated", size_bytes=size, edit_note=f"voice-studio:{job.provider}")
        await media_coll.insert_one(media.model_dump())
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "completed", "progress": 100, "output_media_id": media.id, "metadata": metadata, "updated_at": now_iso()}})
    except Exception as exc:
        logger.exception("Voice job failed: %s", exc)
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "failed", "error": "Audio processing could not be completed.", "updated_at": now_iso()}})

@api.get("/voice/providers")
async def list_voice_providers(_: str = Depends(require_owner)) -> dict:
    return {"active": os.environ.get("VOICE_PROVIDER", "mock"), "providers": voice_provider_catalog()}

@api.post("/voice/generate", response_model=VoiceJob)
async def create_voice_job(background: BackgroundTasks, text: str = Form(""), mode: str = Form("text-to-speech"), voice: str = Form("lumina"), output_format: str = Form("wav"), title: str = Form(""), tags: str = Form(""), provider: Optional[str] = Form(None), owner: str = Depends(require_owner)) -> VoiceJob:
    if mode not in VOICE_MODES: raise HTTPException(400, "Unsupported voice operation.")
    selected = (provider or os.environ.get("VOICE_PROVIDER", "mock")).lower()
    try: engine = get_voice_provider(selected)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    if mode not in engine.capabilities["modes"]: raise HTTPException(400, "The selected voice provider does not support this operation.")
    if output_format not in engine.capabilities["formats"]: raise HTTPException(400, "The selected voice provider does not support this output format.")
    if mode == "text-to-speech" and not text.strip(): raise HTTPException(400, "Enter text to generate speech.")
    job = VoiceJob(owner_email=owner, provider=selected, mode=mode, text=text.strip(), voice=voice, output_format=output_format, title=(title.strip() or text.strip()[:80] or "Untitled audio"), tags=[tag.strip() for tag in tags.split(",") if tag.strip()][:12])
    await voice_jobs_coll.insert_one(job.model_dump()); background.add_task(_run_voice_job, job.id, owner)
    return job

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
    return sorted(image + video + voice, key=lambda item: item.get("updated_at") or item.get("created_at", ""), reverse=True)[:200]


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
    modules = [{"id": item, "name": name, "route": route} for item, name, route in [("image", "Image Studio", "/studio/generate"), ("video", "Video Studio", "/studio/video-studio"), ("voice", "Voice Studio", "/studio/voice-studio"), ("projects", "Projects", "/studio/projects") ] if term.lower() in name.lower()]
    return {"media": media, "projects": projects, "jobs": jobs, "identity_packs": packs, "modules": modules}


@api.get("/settings/readiness")
async def settings_readiness(_: str = Depends(require_owner)) -> dict:
    statuses = await provider_manager.statuses()
    return {"security": {"owner_configured": bool(os.environ.get("OWNER_EMAIL")), "jwt_configured": bool(os.environ.get("JWT_SECRET")), "secrets_exposed": False}, "storage": local_system_metrics().get("disk", {"available": False}), "providers": [{"id": item.get("id"), "configured": bool(item.get("configured")), "healthy": bool(item.get("healthy"))} for item in statuses], "defaults": {"image_provider": os.environ.get("IMAGE_PROVIDER", "mock"), "video_provider": os.environ.get("VIDEO_PROVIDER", "mock"), "voice_provider": os.environ.get("VOICE_PROVIDER", "mock")}}


@api.get("/settings/preferences")
async def get_preferences(owner: str = Depends(require_owner)) -> dict:
    doc = await preferences_coll.find_one({"owner_email": owner}, {"_id": 0})
    return doc or {"theme": "dark", "default_output": "png", "dashboard_compact": False}


@api.put("/settings/preferences")
async def save_preferences(body: dict, owner: str = Depends(require_owner)) -> dict:
    allowed = {"theme", "default_output", "dashboard_compact"}
    update = {key: value for key, value in body.items() if key in allowed}
    if update.get("theme", "dark") not in {"dark", "system"} or update.get("default_output", "png") not in {"png", "jpeg", "webp"}:
        raise HTTPException(400, "Invalid application preference.")
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
    collections = {"image": jobs_coll, "video": video_generation_jobs_coll, "voice": voice_jobs_coll}
    coll = collections.get(module)
    if not coll: raise HTTPException(400, "Unsupported job module.")
    job = await coll.find_one({"id": job_id, "owner_email": owner}, {"_id": 0})
    if not job: raise HTTPException(404, "Job not found.")
    active = job.get("status") in {"queued", "preparing", "uploading", "processing", "rendering"}
    retry = module == "video" and job.get("status") in {"failed", "cancelled"}
    return {"cancel": active and module in {"video", "voice"}, "retry": retry, "output_media_id": job.get("output_media_id") or (job.get("output_media_ids") or [None])[0], "failure_reason": job.get("error")}


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

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown() -> None:
    client.close()
