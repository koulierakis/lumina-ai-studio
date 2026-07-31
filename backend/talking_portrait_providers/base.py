"""Provider-neutral contracts for LUMINA Talking Portrait Studio."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable


class TalkingPortraitProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, safe_message: str | None = None, *, retryable: bool = False, stage: str | None = None, stdout: str | None = None, stderr: str | None = None, technical_details: dict | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.safe_message = safe_message or message or "Talking portrait generation failed."
        self.retryable = retryable
        self.stage = stage
        self.stdout = stdout
        self.stderr = stderr
        self.technical_details = technical_details or {}


class TalkingPortraitCancelledError(TalkingPortraitProviderError):
    def __init__(self, provider: str = "talking-portrait", message: str = "Talking portrait generation was cancelled.") -> None:
        super().__init__(provider, message, "Talking portrait generation was cancelled.", retryable=False, stage="cancelled")


ProgressCallback = Callable[[int, str], Awaitable[None]]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class TalkingPortraitInput:
    portrait_path: Path
    portrait_mime: str
    audio_path: Path
    audio_mime: str
    output_path: Path
    identity_lock: bool = True
    natural_blinking: bool = True
    head_motion: float = 0.35
    expression_intensity: float = 0.55
    fps: int = 25
    resolution: str = "512"
    seed: int | None = None
    should_cancel: CancelCallback | None = None


@dataclass(frozen=True)
class TalkingPortraitCapabilities:
    output_formats: tuple[str, ...] = ("video/mp4",)
    identity_lock: bool = True
    natural_blinking: bool = True
    head_motion: bool = True
    expression_intensity: bool = True
    gpu: bool = False
    cpu_fallback: bool = True
    windows: bool = True


@dataclass(frozen=True)
class GeneratedTalkingPortrait:
    data: bytes
    mime_type: str = "video/mp4"
    duration_seconds: float | None = None
    metadata: dict = field(default_factory=dict)


class TalkingPortraitProvider:
    name = "base"
    display_name = "Base Talking Portrait Provider"
    repository_url = ""
    capabilities = TalkingPortraitCapabilities()

    @classmethod
    def install_root(cls) -> Path:
        return Path(__file__).resolve().parents[2] / "local_models" / cls.name

    @classmethod
    def is_installed(cls) -> bool:
        return False

    @classmethod
    def diagnostics(cls) -> dict:
        return {"installed": cls.is_installed(), "install_root": str(cls.install_root()), "healthy": cls.is_installed()}

    async def generate(self, spec: TalkingPortraitInput, progress: ProgressCallback | None = None) -> GeneratedTalkingPortrait:
        raise TalkingPortraitProviderError(self.name, "Provider is not implemented")
