"""Pydantic models for Lumina AI Desktop."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
    width: int | None = None
    height: int | None = None
    size_bytes: int = 0
    parent_media_id: str | None = None  # lineage: which media this was edited from
    edit_note: str | None = None
    source_module: str = "image"
    project_id: str | None = None
    job_id: str | None = None
    identity_pack_id: str | None = None
    voice_pack_id: str | None = None
    provider: str | None = None
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    folder: str = ""
    collection_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class WorkspaceNotification(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    type: str
    title: str
    message: str = ""
    resource_type: str | None = None
    resource_id: str | None = None
    read: bool = False
    created_at: str = Field(default_factory=now_iso)


# ---------- Identity Packs ----------
class IdentityPackCreate(BaseModel):
    name: str
    description: str | None = ""


class IdentityPackUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    primary_photo_id: str | None = None
    photo_ids: list[str] | None = None


class IdentityPack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    description: str = ""
    photo_ids: list[str] = Field(default_factory=list)
    primary_photo_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ---------- Generation ----------
class GenerationRequest(BaseModel):
    identity_pack_id: str | None = None
    project_id: str | None = None
    prompt: str
    negative_prompt: str | None = ""
    scene: str | None = ""
    outfit: str | None = ""
    aspect_ratio: str = "1:1"  # 9:16 | 16:9 | 1:1 | 4:5 | 3:2
    resolution: str = "1024"
    quality: str = "standard"
    seed: int | None = None
    mode: str = "text-to-image"
    identity_lock: str = "high"
    style_reference_id: str | None = None
    composition_reference_id: str | None = None
    reference_media_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    count: int = 1  # 1..4
    provider: str | None = None  # defaults to env IMAGE_PROVIDER


class GenerationJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"  # queued | processing | completed | failed
    provider: str = "gemini"
    identity_pack_id: str | None = None
    project_id: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    scene: str = ""
    outfit: str = ""
    aspect_ratio: str = "1:1"
    resolution: str = "1024"
    quality: str = "standard"
    seed: int | None = None
    mode: str = "text-to-image"
    identity_lock: str = "high"
    count: int = 1
    progress: int = 0
    estimated_seconds_remaining: int | None = None
    output_media_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    selected_provider: str | None = None
    attempted_providers: list[str] = Field(default_factory=list)
    provider_failures: list[dict] = Field(default_factory=list)
    fallback_used: bool = False
    generation_duration_ms: int | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


# ---------- Gallery ----------
class GalleryItem(BaseModel):
    """A gallery-facing representation of a generated (or edited) media asset."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)  # gallery entry id
    owner_email: str
    media_id: str
    job_id: str | None = None
    identity_pack_id: str | None = None
    project_id: str | None = None
    prompt: str = ""
    scene: str = ""
    outfit: str = ""
    aspect_ratio: str = "1:1"
    provider: str = "gemini"
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    collection_ids: list[str] = Field(default_factory=list)
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
    media_ids: list[str] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)
    identity_pack_ids: list[str] = Field(default_factory=list)
    notes: str = ""
    status: str = "active"  # active | paused | completed | archived
    tags: list[str] = Field(default_factory=list)
    cover_media_id: str | None = None
    export_media_ids: list[str] = Field(default_factory=list)
    archived_at: str | None = None
    activity: list[dict] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)



class PhotoCollection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    description: str = ""
    media_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class PhotoBatchJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"
    source_media_ids: list[str] = Field(default_factory=list)
    operations: dict[str, Any] = Field(default_factory=dict)
    output_media_ids: list[str] = Field(default_factory=list)
    error: str | None = None
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
    project_id: str | None = None
    identity_pack_id: str | None = None
    instruction: str = ""
    identity_lock: str = "high"
    mask_media_id: str | None = None  # if a mask was provided
    reference_media_ids: list[str] = Field(default_factory=list)
    export_options: dict[str, Any] = Field(default_factory=dict)
    output_media_id: str | None = None
    error: str | None = None
    selected_provider: str | None = None
    attempted_providers: list[str] = Field(default_factory=list)
    provider_failures: list[dict] = Field(default_factory=list)
    fallback_used: bool = False
    generation_duration_ms: int | None = None
    retry_of: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)



