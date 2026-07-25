"""Pydantic models for Lumina AI Desktop."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# ---------- Auth ----------
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str


# ---------- Media ----------
class MediaAsset(BaseModel):
    """A stored image file (either uploaded reference or AI-generated output)."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    filename: str
    mime_type: str = "image/png"
    kind: str = "reference"  # reference | generated | edited
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: int = 0
    parent_media_id: Optional[str] = None  # lineage: which media this was edited from
    edit_note: Optional[str] = None
    source_module: str = "image"
    project_id: Optional[str] = None
    job_id: Optional[str] = None
    identity_pack_id: Optional[str] = None
    voice_pack_id: Optional[str] = None
    provider: Optional[str] = None
    favorite: bool = False
    tags: List[str] = Field(default_factory=list)
    folder: str = ""
    collection_ids: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class WorkspaceNotification(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    type: str
    title: str
    message: str = ""
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    read: bool = False
    created_at: str = Field(default_factory=now_iso)


# ---------- Identity Packs ----------
class IdentityPackCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class IdentityPackUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    primary_photo_id: Optional[str] = None
    photo_ids: Optional[List[str]] = None


class IdentityPack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    description: str = ""
    photo_ids: List[str] = Field(default_factory=list)
    primary_photo_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ---------- Generation ----------
class GenerationRequest(BaseModel):
    identity_pack_id: Optional[str] = None
    prompt: str
    negative_prompt: Optional[str] = ""
    scene: Optional[str] = ""
    outfit: Optional[str] = ""
    aspect_ratio: str = "1:1"  # 9:16 | 16:9 | 1:1 | 4:5 | 3:2
    count: int = 1  # 1..4
    provider: Optional[str] = None  # defaults to env IMAGE_PROVIDER


class GenerationJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"  # queued | processing | completed | failed
    provider: str = "gemini"
    identity_pack_id: Optional[str] = None
    prompt: str = ""
    negative_prompt: str = ""
    scene: str = ""
    outfit: str = ""
    aspect_ratio: str = "1:1"
    count: int = 1
    output_media_ids: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    selected_provider: Optional[str] = None
    attempted_providers: List[str] = Field(default_factory=list)
    provider_failures: List[dict] = Field(default_factory=list)
    fallback_used: bool = False
    generation_duration_ms: Optional[int] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ---------- Gallery ----------
class GalleryItem(BaseModel):
    """A gallery-facing representation of a generated (or edited) media asset."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)  # gallery entry id
    owner_email: str
    media_id: str
    job_id: Optional[str] = None
    identity_pack_id: Optional[str] = None
    prompt: str = ""
    scene: str = ""
    outfit: str = ""
    aspect_ratio: str = "1:1"
    provider: str = "gemini"
    favorite: bool = False
    created_at: str = Field(default_factory=now_iso)


# ---------- Cross-module Projects ----------
class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class Project(BaseModel):
    """Owner-private workspace that can link work from every LUMINA module."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    description: str = ""
    media_ids: List[str] = Field(default_factory=list)
    job_ids: List[str] = Field(default_factory=list)
    identity_pack_ids: List[str] = Field(default_factory=list)
    notes: str = ""
    status: str = "active"  # active | paused | completed | archived
    tags: List[str] = Field(default_factory=list)
    cover_media_id: Optional[str] = None
    export_media_ids: List[str] = Field(default_factory=list)
    archived_at: Optional[str] = None
    activity: List[dict] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)



