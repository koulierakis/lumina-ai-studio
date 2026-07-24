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
