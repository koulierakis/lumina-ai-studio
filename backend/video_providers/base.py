"""Provider-neutral contracts for LUMINA Video Studio."""
from __future__ import annotations

from dataclasses import dataclass, field


class VideoProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, safe_message: str | None = None, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.safe_message = safe_message or "Video generation failed. Please try again."
        self.retryable = retryable


@dataclass(frozen=True)
class VideoGenerationInput:
    mode: str
    prompt: str
    duration_seconds: int
    aspect_ratio: str
    negative_prompt: str = ""
    resolution: str = "720p"
    fps: int = 24
    quality: str = "standard"
    camera_motion: str = "auto"
    style: str = "cinematic"
    seed: int | None = None
    source_images: list[bytes] = field(default_factory=list)
    source_mimes: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    source_video: bytes | None = None


@dataclass(frozen=True)
class VideoProviderCapabilities:
    text_to_video: bool = False
    image_to_video: bool = True
    multiple_images: bool = False
    extension: bool = False
    variation: bool = False
    interpolation: bool = False
    editing: bool = False
    output_formats: tuple[str, ...] = ("video/mp4", "video/webm")
    resolutions: tuple[str, ...] = ("720p",)
    durations: tuple[int, ...] = (3, 5, 8)
    aspect_ratios: tuple[str, ...] = ("16:9", "9:16")
    cancellation: bool = False
    max_image_inputs: int = 1
    max_prompt_length: int = 1000


@dataclass(frozen=True)
class GeneratedVideo:
    data: bytes
    mime_type: str
    preview_kind: str = "video"  # video | animated-image
    duration_seconds: int | None = None
    resolution: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderJob:
    id: str
    state: str
    progress: int | None = None
    output_url: str | None = None
    metadata: dict = field(default_factory=dict)


class VideoProvider:
    """Implement this contract to add a hosted video engine without UI changes."""

    name = "base"
    capabilities = VideoProviderCapabilities()
    supports_async_jobs = False

    @classmethod
    def is_configured(cls) -> bool:
        return False

    async def generate(self, spec: VideoGenerationInput) -> GeneratedVideo:
        raise VideoProviderError(self.name, "Video generation is unsupported")

    async def submit(self, spec: VideoGenerationInput) -> ProviderJob:
        raise VideoProviderError(self.name, "Asynchronous jobs are unsupported")

    async def poll(self, provider_job_id: str) -> ProviderJob:
        raise VideoProviderError(self.name, "Asynchronous jobs are unsupported")

    async def download(self, provider_job: ProviderJob) -> GeneratedVideo:
        raise VideoProviderError(self.name, "Asynchronous jobs are unsupported")

    async def cancel(self, provider_job_id: str) -> None:
        raise VideoProviderError(self.name, "Cancellation is unsupported")