# ---------- Video Projects ----------
class VideoProject(BaseModel):
    """Professional non-destructive video project owned by the single owner."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str = "Untitled Video"
    aspect_ratio: str = "16:9"    # 9:16 | 16:9 | 1:1 | 4:5
    fps: int = 30                 # 24 | 25 | 30
    resolution: str = "1080p"     # 720p | 1080p | 2K | 4K
    version: int = 1
    tags: list[str] = Field(default_factory=list)
    favorite: bool = False
    collection_ids: list[str] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)
    ai_generation_history: list[dict] = Field(default_factory=list)
    template_ids: list[str] = Field(default_factory=list)
    # Freeform state blob managed by the frontend (clips, text overlays,
    # music, voice-over, adjustments). Kept as-is so the editor evolves
    # without schema migrations.
    state: dict = Field(default_factory=dict)
    exported_media_id: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VideoTemplate(BaseModel):
    """Reusable personal/company/brand/AI-generated video template."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str
    scope: str = "personal"  # personal | company | brand | ai-generated
    brief: str = ""
    favorite: bool = False
    brand_id: str | None = None
    template: dict = Field(default_factory=dict)
    usage_count: int = 0
    preference_score: float = 0.0
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VideoBrandKit(BaseModel):
    """Company branding assets and defaults for the Video Studio."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str = "Company Brand"
    logos: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=lambda: ["#D4AF37", "#0B0B0F"])
    fonts: list[str] = Field(default_factory=lambda: ["Inter", "Playfair Display"])
    intro_media_id: str | None = None
    outro_media_id: str | None = None
    watermark_media_id: str | None = None
    animations: list[str] = Field(default_factory=lambda: ["fade", "slide-up"])
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
    estimated_seconds_remaining: int | None = None
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
    seed: int | None = None
    source_media_id: str | None = None
    source_media_ids: list[str] = Field(default_factory=list)
    source_job_id: str | None = None
    output_media_id: str | None = None
    output_mime_type: str | None = None
    preview_kind: str | None = None
    error: str | None = None
    cancelled_at: str | None = None
    retry_of: str | None = None
    priority: int = 0
    title: str = "Untitled video"
    folder: str = ""
    collection_ids: list[str] = Field(default_factory=list)
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
    style: str = "podcast"
    preset_id: str | None = None
    personal_model_id: str | None = None
    output_format: str = "wav"
    sample_rate: int = 48000
    bit_depth: int = 24
    bitrate: str = "192k"
    loudness_lufs: float = -16
    source_media_id: str | None = None
    output_media_id: str | None = None
    error: str | None = None
    title: str = "Untitled audio"
    tags: list[str] = Field(default_factory=list)
    folder: str = ""
    collection_ids: list[str] = Field(default_factory=list)
    favorite: bool = False
    metadata: dict = Field(default_factory=dict)
    retry_of: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VoiceProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    voice_identity: dict = Field(default_factory=dict)
    speaking_profile: dict = Field(default_factory=dict)
    singing_profile: dict = Field(default_factory=dict)
    emotion_profiles: list[dict] = Field(default_factory=list)
    vocal_range: dict = Field(default_factory=dict)
    accent_profile: dict = Field(default_factory=dict)
    pronunciation_profile: dict = Field(default_factory=dict)
    breathing_profile: dict = Field(default_factory=dict)
    quality_score: int = 82


class PersonalVoiceModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    name: str = "Personal Voice Model"
    status: str = "active"
    profile: VoiceProfile = Field(default_factory=VoiceProfile)
    approved_recording_ids: list[str] = Field(default_factory=list)
    improvement_events: list[dict] = Field(default_factory=list)
    version: int = 1
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VoiceProjectVersion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    label: str = "Initial version"
    state: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class VoiceProject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    title: str = "Untitled voice project"
    project_type: str = "production"
    status: str = "draft"
    state: dict = Field(default_factory=dict)
    versions: list[VoiceProjectVersion] = Field(default_factory=list)
    collection_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    favorite: bool = False
    autosaved_at: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VoicePreset(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    category: str
    description: str
    chain: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    export: dict = Field(default_factory=dict)


class VoiceRecordingSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    title: str = "Untitled recording"
    microphone_label: str = "Default microphone"
    quality_preset: str = "studio"
    duration_seconds: float = 0
    sample_rate: int = 48000
    bit_depth: int = 24
    monitoring_enabled: bool = True
    waveform: list[float] = Field(default_factory=list)
    media_id: str | None = None
    take_history: list[dict] = Field(default_factory=list)
    approved_for_model: bool = False
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class VoiceExportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_id: str | None = None
    job_id: str | None = None
    format: str = "wav"
    sample_rate: int = 48000
    bit_depth: int = 24
    bitrate: str = "192k"
    loudness_lufs: float = -16
    metadata: dict = Field(default_factory=dict)


class VideoVoiceIntegrationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    video_project_id: str | None = None
    audio_media_id: str | None = None
    action: str = "replace-narration"
    lip_sync_preparation: bool = True
    metadata: dict = Field(default_factory=dict)


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
    provider_voice_id: str | None = None
    readiness_status: str = "draft"  # draft | ready | archived | provider-pending | failed
    consent_confirmed: bool = False
    consent_at: str | None = None
    ownership_declaration: str = ""
    sample_media_ids: list[str] = Field(default_factory=list)
    sample_count: int = 0
    total_sample_duration_seconds: float = 0
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    archived_at: str | None = None
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
    timestamps: list[dict] = Field(default_factory=list)
    error: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TalkingFaceJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"
    provider: str = "mock"
    identity_pack_id: str | None = None
    voice_pack_id: str | None = None
    audio_media_id: str | None = None
    transcript_id: str | None = None
    project_id: str | None = None
    portrait_media_id: str | None = None
    script: str = ""
    output_media_id: str | None = None
    error: str | None = None
    consent_confirmed: bool = False
    consent_at: str | None = None
    ownership_declaration: str = ""
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TalkingPortraitJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    owner_email: str
    status: str = "queued"  # queued | preparing | processing | rendering | completed | failed | cancelled | installing
    progress: int = 0
    estimated_seconds_remaining: int | None = None
    provider: str = "liveportrait"
    portrait_media_id: str | None = None
    audio_media_id: str | None = None
    output_media_id: str | None = None
    output_mime_type: str | None = None
    identity_lock: bool = True
    natural_blinking: bool = True
    head_motion: float = 0.35
    expression_intensity: float = 0.55
    fps: int = 25
    resolution: str = "512"
    seed: int | None = None
    title: str = "Talking portrait"
    error: str | None = None
    cancelled_at: str | None = None
    retry_of: str | None = None
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class TalkingPortraitInstallJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=new_id)
    install_job_id: str | None = None
    owner_email: str
    provider: str = "liveportrait"
    status: str = "queued"
    stage: str = "preflight"
    progress: int = 0
    step: str = "Queued"
    current_message: str = "Queued"
    log: list[str] = Field(default_factory=list)
    recent_log_lines: list[str] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    full_user_safe_error: str | None = None
    metadata: dict = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
