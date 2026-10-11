"""FastAPI routes for Gold Builder. All prefixed with /api by the parent app."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from .. import workspace
from ..engine.capabilities import report as capability_report
from ..engine.checkpoint import delete_job, list_jobs, load_job, ownership_diagnostics, persistence_status, save_job
from ..engine.exporter import export_engine_zip, export_zip
from ..engine.orchestrator import finalize_job, run_existing_repo_job, run_job
from ..engine.lifecycle import begin_new_run, transition
from ..guardian import Guardian
from ..guardian.events import guardian_event
from ..guardian.policy import (
    ACTIVE_STATUSES as GUARDIAN_ACTIVE_STATUSES,
    heartbeat_age_seconds as guardian_heartbeat_age,
    is_stale as guardian_is_stale,
    stale_threshold_seconds as guardian_stale_threshold,
)
from ..guardian.provider_gate import provider_snapshot as guardian_provider_snapshot
from ..engine.media import generate_media
from ..engine.preview import manager as preview_manager
from ..engine.quality_gates import evaluate
from ..engine.review import review_verdict
from ..engine.snapshots import list_snapshots as list_snap
from ..engine.snapshots import restore as restore_snap
from ..engine.stacks import get_stack, list_stacks
from ..engine.usage import tracker
from ..engine.verifier import verify_url as verifier_verify_url
from ..models import (
    AttachmentInfo,
    Capability,
    CreateExistingRepoJobRequest,
    CreateJobRequest,
    Job,
    JobStatus,
    LogEvent,
    MediaImageRequest,
    MediaVideoRequest,
    PreviewInfo,
    ProviderInfo,
    QualityGates,
    Snapshot,
    StackInfo,
    UsageMetrics,
)
from ..providers.router import router as provider_router
from ..security import SecretDetectedError, UnsafePathError, safe_resolve


_ALLOWED_URL_SCHEMES = ("http://", "https://", "git://")
_URL_HOST_ALLOWLIST_ENV = "GB_ALLOWED_GIT_HOSTS"


def _validate_remote_source(source: str) -> None:
    if source.startswith("git@"):
        if os.environ.get("GB_ALLOW_SSH_SOURCE") != "1":
            raise HTTPException(400, "SSH source URLs are disabled")
        return
    if not source.startswith(_ALLOWED_URL_SCHEMES):
        raise HTTPException(400, "source must be an http(s)/git URL")
    host_allow = os.environ.get(_URL_HOST_ALLOWLIST_ENV, "").strip()
    if not host_allow:
        return
    allowed = [h.strip().lower() for h in host_allow.split(",") if h.strip()]
    m = re.match(r"^[a-z]+://([^/@]+@)?([^/:]+)", source, re.IGNORECASE)
    host = (m.group(2).lower() if m else "")
    if host not in allowed:
        raise HTTPException(400,
            f"git host {host!r} not on allowlist ({_URL_HOST_ALLOWLIST_ENV})")


def _validate_public_http_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(400, "production URL must be a valid http(s) URL")
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise HTTPException(400, "production URL must be publicly reachable")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise HTTPException(400, f"production host could not be resolved: {host}") from e
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise HTTPException(400, "production URL resolves to a private or reserved network")
    return url.strip()


def _normalize_repository_source(source: str) -> str:
    """Accept GitHub owner/repo shorthand from the UI as a safe HTTPS clone URL."""
    value = source.strip()
    if len(value) > 2048:
        raise HTTPException(400, "repository source is too long")

    def is_repo_segment(segment: str) -> bool:
        return bool(segment) and all(
            char.isascii() and (char.isalnum() or char in "_.-")
            for char in segment
        )

    parts = value.split("/")
    if len(parts) == 2 and all(is_repo_segment(part) for part in parts):
        return f"https://github.com/{value}.git"

    try:
        parsed = urlparse(value)
        is_github_https = (
            parsed.scheme.lower() == "https"
            and parsed.hostname == "github.com"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        is_github_https = False
        parsed = None
    if is_github_https and parsed is not None:
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) == 2:
            owner, repository = path_parts
            if repository.endswith(".git"):
                repository = repository[:-4]
            if is_repo_segment(owner) and is_repo_segment(repository):
                return f"https://github.com/{owner}/{repository}.git"
    return value


def _validate_source_for_remote_caller(source: str) -> None:
    if source.startswith(_ALLOWED_URL_SCHEMES + ("git@",)):
        _validate_remote_source(source)
        return
    if os.environ.get("GB_ALLOW_LOCAL_SOURCE") != "1":
        raise HTTPException(400,
            "local filesystem sources are disabled on the public API. "
            "Set GB_ALLOW_LOCAL_SOURCE=1 in the engine environment (and "
            "optionally GB_LOCAL_SOURCE_ROOT) to enable, or use a git URL.")
    root = Path(os.environ.get("GB_LOCAL_SOURCE_ROOT",
                               str(workspace.workspace_root()))).resolve()
    source_path = Path(source).expanduser()
    try:
        relative_source = (
            source_path.relative_to(root) if source_path.is_absolute()
            else source_path
        )
        src = safe_resolve(root, str(relative_source))
    except (ValueError, UnsafePathError) as e:
        raise HTTPException(400,
            f"local source must live under {root} (see GB_LOCAL_SOURCE_ROOT)") from e
    if not src.exists() or not src.is_dir():
        raise HTTPException(400, f"source directory not found: {source}")


_ACTIVE_JOB_STATUSES = {
    JobStatus.PENDING, JobStatus.UNDERSTANDING, JobStatus.INSPECTING,
    JobStatus.PLANNING, JobStatus.GENERATING, JobStatus.MEDIA,
    JobStatus.INSTALLING, JobStatus.BUILDING, JobStatus.TYPECHECKING,
    JobStatus.LINTING, JobStatus.TESTING, JobStatus.STARTING,
    JobStatus.VERIFYING, JobStatus.DIAGNOSING, JobStatus.REPAIRING,
    JobStatus.RECOVERING,
    JobStatus.SELF_REVIEWING, JobStatus.INDEPENDENT_REVIEW,
    JobStatus.REVIEW_REPAIR, JobStatus.FINAL_VERIFYING,
}
_PREVIEW_BLOCKED_STATUSES = set(_ACTIVE_JOB_STATUSES) | {JobStatus.PAUSED}
_TERMINAL_JOB_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
_STALE_JOB_SECONDS = max(90, int(os.environ.get("GB_STALE_JOB_SECONDS", "240")))

# Process-wide Guardian instance, created by make_router and reused by the
# server startup scan.
_GUARDIAN: Optional[Guardian] = None


def get_guardian() -> Optional[Guardian]:
    return _GUARDIAN


def _job_age_seconds(job: Job) -> float:
    try:
        updated = datetime.fromisoformat(str(job.updated_at).replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())
    except Exception:
        return 0.0


async def _fail_stale_job_if_needed(job: Job, db: AsyncIOMotorDatabase) -> Job:
    if job.status not in _ACTIVE_JOB_STATUSES:
        return job
    age = _job_age_seconds(job)
    if age <= _STALE_JOB_SECONDS:
        return job
    previous = job.status.value
    transition(job, JobStatus.FAILED, context="routes:stale_watchdog")
    job.error = (
        f"Job interrupted while {previous}: no worker heartbeat for "
        f"{int(age)} seconds. The worker may have restarted or been replaced. "
        "Start a new run; no push was performed unless a verified push was already recorded."
    )
    job.logs.append(LogEvent(
        phase="watchdog",
        level="error",
        message=job.error,
        data={"previous_status": previous, "stale_seconds": int(age)},
    ))
    guardian_event(
        job, "stale_marked_failed", phase=previous,
        message=job.error,
        data={"previous_status": previous, "stale_seconds": int(age)},
    )
    job.updated_at = datetime.now(timezone.utc).isoformat()
    await save_job(db, job)
    return job


async def _heartbeat(job: Job, db: AsyncIOMotorDatabase, stop: asyncio.Event,
                     guardian: Optional[Guardian] = None) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=15.0)
            return
        except asyncio.TimeoutError:
            pass
        if job.status not in _ACTIVE_JOB_STATUSES:
            return
        if guardian is not None:
            guardian.record_heartbeat(job)
        else:
            job.updated_at = datetime.now(timezone.utc).isoformat()
        await save_job(db, job)

def _ensure_preview_lifecycle_ready(job: Job) -> None:
    if job.status in _PREVIEW_BLOCKED_STATUSES:
        raise HTTPException(
            409,
            f"Preview is not available yet. The job is still {job.status.value}. "
            "It will become available after the application reaches a runnable state.",
        )

_PROXY_SHIM = """<script>(function(){var B=%s;function fix(u){return (typeof u==='string'&&u.charAt(0)==='/'&&u.charAt(1)!=='/'&&u.indexOf(B+'/')!==0)?B+u:u;}
var f=window.fetch;window.fetch=function(i,o){return f.call(this,typeof i==='string'?fix(i):i,o);};
var x=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(m,u){arguments[1]=fix(u);return x.apply(this,arguments);};})();</script>"""


def _inject_proxy_shim(content: bytes, base: str) -> bytes:
    """Route root-relative fetch/XHR of generated apps through the preview proxy."""
    shim = (_PROXY_SHIM % json.dumps(base)).encode("utf-8")
    lower = content.lower()
    at = lower.find(b"<head>")
    if at == -1:
        return shim + content
    at += len(b"<head>")
    return content[:at] + shim + content[at:]


def make_router(db: AsyncIOMotorDatabase) -> APIRouter:
    global _GUARDIAN
    r = APIRouter(prefix="/gb")
    job_mutation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    _GUARDIAN = Guardian(db)

    def _job_mutation_lock(job_id: str) -> asyncio.Lock:
        lock = job_mutation_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            job_mutation_locks[job_id] = lock
        return lock

    @r.get("/health")
    async def health():
        return {
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "commit": os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT") or "",
            "persistence": await persistence_status(),
        }

    @r.get("/github/repositories")
    async def github_repositories():
        """List repositories visible to the configured GitHub token without exposing it."""
        token = (os.environ.get("GB_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
        if not token:
            raise HTTPException(503, "GitHub repository access is not configured")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        repos = []
        page = 1
        # The picker is the owner's control center: enumerate every repository
        # owned by the authenticated GitHub account, including private repos.
        # Foreign repositories remain supported through the manual URL field.
        async with httpx.AsyncClient(timeout=20.0) as client:
            me = await client.get("https://api.github.com/user", headers=headers)
            if me.status_code != 200:
                raise HTTPException(502, f"GitHub account lookup failed (HTTP {me.status_code})")
            owner_login = str(me.json().get("login") or "").strip()
            if not owner_login:
                raise HTTPException(502, "GitHub account lookup returned no login")
            while page <= 10:
                response = await client.get(
                    "https://api.github.com/user/repos",
                    headers=headers,
                    params={"per_page": 100, "page": page, "sort": "updated", "affiliation": "owner"},
                )
                if response.status_code != 200:
                    raise HTTPException(502, f"GitHub repository listing failed (HTTP {response.status_code})")
                batch = response.json()
                for item in batch:
                    if str((item.get("owner") or {}).get("login") or "").lower() != owner_login.lower():
                        continue
                    repos.append({
                        "full_name": item.get("full_name"),
                        "name": item.get("name"),
                        "private": bool(item.get("private")),
                        "default_branch": item.get("default_branch") or "main",
                        "clone_url": item.get("clone_url"),
                        "html_url": item.get("html_url"),
                        "updated_at": item.get("updated_at"),
                    })
                if len(batch) < 100:
                    break
                page += 1
        repos.sort(key=lambda item: (item.get("full_name") or "").lower())
        return {"owner": owner_login, "repositories": repos}

    @r.get("/providers", response_model=list[ProviderInfo])
    async def providers():
        infos: list[ProviderInfo] = []
        for p in provider_router.list_llm():
            health = provider_router.provider_status(p)
            infos.append(ProviderInfo(
                id=p.id, label=f"{p.provider} / {p.model}",
                kind="llm", provider=p.provider, model=p.model,
                available=health["status"] in {"AVAILABLE", "DEGRADED"},
                status=health["status"],
                cooldown_remaining_s=health["cooldown_remaining_s"],
                capabilities=health["capabilities"],
                last_failure=health["last_failure"],
            ))
        for ip in provider_router.list_image():
            health = provider_router.provider_status(ip)
            infos.append(ProviderInfo(
                id=ip.id,
                label=f"{getattr(ip, 'provider', 'image')} / {getattr(ip, 'model', ip.id)}",
                kind="image",
                provider=getattr(ip, "provider", "image"),
                model=getattr(ip, "model", ip.id),
                available=health["status"] in {"AVAILABLE", "DEGRADED"},
                status=health["status"],
                cooldown_remaining_s=health["cooldown_remaining_s"],
                capabilities=health["capabilities"],
                last_failure=health["last_failure"],
            ))
        for vp in provider_router.list_video():
            health = provider_router.provider_status(vp)
            infos.append(ProviderInfo(
                id=vp.id,
                label=f"{getattr(vp, 'provider', 'video')} / {getattr(vp, 'model', vp.id)}",
                kind="video",
                provider=getattr(vp, "provider", "video"),
                model=getattr(vp, "model", vp.id),
                available=health["status"] in {"AVAILABLE", "DEGRADED"},
                status=health["status"],
                cooldown_remaining_s=health["cooldown_remaining_s"],
                capabilities=health["capabilities"],
                last_failure=health["last_failure"],
            ))
        return infos

    @r.get("/media/capabilities")
    async def media_capabilities():
        return provider_router.media_capabilities()

    async def _run_direct_media(job_id: str, image_specs=None, video_specs=None):
        async with _job_mutation_lock(job_id):
            job = await load_job(db, job_id)
            if not job:
                raise HTTPException(404, "job not found")
            if job.status not in {JobStatus.COMPLETED, JobStatus.FAILED}:
                raise HTTPException(
                    409,
                    f"direct media generation requires a terminal job; current status is {job.status.value}",
                )
            project = workspace.project_dir(job_id)
            try:
                files, assets = await generate_media(
                    project,
                    image_specs=image_specs or [],
                    video_specs=video_specs or [],
                )
            except (ValueError, FileNotFoundError, UnsafePathError) as exc:
                raise HTTPException(400, str(exc)) from exc
            except Exception as exc:  # provider failures are safe/sanitized upstream
                raise HTTPException(503, str(exc)) from exc
            latest = await load_job(db, job_id)
            if not latest:
                raise HTTPException(404, "job not found")
            latest.files.extend(files)
            latest.media_assets.extend(assets)
            await save_job(db, latest)
            return {"assets": [asset.model_dump() for asset in assets]}

    @r.post("/jobs/{job_id}/media/image/generate")
    async def media_image_generate(job_id: str, req: MediaImageRequest):
        payload = req.model_dump()
        payload["path"] = payload.pop("output_path")
        payload["operation"] = "generate"
        return await _run_direct_media(job_id, image_specs=[payload])

    @r.post("/jobs/{job_id}/media/image/edit")
    async def media_image_edit(job_id: str, req: MediaImageRequest):
        payload = req.model_dump()
        payload["path"] = payload.pop("output_path")
        payload["operation"] = "edit"
        return await _run_direct_media(job_id, image_specs=[payload])

    @r.post("/jobs/{job_id}/media/video/generate")
    async def media_video_generate(job_id: str, req: MediaVideoRequest):
        payload = req.model_dump()
        payload["path"] = payload.pop("output_path")
        if payload.get("operation") not in {"generate", "animate", "text_image"}:
            payload["operation"] = "generate"
        return await _run_direct_media(job_id, video_specs=[payload])

    @r.post("/jobs/{job_id}/media/video/transform")
    async def media_video_transform(job_id: str, req: MediaVideoRequest):
        payload = req.model_dump()
        payload["path"] = payload.pop("output_path")
        payload["operation"] = "transform"
        return await _run_direct_media(job_id, video_specs=[payload])

    @r.get("/jobs/{job_id}/media/{asset_id}")
    async def media_asset(job_id: str, asset_id: str):
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        asset = next((a for a in job.media_assets if a.id == asset_id), None)
        if not asset:
            raise HTTPException(404, "media asset not found")
        try:
            path = workspace.resolve_within(workspace.project_dir(job_id), asset.path)
        except UnsafePathError as exc:
            raise HTTPException(400, f"unsafe path: {exc}") from exc
        if not path.is_file():
            raise HTTPException(404, "media file not found")
        return FileResponse(str(path), media_type=asset.mime, filename=path.name)

    @r.get("/stacks", response_model=list[StackInfo])
    async def stacks():
        return [StackInfo(id=s.id, label=s.label) for s in list_stacks()]

    @r.get("/capabilities", response_model=list[Capability])
    async def capabilities():
        return capability_report()

    @r.post("/jobs/draft", response_model=Job)
    async def create_job_draft(req: CreateJobRequest):
        from ..models import Job as JobModel
        job = JobModel(
            request=req.request,
            max_repair_attempts=req.max_repair_attempts,
            budget=req.budget,
            strict_review=bool(req.strict_review),
            require_independent_review=bool(req.require_independent_review),
            max_self_review_repairs=req.max_self_review_repairs,
            max_independent_review_repairs=req.max_independent_review_repairs,
            provider_config={
                "llm_provider": req.llm_provider,
                "llm_model": req.llm_model,
                "stack_id": req.stack_id,
                "with_media": req.with_media,
                "quality_gates": req.quality_gates.model_dump() if req.quality_gates else None,
                "strict_review": req.strict_review,
                "require_independent_review": req.require_independent_review,
            },
        )
        await save_job(db, job)
        return job

    @r.post("/jobs/existing/draft", response_model=Job)
    async def create_existing_job_draft(req: CreateExistingRepoJobRequest):
        source = _normalize_repository_source(req.source)
        _validate_source_for_remote_caller(source)
        from ..models import Job as JobModel
        job = JobModel(
            request=req.request,
            mode="existing-repo",
            source=source,
            max_repair_attempts=req.max_repair_attempts,
            budget=req.budget,
            strict_review=bool(req.strict_review),
            require_independent_review=bool(req.require_independent_review),
            max_self_review_repairs=req.max_self_review_repairs,
            max_independent_review_repairs=req.max_independent_review_repairs,
            provider_config={
                "llm_provider": req.llm_provider,
                "quality_gates": req.quality_gates.model_dump() if req.quality_gates else None,
                "push_changes": req.push_changes,
                "strict_review": req.strict_review,
                "require_independent_review": req.require_independent_review,
            },
        )
        await save_job(db, job)
        return job

    @r.post("/jobs/{job_id}/attachments")
    async def upload_attachments(job_id: str, files: list[UploadFile] = File(...)):
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        if len(files) > 12:
            raise HTTPException(400, "maximum 12 files per upload")
        root = workspace.job_dir(job_id) / "inputs"
        root.mkdir(parents=True, exist_ok=True)
        total = 0
        uploaded = []
        for item in files:
            raw_name = Path(item.filename or "file").name
            safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", raw_name).strip(" .") or "file"
            data = await item.read()
            total += len(data)
            if not data or len(data) > 200 * 1024 * 1024 or total > 250 * 1024 * 1024:
                raise HTTPException(413, "attachment limit exceeded (200 MB/file, 250 MB/request)")
            target = root / safe_name
            stem, suffix = target.stem, target.suffix
            n = 2
            while target.exists():
                target = root / f"{stem}-{n}{suffix}"
                n += 1
            target.write_bytes(data)
            info = AttachmentInfo(
                name=target.name,
                path=f"inputs/{target.name}",
                mime=(item.content_type or "application/octet-stream"),
                size_bytes=len(data),
            )
            job.attachments.append(info)
            if job.status in _TERMINAL_JOB_STATUSES:
                workspace.safe_write(
                    workspace.project_dir(job_id), info.path, data, binary=True
                )
            uploaded.append(info.model_dump())
        await save_job(db, job)
        return {"attachments": uploaded}

    @r.post("/jobs/{job_id}/start", response_model=Job)
    async def start_draft_job(job_id: str, background: BackgroundTasks):
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        if job.status != JobStatus.PENDING:
            raise HTTPException(409, f"job cannot start from status {job.status.value}")

        if job.attachments:
            context_lines = ["Attached input files:"]
            text_budget = 50000
            root = workspace.job_dir(job.id)
            for attachment in job.attachments:
                context_lines.append(f"- {attachment.path} ({attachment.mime}, {attachment.size_bytes} bytes)")
                if text_budget > 0 and (
                    attachment.mime.startswith("text/")
                    or attachment.name.lower().endswith((".md", ".txt", ".json", ".csv", ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css"))
                ):
                    try:
                        text_value = workspace.resolve_within(root, attachment.path).read_text(
                            encoding="utf-8", errors="replace"
                        )[:text_budget]
                        if text_value:
                            context_lines.append(f"Content of {attachment.name}:\n{text_value}")
                            text_budget -= len(text_value)
                    except OSError:
                        pass
            job.request = job.request.rstrip() + "\n\n" + "\n".join(context_lines)
            await save_job(db, job)

        cfg = job.provider_config or {}
        gates_data = cfg.get("quality_gates")
        gates = QualityGates(**gates_data) if gates_data else None
        if job.budget:
            tracker.set_budget(job.id, job.budget)
        if job.mode == "existing-repo":
            if not job.source:
                raise HTTPException(400, "existing-repo draft has no source")
            background.add_task(
                _run_existing_and_swallow, job, db, job.source,
                cfg.get("llm_provider"), gates, bool(cfg.get("push_changes")),
            )
        else:
            background.add_task(
                _run_and_swallow, job, db, cfg.get("llm_provider"),
                cfg.get("stack_id"), bool(cfg.get("with_media", True)), gates,
            )
        return job

    @r.post("/jobs", response_model=Job)
    async def create_job(req: CreateJobRequest, background: BackgroundTasks):
        from ..models import Job as JobModel
        job = JobModel(
            request=req.request,
            max_repair_attempts=req.max_repair_attempts,
            budget=req.budget,
            strict_review=bool(req.strict_review),
            require_independent_review=bool(req.require_independent_review),
            max_self_review_repairs=req.max_self_review_repairs,
            max_independent_review_repairs=req.max_independent_review_repairs,
            provider_config={
                "llm_provider": req.llm_provider,
                "llm_model": req.llm_model,
                "stack_id": req.stack_id,
                "with_media": req.with_media,
                "quality_gates": req.quality_gates.model_dump() if req.quality_gates else None,
                "strict_review": req.strict_review,
                "require_independent_review": req.require_independent_review,
            },
        )
        if req.budget:
            tracker.set_budget(job.id, req.budget)
        await save_job(db, job)
        background.add_task(_run_and_swallow, job, db, req.llm_provider,
                            req.stack_id, req.with_media,
                            req.quality_gates)
        return job

    @r.post("/jobs/existing", response_model=Job)
    async def create_existing_repo_job(
        req: CreateExistingRepoJobRequest, background: BackgroundTasks,
    ):
        _validate_source_for_remote_caller(req.source)
        from ..models import Job as JobModel
        job = JobModel(
            request=req.request,
            mode="existing-repo",
            source=req.source,
            max_repair_attempts=req.max_repair_attempts,
            budget=req.budget,
            strict_review=bool(req.strict_review),
            require_independent_review=bool(req.require_independent_review),
            max_self_review_repairs=req.max_self_review_repairs,
            max_independent_review_repairs=req.max_independent_review_repairs,
            provider_config={
                "llm_provider": req.llm_provider,
                "quality_gates": req.quality_gates.model_dump() if req.quality_gates else None,
                "push_changes": req.push_changes,
                "strict_review": req.strict_review,
                "require_independent_review": req.require_independent_review,
            },
        )
        if req.budget:
            tracker.set_budget(job.id, req.budget)
        await save_job(db, job)
        background.add_task(_run_existing_and_swallow, job, db,
                            req.source, req.llm_provider, req.quality_gates, req.push_changes)
        return job

    @r.get("/jobs", response_model=list[Job])
    async def list_all(limit: int = Query(50, le=200)):
        return await list_jobs(db, limit=limit)

    @r.get("/jobs/{job_id}", response_model=Job)
    async def get_one(job_id: str):
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job = await _fail_stale_job_if_needed(job, db)
        # attach live usage and preview info to the response
        job.usage = tracker.get(job_id)
        job.preview = preview_manager.status(job_id) or job.preview
        return job

    @r.delete("/jobs/{job_id}")
    async def delete_one(job_id: str):
        await preview_manager.stop(job_id)
        tracker.clear(job_id)
        await delete_job(db, job_id)
        workspace.cleanup(job_id)
        return {"deleted": job_id}

    @r.get("/jobs/{job_id}/review")
    async def get_review(job_id: str):
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return {
            "job_id": job.id,
            "status": job.status.value,
            "strict_review": job.strict_review,
            "require_independent_review": job.require_independent_review,
            "verdict": review_verdict(job),
            "evidence": job.review.model_dump() if job.review else None,
        }

    @r.get("/jobs/{job_id}/usage", response_model=UsageMetrics)
    async def get_usage(job_id: str):
        return tracker.get(job_id)

    @r.get("/jobs/{job_id}/download")
    async def download_project(job_id: str):
        job = await load_job(db, job_id)
        if not job or not job.plan:
            raise HTTPException(404, "job not found or has no plan")
        zip_path = workspace.artifacts_dir(job_id) / f"{job.plan.app_name}.zip"
        if not zip_path.exists():
            try:
                export_zip(workspace.project_dir(job_id), zip_path)
            except SecretDetectedError as e:
                raise HTTPException(409, str(e))
        return FileResponse(str(zip_path), media_type="application/zip",
                            filename=f"{job.plan.app_name}.zip")

    @r.get("/jobs/{job_id}/file")
    async def get_file(job_id: str, path: str):
        try:
            resolved = workspace.resolve_within(
                workspace.project_dir(job_id), path,
            )
        except UnsafePathError as e:
            raise HTTPException(400, f"unsafe path: {e}") from e

        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "job not found")

        if resolved.exists() and resolved.is_file():
            try:
                return {"path": path, "content": resolved.read_text(encoding="utf-8")}
            except UnicodeDecodeError:
                return {"path": path, "content": "<binary>"}
        for f in job.files:
            if f.path == path:
                return {"path": f.path, "content": f.content}
        raise HTTPException(404, f"file not found: {path}")

    @r.get("/jobs/{job_id}/screenshot")
    async def get_screenshot(job_id: str):
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        artifacts = workspace.artifacts_dir(job_id).resolve()
        candidates = []
        if job.verification and job.verification.screenshot_path:
            candidates.append(Path(job.verification.screenshot_path))
        candidates.extend([
            artifacts / "verification.png",
            artifacts / "screenshot.png",
        ])
        for candidate in candidates:
            try:
                p = candidate.resolve()
                p.relative_to(artifacts)
            except (OSError, ValueError):
                continue
            if p.exists() and p.is_file():
                return FileResponse(str(p), media_type="image/png")
        raise HTTPException(404, "screenshot not available")

    @r.post("/jobs/{job_id}/verify")
    async def reverify(job_id: str, url: Optional[str] = None,
                       selectors: Optional[str] = None):
        async with _job_mutation_lock(job_id):
            job = await load_job(db, job_id)
            if not job or not job.plan:
                raise HTTPException(404, "job not found or has no plan")
            if job.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(409, f"job is still active: {job.status.value}")

            stack = get_stack(job.plan.stack_id)
            info = preview_manager.status(job_id)
            if info is None:
                info = await preview_manager.start(job_id, stack)
                job.preview = info

            target_url = url or info.internal_url
            if not target_url:
                raise HTTPException(503, "preview did not expose a verification URL")

            sel = [s.strip() for s in (selectors or "").split(",") if s.strip()]
            scenario = [s.model_dump() for s in job.plan.verification_scenario]
            artifacts = workspace.artifacts_dir(job_id)
            result = await verifier_verify_url(
                target_url,
                artifacts,
                click_selectors=sel,
                scenario=scenario or None,
                project_dir=workspace.project_dir(job_id),
                plan=job.plan,
                app_requirements=job.request,
            )
            job.verification = result
            job.gates = evaluate(
                job.build_evidence,
                result,
                job.plan.quality_gates,
                stack=stack,
                startup_ok=True,
            )
            # Single completion authority. A passing re-verification may never
            # resurrect a job whose review layer left unresolved blocking
            # findings; legacy jobs without review keep the pre-review behaviour.
            await finalize_job(
                job, db,
                requires_review=job.review is not None,
            )
            await save_job(db, job)
            return {
                "verification": result,
                "gates": job.gates,
                "status": job.status,
                "error": job.error,
            }

    @r.post("/jobs/{job_id}/production/verify")
    async def verify_production(job_id: str, payload: dict):
        job = await load_job(db, job_id)
        if not job or not job.plan:
            raise HTTPException(404, "job not found or has no plan")
        target_url = _validate_public_http_url(str(payload.get("url", "")).strip())
        scenario = [s.model_dump() for s in job.plan.verification_scenario]
        result = await verifier_verify_url(
            target_url,
            workspace.artifacts_dir(job_id) / "production",
            scenario=scenario or None,
            plan=job.plan,
            app_requirements=job.request,
            restrict_public_network=True,
        )
        job.production_url = target_url
        job.production_verification = result
        job.production_verified_at = datetime.now(timezone.utc).isoformat()
        await save_job(db, job)
        return {
            "url": target_url,
            "verification": result,
            "verified_at": job.production_verified_at,
        }

    # ---- preview lifecycle ----
    @r.post("/jobs/{job_id}/preview/start", response_model=PreviewInfo)
    async def preview_start(job_id: str):
        job = await load_job(db, job_id)
        if not job or not job.plan:
            raise HTTPException(404, "job not found or has no plan")
        _ensure_preview_lifecycle_ready(job)
        stack = get_stack(job.plan.stack_id)
        info = await preview_manager.start(job_id, stack)
        job.preview = info
        await save_job(db, job)
        return info

    @r.post("/jobs/{job_id}/preview/restart", response_model=PreviewInfo)
    async def preview_restart(job_id: str):
        job = await load_job(db, job_id)
        if not job or not job.plan:
            raise HTTPException(404, "job not found or has no plan")
        _ensure_preview_lifecycle_ready(job)
        info = await preview_manager.restart(job_id)
        if info is None:
            info = await preview_manager.start(job_id, get_stack(job.plan.stack_id))
        job = await load_job(db, job_id)
        if job:
            job.preview = info
            await save_job(db, job)
        return info

    @r.post("/jobs/{job_id}/preview/stop", response_model=PreviewInfo)
    async def preview_stop(job_id: str):
        info = await preview_manager.stop(job_id)
        if info is None:
            info = PreviewInfo(job_id=job_id, running=False)
        job = await load_job(db, job_id)
        if job:
            job.preview = info
            await save_job(db, job)
        return info

    @r.get("/jobs/{job_id}/preview", response_model=PreviewInfo)
    async def preview_status(job_id: str):
        info = preview_manager.status(job_id)
        if info is None:
            return PreviewInfo(job_id=job_id, running=False)
        return info

    # Reverse proxy to the running preview (localhost:PORT)
    @r.api_route("/jobs/{job_id}/proxy/{path:path}",
                 methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def proxy(job_id: str, path: str, request: Request):
        port = preview_manager.port(job_id)
        if not port:
            raise HTTPException(503, "preview not running for this job")
        target = f"http://127.0.0.1:{port}/{path}"
        if request.url.query:
            target += f"?{request.url.query}"
        body = await request.body()
        # Never forward host credentials (Lumina JWT / session cookie) to generated code.
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in {"host", "content-length", "authorization", "cookie"}}
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as c:
                resp = await c.request(request.method, target,
                                       headers=headers, content=body)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"upstream error: {e}") from e
        # Filter hop-by-hop headers
        drop = {"content-encoding", "transfer-encoding", "connection",
                "keep-alive", "content-length"}
        out_headers = {k: v for k, v in resp.headers.items()
                       if k.lower() not in drop}
        content = resp.content
        if "text/html" in (resp.headers.get("content-type") or ""):
            content = _inject_proxy_shim(content, f"/api/gb/jobs/{job_id}/proxy")
        return Response(content=content, status_code=resp.status_code,
                        headers=out_headers, media_type=resp.headers.get("content-type"))

    # ---- snapshots ----
    @r.get("/jobs/{job_id}/snapshots", response_model=list[Snapshot])
    async def snapshots(job_id: str):
        return list_snap(job_id)

    @r.post("/jobs/{job_id}/snapshots/{snapshot_id}/restore",
            response_model=Snapshot)
    async def snapshot_restore(job_id: str, snapshot_id: str):
        try:
            snap = restore_snap(job_id, snapshot_id)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        job = await load_job(db, job_id)
        if job:
            job.snapshots.append(snap)
            await save_job(db, job)
        return snap

    @r.get("/jobs/{job_id}/stream")
    async def stream_events(job_id: str):
        async def gen():
            last_len = 0
            last_status: Optional[str] = None
            while True:
                job = await load_job(db, job_id)
                if not job:
                    yield f"event: error\ndata: {json.dumps({'error':'not found'})}\n\n"
                    return
                job = await _fail_stale_job_if_needed(job, db)
                new_logs = job.logs[last_len:]
                for ev in new_logs:
                    payload = {"phase": ev.phase, "level": ev.level,
                               "message": ev.message, "ts": ev.ts,
                               "data": ev.data}
                    yield f"event: log\ndata: {json.dumps(payload)}\n\n"
                last_len = len(job.logs)
                status_payload = {"status": job.status.value, "progress": job.progress,
                                  "gates": [g.model_dump() for g in job.gates]}
                if job.review is not None:
                    status_payload["review"] = {
                        "strict": job.review.strict,
                        "required": job.review.required,
                        "self_review_status": job.review.self_review_status,
                        "independent_review_status": job.review.independent_review_status,
                        "reviewer_provider": job.review.reviewer_provider,
                        "review_attempt_count": job.review.review_attempt_count,
                        "repair_attempt_count": job.review.repair_attempt_count,
                        "unresolved_blockers": len(job.review.unresolved_blockers),
                        "independent_review_unavailable": job.review.independent_review_unavailable,
                        "verdict": review_verdict(job),
                    }
                if json.dumps(status_payload) != last_status:
                    yield f"event: status\ndata: {json.dumps(status_payload)}\n\n"
                    last_status = json.dumps(status_payload)
                if job.status in _TERMINAL_JOB_STATUSES:
                    yield f"event: done\ndata: {json.dumps({'status': job.status.value})}\n\n"
                    return
                await asyncio.sleep(0.6)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @r.get("/engine-source")
    async def engine_source():
        out = workspace.workspace_root() / "gold-builder-engine.zip"
        if out.exists():
            try:
                out.unlink()
            except OSError:
                pass
        engine_root = Path("/app")
        try:
            export_engine_zip(engine_root, out)
        except SecretDetectedError as e:
            raise HTTPException(409, str(e))
        return FileResponse(str(out), media_type="application/zip",
                            filename="gold-builder-engine.zip")

    
    @r.post("/jobs/{job_id}/iterate")
    async def iterate_existing_job(job_id: str, payload: dict, bg: BackgroundTasks):
        continuation_req = payload.get("request", "").strip()
        if not continuation_req:
            raise HTTPException(400, "Continuation request cannot be empty")
        async with _job_mutation_lock(job_id):
            job = await load_job(db, job_id)
            if not job:
                raise HTTPException(404, "Job not found")
            if job.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(409, f"job is already active: {job.status.value}")
            begin_new_run(job, JobStatus.PLANNING, context="routes:iterate")
            job.updated_at = datetime.now(timezone.utc).isoformat()
            await save_job(db, job)
            from ..engine.orchestrator import iterate_job
            bg.add_task(iterate_job, job, continuation_req, db)
            return {"ok": True, "job_id": job.id, "status": "iterating"}

    @r.post("/jobs/{job_id}/rollback")
    async def rollback_job(job_id: str, payload: dict):
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        checkpoint_id = payload.get("checkpoint_id")
        from ..engine.snapshots import restore as restore_snap, list_snapshots
        if not checkpoint_id:
            snaps = list_snapshots(job_id)
            if not snaps:
                raise HTTPException(400, "No checkpoints available to rollback")
            checkpoint_id = snaps[-1].id
        try:
            restored = restore_snap(job_id, checkpoint_id)
            return {"ok": True, "restored_checkpoint": restored.id}
        except Exception as e:
            raise HTTPException(400, f"Rollback failed: {e}")

    @r.get("/jobs/{job_id}/history")
    async def get_job_history(job_id: str):
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        from ..engine.snapshots import list_snapshots
        return {
            "version_history": [v.model_dump() for v in getattr(job, "version_history", [])],
            "checkpoints": [s.model_dump() for s in list_snapshots(job_id)],
        }

    @r.get("/jobs/{job_id}/guardian")
    async def get_job_guardian(job_id: str):
        """Secret-free Guardian state: execution phase, recovery history, events."""
        job = await load_job(db, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        phase = job.active_phase or (job.status.value if isinstance(job.status, JobStatus) else str(job.status))
        return {
            "job_id": job.id,
            "status": job.status.value if isinstance(job.status, JobStatus) else str(job.status),
            "execution_generation": job.execution_generation,
            "recovery_attempts": job.recovery_attempts,
            "max_recovery_attempts": job.max_recovery_attempts,
            "last_recovery_reason": job.last_recovery_reason,
            "recovery_source": job.recovery_source,
            "recovered_at": job.recovered_at,
            "provider_paused": job.provider_paused,
            "paused_from_status": job.paused_from_status,
            "last_checkpoint_snapshot": job.last_checkpoint_snapshot,
            "active_phase": phase,
            "active_phase_started_at": job.active_phase_started_at,
            "heartbeat_at": job.heartbeat_at,
            "heartbeat_age_s": round(guardian_heartbeat_age(job), 3),
            "stale": guardian_is_stale(job),
            "stale_threshold_s": int(guardian_stale_threshold(phase)),
            "runner_active": get_guardian().runner_for(job_id) is not None if get_guardian() else False,
            "recovery_history": [rec.model_dump() for rec in job.recovery_history],
            "events": [e.model_dump() for e in job.guardian_events],
        }

    @r.get("/guardian")
    async def guardian_status():
        """Process-level Guardian dashboard: unfinished jobs and provider state."""
        g = get_guardian()
        jobs = await list_jobs(db, limit=200)
        active = [j for j in jobs if j.status in GUARDIAN_ACTIVE_STATUSES]
        paused = [j for j in jobs if j.status == JobStatus.PAUSED]
        ownership = ownership_diagnostics()
        return {
            "enabled": g is not None,
            "ownership": {
                **ownership,
                "guardian_authority": g.ownership_mode if g is not None else None,
            },
            "active_jobs": [
                {
                    "job_id": j.id,
                    "status": j.status.value if isinstance(j.status, JobStatus) else str(j.status),
                    "active_phase": j.active_phase,
                    "heartbeat_age_s": round(guardian_heartbeat_age(j), 3),
                    "stale": guardian_is_stale(j),
                    "recovery_attempts": j.recovery_attempts,
                    "generation": j.execution_generation,
                }
                for j in active
            ],
            "paused_jobs": [
                {
                    "job_id": j.id,
                    "paused_from_status": j.paused_from_status,
                    "recovery_attempts": j.recovery_attempts,
                }
                for j in paused
            ],
            "providers": guardian_provider_snapshot(),
        }

    @r.post("/jobs/{job_id}/guardian/recover")
    async def guardian_recover(job_id: str, payload: dict | None = None):
        """Manually trigger deterministic Guardian recovery for a job."""
        g = get_guardian()
        if g is None:
            raise HTTPException(503, "Guardian is not available")
        async with _job_mutation_lock(job_id):
            job = await load_job(db, job_id)
            if not job:
                raise HTTPException(404, "Job not found")
            if job.status in _TERMINAL_JOB_STATUSES:
                raise HTTPException(409, f"job is terminal: {job.status.value}")
            if job.status == JobStatus.PAUSED:
                raise HTTPException(409, "job is provider-paused; it will resume automatically")
            action = (payload or {}).get("action")
            ok = await g.recover_job(
                job, reason="manual", action=action,
                stale_phase=job.active_phase or "", source="manual",
            )
            return {"ok": ok, "job_id": job.id, "status": job.status.value,
                    "generation": job.execution_generation}

    @r.post("/jobs/{job_id}/guardian/pause")
    async def guardian_pause(job_id: str):
        g = get_guardian()
        if g is None:
            raise HTTPException(503, "Guardian is not available")
        async with _job_mutation_lock(job_id):
            job = await load_job(db, job_id)
            if not job:
                raise HTTPException(404, "Job not found")
            ok = await g.pause_job(job, reason="manual")
            if not ok:
                raise HTTPException(409, f"job cannot be paused from {job.status.value}")
            return {"ok": True, "job_id": job.id, "status": job.status.value}

    @r.post("/jobs/{job_id}/guardian/resume")
    async def guardian_resume(job_id: str, background: BackgroundTasks):
        g = get_guardian()
        if g is None:
            raise HTTPException(503, "Guardian is not available")
        async with _job_mutation_lock(job_id):
            job = await load_job(db, job_id)
            if not job:
                raise HTTPException(404, "Job not found")
            if job.status != JobStatus.PAUSED:
                raise HTTPException(409, f"job is not paused: {job.status.value}")
            job.provider_paused = False
            ok = await g.resume_paused_job(job)
            if not ok:
                # Manual resume proceeds even if provider state is unclear;
                # restore an active phase and launch under the heartbeat guard.
                target = job.paused_from_status or ""
                restored = None
                if target:
                    try:
                        candidate = JobStatus(target)
                        if candidate not in _TERMINAL_JOB_STATUSES and candidate != JobStatus.PAUSED:
                            restored = candidate
                    except ValueError:
                        restored = None
                begin_new_run(
                    job,
                    restored or (JobStatus.PLANNING if job.plan is None else JobStatus.GENERATING),
                    context="routes:manual_resume",
                )
                job.provider_paused = False
                job.paused_from_status = None
                job.error = None
                cfg, gates = g._provider_config(job)
                background.add_task(
                    _run_guardian_resume_swallow, job, db, cfg, gates,
                )
                return {"ok": True, "job_id": job.id, "status": job.status.value,
                        "provider_available": False}
            return {"ok": True, "job_id": job.id, "status": job.status.value,
                    "provider_available": True}

    return r


async def _run_guardian_resume_swallow(job, db, cfg, gates):
    from ..engine.orchestrator import resume_job as _resume

    async def runner():
        return await _resume(
            job, db,
            preferred_provider=(cfg or {}).get("llm_provider"),
            quality_gates=gates,
        )
    await _run_with_heartbeat(job, db, runner, guardian=get_guardian())


async def _run_with_heartbeat(job, db, runner, guardian=None):
    stop = asyncio.Event()
    if guardian is not None:
        guardian.begin_phase(job, job.status)
    heartbeat = asyncio.create_task(_heartbeat(job, db, stop, guardian))
    current = asyncio.current_task()
    if guardian is not None and current is not None:
        guardian.register_runner(job.id, current, job.execution_generation)
    try:
        return await runner()
    except asyncio.CancelledError:
        # Guardian-triggered cancellation: a replacement runner owns the job.
        raise
    except Exception as exc:  # noqa: BLE001
        transition(job, JobStatus.FAILED, context="routes:worker_failure")
        job.error = f"Worker failure: {type(exc).__name__}: {exc}"
        job.logs.append(LogEvent(
            phase="worker",
            level="error",
            message=job.error,
        ))
        job.updated_at = datetime.now(timezone.utc).isoformat()
        await save_job(db, job)
        return job
    finally:
        stop.set()
        heartbeat.cancel()
        try:
            await heartbeat
        except (asyncio.CancelledError, Exception):
            pass
        if guardian is not None and current is not None:
            guardian.unregister_runner(job.id, current)


async def _run_and_swallow(job, db, preferred, stack_id, with_media, gates):
    async def runner():
        return await run_job(
            job, db, preferred_provider=preferred,
            stack_id=stack_id, with_media=with_media,
            quality_gates=gates,
        )
    await _run_with_heartbeat(job, db, runner, guardian=get_guardian())


async def _run_existing_and_swallow(job, db, source, preferred, gates, push_changes=False):
    async def runner():
        return await run_existing_repo_job(
            job, db, source=source,
            preferred_provider=preferred,
            quality_gates=gates,
            push_changes=push_changes,
        )
    await _run_with_heartbeat(job, db, runner, guardian=get_guardian())