# ---------- AI Edit Jobs ----------
class AiEditJob(BaseModel):
    """A background AI edit job (Gemini edit) applied to an existing source media."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"  # queued | processing | completed | failed | canceled
    provider: str = "gemini"
    tool: str = "retouch"  # one of the AI tool keys (retouch, enhance, upscale, ...)
    source_media_id: str
    identity_pack_id: Optional[str] = None
    instruction: str = ""
    mask_media_id: Optional[str] = None  # if a mask was provided
    output_media_id: Optional[str] = None
    error: Optional[str] = None
    selected_provider: Optional[str] = None
    attempted_providers: List[str] = Field(default_factory=list)
    provider_failures: List[dict] = Field(default_factory=list)
    fallback_used: bool = False
    generation_duration_ms: Optional[int] = None
    retry_of: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)



# ---------- Video Projects ----------
class VideoProject(BaseModel):
    """Simple CapCut-style video project owned by the single owner."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str = "Untitled Video"
    aspect_ratio: str = "16:9"    # 9:16 | 16:9 | 1:1 | 4:5
    fps: int = 30                 # 24 | 25 | 30
    resolution: str = "1080p"     # 720p | 1080p
    # Freeform state blob managed by the frontend (clips, text overlays,
    # music, voice-over, adjustments). Kept as-is so the editor evolves
    # without schema migrations.
    state: dict = Field(default_factory=dict)
    exported_media_id: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ---------- Video Studio generation ----------
class VideoGenerationJob(BaseModel):
    """A provider-neutral image-to-video request and its private result."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"  # queued | preparing | uploading | processing | rendering | completed | failed | cancelled
    progress: int = 0
    estimated_seconds_remaining: Optional[int] = None
    provider: str = "mock"
    mode: str = "image-to-video"  # text-to-video | image-to-video | multi-image | extend | variation | interpolation | edit
    prompt: str = ""
    negative_prompt: str = ""
    duration_seconds: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    fps: int = 24
    quality: str = "standard"
    camera_motion: str = "auto"
    style: str = "cinematic"
    seed: Optional[int] = None
    source_media_id: Optional[str] = None
    source_media_ids: List[str] = Field(default_factory=list)
    source_job_id: Optional[str] = None
    output_media_id: Optional[str] = None
    output_mime_type: Optional[str] = None
    preview_kind: Optional[str] = None
    error: Optional[str] = None
    cancelled_at: Optional[str] = None
    retry_of: Optional[str] = None
    priority: int = 0
    title: str = "Untitled video"
    folder: str = ""
    collection_ids: List[str] = Field(default_factory=list)
    favorite: bool = False
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VideoLibraryOrganization(BaseModel):
    """Owner-private folder or collection, retained even when currently empty."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    kind: str  # folder | collection
    name: str
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ---------- Voice Studio ----------
class VoiceJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"  # queued | preparing | processing | completed | failed | cancelled
    progress: int = 0
    provider: str = "mock"
    mode: str = "text-to-speech"
    text: str = ""
    voice: str = "lumina"
    output_format: str = "wav"
    source_media_id: Optional[str] = None
    output_media_id: Optional[str] = None
    error: Optional[str] = None
    title: str = "Untitled audio"
    tags: List[str] = Field(default_factory=list)
    folder: str = ""
    collection_ids: List[str] = Field(default_factory=list)
    favorite: bool = False
    metadata: dict = Field(default_factory=dict)
    retry_of: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VoiceLibraryOrganization(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    kind: str
    name: str
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VoicePack(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    description: str = ""
    language: str = "en"
    accent: str = ""
    gender: str = "unspecified"
    provider: str = "mock"
    provider_voice_id: Optional[str] = None
    readiness_status: str = "draft"  # draft | ready | archived | provider-pending | failed
    consent_confirmed: bool = False
    consent_at: Optional[str] = None
    ownership_declaration: str = ""
    sample_media_ids: List[str] = Field(default_factory=list)
    sample_count: int = 0
    total_sample_duration_seconds: float = 0
    favorite: bool = False
    tags: List[str] = Field(default_factory=list)
    archived_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TranscriptionJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"
    provider: str = "mock"
    source_media_id: str
    language: str = "auto"
    transcript: str = ""
    timestamps: List[dict] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TalkingFaceJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"
    provider: str = "mock"
    identity_pack_id: Optional[str] = None
    voice_pack_id: Optional[str] = None
    audio_media_id: Optional[str] = None
    transcript_id: Optional[str] = None
    project_id: Optional[str] = None
    portrait_media_id: Optional[str] = None
    script: str = ""
    output_media_id: Optional[str] = None
    error: Optional[str] = None
    consent_confirmed: bool = False
    consent_at: Optional[str] = None
    ownership_declaration: str = ""
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
