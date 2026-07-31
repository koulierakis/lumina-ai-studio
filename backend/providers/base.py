"""Provider-neutral image generation contracts for Lumina AI Desktop."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class ErrorKind(str, Enum):
    AUTH = "authentication"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ProviderError(RuntimeError):
    def __init__(
        self,
        provider: str,
        message: str,
        *,
        kind: ErrorKind = ErrorKind.UNKNOWN,
        retryable: bool = False,
        status_code: int | None = None,
        safe_message: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code
        self.safe_message = safe_message
        self.retry_after_seconds = retry_after_seconds

    def public_message(self) -> str:
        if self.safe_message:
            return self.safe_message
        labels = {
            ErrorKind.AUTH: "Provider credentials are invalid or missing.",
            ErrorKind.QUOTA: "Provider quota is exhausted.",
            ErrorKind.RATE_LIMIT: "Provider rate limit reached.",
            ErrorKind.TIMEOUT: "Provider request timed out.",
            ErrorKind.INVALID_REQUEST: "Provider rejected the request.",
            ErrorKind.UNAVAILABLE: "Provider is temporarily unavailable.",
            ErrorKind.UNSUPPORTED: "Provider does not support this operation.",
        }
        return labels.get(self.kind, "Provider request failed.")

    def availability_state(self) -> str:
        if self.kind == ErrorKind.AUTH:
            return "missing_credentials"
        if self.kind == ErrorKind.QUOTA:
            return "quota_exhausted"
        if self.kind in {ErrorKind.RATE_LIMIT, ErrorKind.TIMEOUT, ErrorKind.UNAVAILABLE}:
            return "temporarily_unavailable"
        if self.kind == ErrorKind.UNSUPPORTED:
            return "unsupported_operation"
        return "unavailable"

    def safe_summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "retryable": self.retryable,
            "status_code": self.status_code,
            "safe_message": self.public_message(),
            "retry_after_seconds": self.retry_after_seconds,
            "kind": self.kind.value,
            "availability_state": self.availability_state(),
        }


class ProviderTimeoutError(ProviderError):
    def __init__(self, provider: str, message: str = "Provider request timed out.", **kwargs: Any) -> None:
        super().__init__(provider, message, kind=ErrorKind.TIMEOUT, retryable=True, **kwargs)


class ProviderRateLimitError(ProviderError):
    def __init__(self, provider: str, message: str = "Provider rate limit reached.", **kwargs: Any) -> None:
        super().__init__(provider, message, kind=ErrorKind.RATE_LIMIT, retryable=True, **kwargs)


class ProviderQuotaError(ProviderError):
    def __init__(self, provider: str, message: str = "Provider quota is exhausted.", **kwargs: Any) -> None:
        super().__init__(provider, message, kind=ErrorKind.QUOTA, retryable=True, **kwargs)


class ProviderAuthenticationError(ProviderError):
    def __init__(self, provider: str, message: str = "Provider credentials are invalid or missing.", **kwargs: Any) -> None:
        super().__init__(provider, message, kind=ErrorKind.AUTH, retryable=False, **kwargs)


class ProviderConfigurationError(ProviderError):
    def __init__(self, provider: str, message: str = "Provider is not configured.", **kwargs: Any) -> None:
        super().__init__(provider, message, kind=ErrorKind.AUTH, retryable=False, **kwargs)


class ProviderUnsupportedCapabilityError(ProviderError):
    def __init__(self, provider: str, message: str = "Provider does not support this operation.", **kwargs: Any) -> None:
        super().__init__(provider, message, kind=ErrorKind.UNSUPPORTED, retryable=False, **kwargs)


class ProviderContentPolicyError(ProviderError):
    def __init__(self, provider: str, message: str = "Provider rejected the content.", **kwargs: Any) -> None:
        super().__init__(provider, message, kind=ErrorKind.INVALID_REQUEST, retryable=False, **kwargs)


class ProviderInvalidResponseError(ProviderError):
    def __init__(self, provider: str, message: str = "Provider returned no valid image.", **kwargs: Any) -> None:
        super().__init__(provider, message, kind=ErrorKind.UNAVAILABLE, retryable=True, **kwargs)


@dataclass(frozen=True)
class ProviderCapabilities:
    generation: bool = True
    editing: bool = False
    identity_references: bool = False
    masks: bool = False
    multiple_outputs: bool = True
    aspect_ratios: tuple[str, ...] = ("1:1",)
    models: tuple[str, ...] = ()
    maximum_reference_images: int = 0
    maximum_outputs: int = 1


@dataclass
class ProviderStatus:
    name: str
    configured: bool
    healthy: bool
    priority: int
    capabilities: ProviderCapabilities
    detail: str = ""
    available: bool | None = None
    cooldown_until: str | None = None
    last_safe_error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        available = self.healthy if self.available is None else self.available
        return {
            "name": self.name,
            "configured": self.configured,
            "healthy": self.healthy,
            "available": available,
            "cooldown_until": self.cooldown_until,
            "priority": self.priority,
            "detail": self.detail,
            "last_safe_error": self.last_safe_error,
            "supports_generate": self.capabilities.generation,
            "supports_edit": self.capabilities.editing,
            "supports_identity_references": self.capabilities.identity_references,
            "supports_mask": self.capabilities.masks,
            "supported_aspect_ratios": list(self.capabilities.aspect_ratios),
            "maximum_reference_images": self.capabilities.maximum_reference_images,
            "maximum_outputs": self.capabilities.maximum_outputs,
            "capabilities": {
                "generation": self.capabilities.generation,
                "editing": self.capabilities.editing,
                "identity_references": self.capabilities.identity_references,
                "masks": self.capabilities.masks,
                "multiple_outputs": self.capabilities.multiple_outputs,
                "aspect_ratios": list(self.capabilities.aspect_ratios),
                "models": list(self.capabilities.models),
                "maximum_reference_images": self.capabilities.maximum_reference_images,
                "maximum_outputs": self.capabilities.maximum_outputs,
            },
        }


@dataclass
class ProviderRoutingResult:
    provider: str
    images: list[GeneratedImage]
    attempted_providers: list[str]
    provider_failures: list[dict[str, Any]]
    fallback_used: bool
    generation_duration_ms: int


@dataclass
class GenerationInput:
    prompt: str
    negative_prompt: str = ""
    scene: str = ""
    outfit: str = ""
    aspect_ratio: str = "1:1"
    resolution: str = "1024"
    quality: str = "standard"
    seed: Optional[int] = None
    mode: str = "text-to-image"
    identity_lock: str = "high"
    metadata: dict[str, Any] = field(default_factory=dict)
    count: int = 1
    model: Optional[str] = None
    reference_images: List[bytes] = field(default_factory=list)
    reference_mimes: List[str] = field(default_factory=list)


@dataclass
class GeneratedImage:
    data: bytes
    mime_type: str = "image/png"


class ImageProvider:
    name: str = "base"
    priority: int = 100
    capabilities = ProviderCapabilities()

    @classmethod
    def is_configured(cls) -> bool:
        return False

    async def health_check(self) -> ProviderStatus:
        configured = self.is_configured()
        return ProviderStatus(
            name=self.name,
            configured=configured,
            healthy=configured,
            priority=self.priority,
            capabilities=self.capabilities,
            detail="ready" if configured else "credentials not configured",
        )

    async def generate(self, spec: GenerationInput) -> List[GeneratedImage]:
        raise ProviderUnsupportedCapabilityError(self.name, "Generation is unsupported")

    async def edit(
        self,
        source_bytes: bytes,
        source_mime: str,
        instruction: str,
        mask_bytes: Optional[bytes] = None,
        mask_mime: Optional[str] = None,
        identity_refs: Optional[List[bytes]] = None,
    ) -> GeneratedImage:
        raise ProviderUnsupportedCapabilityError(self.name, "Editing is unsupported")
