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
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from auth import issue_token, require_owner, verify_credentials  # noqa: E402
from login_limiter import login_limiter  # noqa: E402
from models import (  # noqa: E402
    AiEditJob,
    GalleryItem,
    GenerationJob,
    GenerationRequest,
    IdentityPack,
    IdentityPackCreate,
    IdentityPackUpdate,
    LoginRequest,
    MediaAsset,
    TokenResponse,
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
from fastapi import Depends  # noqa: E402

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

ALLOWED_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
ALLOWED_VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm", "video/x-msvideo"}
ALLOWED_AUDIO_MIMES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB (images / mask)
MAX_VIDEO_ASSET_BYTES = 500 * 1024 * 1024  # 500 MB (video / audio for editor)
MAX_PHOTOS_PER_PACK = 5

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
        "provider_active": os.environ.get("IMAGE_PROVIDER", "gemini"),
        "providers_available": available_providers(),
        "provider_statuses": statuses,
        "provider_routing": await provider_manager.health_summary(),
    }


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
