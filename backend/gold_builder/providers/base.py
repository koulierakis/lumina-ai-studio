"""Enhanced provider base: adds VideoProvider ABC and typed transient errors.

Kept backward compatible with earlier imports (Message, CompletionRequest,
CompletionResponse, LLMProvider, ImageProvider are unchanged).
"""
from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class CompletionRequest:
    messages: List[Message]
    max_tokens: int = 4096
    temperature: float = 0.2
    system: Optional[str] = None
    json_mode: bool = False
    required_capabilities: List[str] = field(default_factory=list)


@dataclass
class CompletionResponse:
    text: str
    provider: str
    model: str
    usage: dict = field(default_factory=dict)
    finish_reason: Optional[str] = None


class ProviderError(Exception):
    """Base error for provider failures. Router catches this to trigger fallback."""

    def __init__(self, message: str, *, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code = status_code if isinstance(status_code, int) else None
        self.retry_after = retry_after


class TransientProviderError(ProviderError):
    """Timeouts, 429s and other retryable failures.

    Timeouts and 5xx retry within bounds; 429 falls back immediately.
    """


class LLMProvider(ABC):
    id: str = "abstract"
    provider: str = ""
    model: str = ""
    capabilities = frozenset({"text", "json", "coding", "reasoning"})

    # Most providers are single completions and fit the router's default
    # attempt/total budgets. A delegated coding agent (e.g. OpenHands) runs a
    # full conversation and can legitimately take minutes, so it declares a
    # floor here. The router honors the floor for that provider instead of
    # cancelling it mid-conversation; 0.0 keeps the default behaviour.
    min_attempt_timeout_s: float = 0.0
    min_total_timeout_s: float = 0.0

    def supports(self, required: List[str]) -> bool:
        return set(required or []).issubset(set(self.capabilities))

    @abstractmethod
    async def complete(self, req: CompletionRequest) -> CompletionResponse: ...

    @abstractmethod
    def available(self) -> bool: ...


@dataclass
class ImageRequest:
    prompt: str
    n: int = 1
    size: str = "1024x1024"
    operation: str = "generate"  # generate | edit
    input_images: List[bytes] = field(default_factory=list)
    input_image_names: List[str] = field(default_factory=list)
    negative_prompt: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[str] = None
    quality: Optional[str] = None
    style: Optional[str] = None
    seed: Optional[int] = None
    output_format: str = "png"


@dataclass
class ImageResponse:
    images: List[bytes]
    provider: str
    model: str
    mime_types: List[str] = field(default_factory=list)
    provider_attempts: List[dict] = field(default_factory=list)


class ImageProvider(ABC):
    id: str = "abstract-image"
    provider: str = ""
    model: str = ""
    capabilities = frozenset({"text_to_image"})

    def supports(self, operation: str) -> bool:
        mapping = {"generate": "text_to_image", "edit": "image_to_image"}
        capability = mapping.get(operation, operation)
        return capability in set(self.capabilities)

    @abstractmethod
    async def generate(self, req: ImageRequest) -> ImageResponse: ...

    async def edit(self, req: ImageRequest) -> ImageResponse:
        raise ProviderError(f"{self.id} does not support image_to_image")

    @abstractmethod
    def available(self) -> bool: ...


# ------------- Video --------------
@dataclass
class VideoRequest:
    prompt: str
    seconds: float = 4.0
    size: str = "1024x576"
    operation: str = "generate"  # generate | animate | transform
    input_image: Optional[bytes] = None
    input_video: Optional[bytes] = None
    reference_images: List[bytes] = field(default_factory=list)
    negative_prompt: Optional[str] = None
    aspect_ratio: Optional[str] = None
    quality: Optional[str] = None
    seed: Optional[int] = None
    output_format: str = "mp4"
    fps: Optional[int] = None


@dataclass
class VideoJob:
    id: str
    status: str
    provider: str
    model: str
    progress: float = 0.0
    error: Optional[str] = None


@dataclass
class VideoResponse:
    video: bytes
    mime: str = "video/mp4"
    provider: str = ""
    model: str = ""
    duration: Optional[float] = None
    provider_attempts: List[dict] = field(default_factory=list)


class VideoProvider(ABC):
    id: str = "abstract-video"
    provider: str = ""
    model: str = ""
    capabilities = frozenset({"text_to_video"})

    def supports(self, operation: str) -> bool:
        mapping = {
            "generate": "text_to_video",
            "animate": "image_to_video",
            "transform": "video_to_video",
            "text_image": "text_image_to_video",
        }
        capability = mapping.get(operation, operation)
        return capability in set(self.capabilities)

    async def submit(self, req: VideoRequest) -> VideoJob:
        raise ProviderError(f"{self.id} does not implement async video jobs")

    async def status(self, job: VideoJob) -> VideoJob:
        raise ProviderError(f"{self.id} does not implement async video status")

    async def download(self, job: VideoJob) -> VideoResponse:
        raise ProviderError(f"{self.id} does not implement async video download")

    @abstractmethod
    def available(self) -> bool: ...

    async def generate(self, req: VideoRequest) -> VideoResponse:
        """Default async-job adapter with a bounded poll loop."""
        import asyncio
        job = await self.submit(req)
        for _ in range(120):
            if job.status == "completed":
                return await self.download(job)
            if job.status in {"failed", "cancelled"}:
                raise ProviderError(job.error or f"{self.id} video job {job.status}")
            await asyncio.sleep(1)
            job = await self.status(job)
        raise ProviderTimeoutError(f"{self.id} video job timed out")


def classify_transient(exc: Exception) -> bool:
    """Best-effort classifier — string-based to avoid vendor SDK imports."""
    s = str(exc).lower()
    signals = ("timeout", "timed out", "rate limit", "429", "503", "502",
               "504", "temporarily unavailable", "connection reset",
               "read timeout", "overloaded", "server error")
    return any(sig in s for sig in signals)


_STATUS_GUIDANCE = {
    401: "invalid or missing API key",
    402: "account out of credit/quota",
    403: "key rejected or region-blocked",
    410: "provider endpoint retired",
    429: "rate limited — wait or raise your quota",
}


def provider_failure_guidance(errors: List[str]) -> Optional[str]:
    """Turn raw per-provider error strings into a short operator hint.

    Errors carry a machine prefix (``<id>: <ExceptionType> HTTP <code>``) that
    the router and the live-provider E2E classifier depend on, so this only
    *adds* a human-readable next step instead of rewriting the prefix. It never
    invents a cause: if no recognised status or transport signal is present it
    returns ``None`` and the raw errors stand on their own.
    """
    text = " ".join(errors).lower()
    hints: List[str] = []
    for code in (401, 402, 403, 410, 429):
        if re.search(rf"\b{code}\b", text):
            hints.append(_STATUS_GUIDANCE[code])
    if any(sig in text for sig in ("timeout", "timed out", "connection", "dns", "unreachable")):
        hints.append("network reachability/timeout — check connectivity")
    if not hints:
        return None
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = [h for h in hints if not (h in seen or seen.add(h))]
    return "Check: " + "; ".join(unique) + "."


class ProviderTimeoutError(TransientProviderError):
    """An attempt or the complete routed request exhausted its time budget."""


def retry_delay(exc: Exception) -> Optional[float]:
    """Read a retry hint internally without emitting provider response bodies."""
    value = getattr(exc, "retry_after", None)
    if value is not None:
        try:
            value = float(value)
            if math.isfinite(value) and value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    match = re.search(
        r"try again in\s+(?:(?P<hours>[0-9.]+)h)?\s*(?:(?P<minutes>[0-9.]+)m)?\s*(?P<seconds>[0-9.]+)s",
        str(exc), re.I,
    )
    if match:
        value = (float(match.group("hours") or 0) * 3600
                 + float(match.group("minutes") or 0) * 60
                 + float(match.group("seconds")))
        if math.isfinite(value):
            return value + 1
    return None


def provider_exception(provider: str, exc: Exception) -> ProviderError:
    """Preserve retry metadata but exclude vendor bodies, headers, and keys."""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(response, "status_code", None)
    status = status if isinstance(status, int) else None
    headers = getattr(response, "headers", {})
    hint = headers.get("retry-after") if headers else None
    try:
        hint = float(hint) if hint is not None else retry_delay(exc)
    except (TypeError, ValueError):
        hint = retry_delay(exc)
    transient = (isinstance(status, int) and (status == 429 or 500 <= status < 600)) or classify_transient(exc)
    error_class = TransientProviderError if transient else ProviderError
    reason = f"HTTP {status}" if isinstance(status, int) else type(exc).__name__
    return error_class(f"{provider} request failed: {reason}",
                       status_code=status, retry_after=hint)


def provider_identity(provider: object) -> tuple[str, str]:
    """(vendor, model) for a provider instance.

    Two providers are the *same* implementation authority only when both the
    vendor and the model match. Comparing vendor alone would let two models of
    one vendor count as independent reviewers.
    """
    vendor = str(getattr(provider, "provider", "") or "").strip().lower()
    model = str(getattr(provider, "model", "") or "").strip().lower()
    return vendor, model
