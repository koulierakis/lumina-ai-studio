"""Local Ollama API integration for the LUMINA Code Builder.

This module provides a production-oriented asynchronous client for a local
Ollama installation.

Responsibilities include:

- Validating the configured local Ollama endpoint.
- Checking whether Ollama is running and responding.
- Retrieving the installed Ollama version.
- Listing locally installed models.
- Sending non-streaming requests to /api/generate and /api/chat.
- Requesting structured JSON or JSON Schema constrained responses.
- Parsing responses into dictionaries or Pydantic v2 models.
- Handling connection failures, HTTP errors, malformed responses,
  unavailable models, and generation timeouts.
- Retrying transient failures with bounded exponential backoff.
- Preventing accidental connections to non-local or unsafe hosts.
- Providing explicit connection-status information for the frontend.

The structured-output, generate, chat, and public helper methods continue
in Part 2 of this file.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import random
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from .models import OllamaConnectionStatus


LOGGER = logging.getLogger(__name__)

UTC = timezone.utc

DEFAULT_OLLAMA_BASE_URL: Final[str] = "http://127.0.0.1:11434"
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0
DEFAULT_READ_TIMEOUT_SECONDS: Final[float] = 300.0
DEFAULT_WRITE_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_POOL_TIMEOUT_SECONDS: Final[float] = 10.0
DEFAULT_HEALTH_TIMEOUT_SECONDS: Final[float] = 5.0
DEFAULT_MAX_RETRIES: Final[int] = 2
DEFAULT_RETRY_BASE_DELAY_SECONDS: Final[float] = 0.75
DEFAULT_RETRY_MAX_DELAY_SECONDS: Final[float] = 5.0
DEFAULT_MAX_RESPONSE_BYTES: Final[int] = 25_000_000
DEFAULT_KEEP_ALIVE: Final[str] = "5m"
MAX_PROMPT_CHARACTERS: Final[int] = 2_000_000
MAX_MESSAGES: Final[int] = 1_000
MAX_MESSAGE_CHARACTERS: Final[int] = 1_000_000

SAFE_LOCAL_HOST_NAMES: Final[frozenset[str]] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "127.0.0.1",
        "::1",
    }
)

RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset(
    {
        408,
        409,
        425,
        429,
        500,
        502,
        503,
        504,
    }
)

MODEL_NOT_FOUND_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"model\s+['\"]?.+?['\"]?\s+not\s+found",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"model\s+.+?\s+does\s+not\s+exist",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"pull\s+model",
        flags=re.IGNORECASE,
    ),
)

JSON_CODE_FENCE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    ^\s*
    ```(?:json)?
    \s*
    (?P<body>[\s\S]*?)
    \s*
    ```
    \s*$
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

JSON_OBJECT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\{[\s\S]*\}"
)

JSON_ARRAY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\[[\s\S]*\]"
)


StructuredModelT = TypeVar(
    "StructuredModelT",
    bound=BaseModel,
)


class OllamaServiceError(RuntimeError):
    """Base exception for Ollama service failures."""


class OllamaConfigurationError(OllamaServiceError):
    """Raised when the Ollama client configuration is invalid."""


class OllamaUnavailableError(OllamaServiceError):
    """Raised when the local Ollama service cannot be reached."""


class OllamaTimeoutError(OllamaServiceError):
    """Raised when Ollama does not respond within the configured timeout."""


class OllamaHTTPError(OllamaServiceError):
    """Raised when the Ollama API returns an unsuccessful HTTP response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        response_body: str | None = None,
    ) -> None:
        """Initialize an Ollama HTTP error."""

        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class OllamaModelNotFoundError(OllamaHTTPError):
    """Raised when the requested local Ollama model is unavailable."""


class OllamaResponseError(OllamaServiceError):
    """Raised when Ollama returns an invalid or incomplete response."""


class OllamaStructuredOutputError(OllamaResponseError):
    """Raised when a structured Ollama response cannot be parsed."""


class OllamaResponseValidationError(OllamaStructuredOutputError):
    """Raised when structured output fails Pydantic validation."""


class OllamaRequestCancelledError(OllamaServiceError):
    """Raised when an Ollama request is cancelled."""


class OllamaEndpoint(str, Enum):
    """Supported Ollama API endpoints."""

    VERSION = "/api/version"
    TAGS = "/api/tags"
    GENERATE = "/api/generate"
    CHAT = "/api/chat"


@dataclass(frozen=True, slots=True)
class OllamaTimeoutConfiguration:
    """HTTP timeout configuration for Ollama requests."""

    connect_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
    write_seconds: float = DEFAULT_WRITE_TIMEOUT_SECONDS
    pool_seconds: float = DEFAULT_POOL_TIMEOUT_SECONDS
    health_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """Validate all timeout values."""

        timeout_values = {
            "connect_seconds": self.connect_seconds,
            "read_seconds": self.read_seconds,
            "write_seconds": self.write_seconds,
            "pool_seconds": self.pool_seconds,
            "health_seconds": self.health_seconds,
        }

        for field_name, value in timeout_values.items():
            if isinstance(value, bool):
                raise OllamaConfigurationError(
                    f"{field_name} must be a positive number."
                )

            if not math.isfinite(value) or value <= 0:
                raise OllamaConfigurationError(
                    f"{field_name} must be a finite positive number."
                )

    def to_httpx_timeout(self) -> httpx.Timeout:
        """Build the HTTPX timeout used for generation requests."""

        return httpx.Timeout(
            connect=self.connect_seconds,
            read=self.read_seconds,
            write=self.write_seconds,
            pool=self.pool_seconds,
        )

    def to_health_timeout(self) -> httpx.Timeout:
        """Build the shorter HTTPX timeout used for health checks."""

        return httpx.Timeout(
            connect=min(
                self.connect_seconds,
                self.health_seconds,
            ),
            read=self.health_seconds,
            write=min(
                self.write_seconds,
                self.health_seconds,
            ),
            pool=min(
                self.pool_seconds,
                self.health_seconds,
            ),
        )


@dataclass(frozen=True, slots=True)
class OllamaRetryConfiguration:
    """Bounded retry policy for transient Ollama failures."""

    maximum_retries: int = DEFAULT_MAX_RETRIES
    base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS
    maximum_delay_seconds: float = DEFAULT_RETRY_MAX_DELAY_SECONDS
    use_jitter: bool = True

    def __post_init__(self) -> None:
        """Validate retry settings."""

        if isinstance(self.maximum_retries, bool):
            raise OllamaConfigurationError(
                "maximum_retries must be an integer."
            )

        if self.maximum_retries < 0 or self.maximum_retries > 10:
            raise OllamaConfigurationError(
                "maximum_retries must be between 0 and 10."
            )

        for field_name, value in {
            "base_delay_seconds": self.base_delay_seconds,
            "maximum_delay_seconds": self.maximum_delay_seconds,
        }.items():
            if isinstance(value, bool):
                raise OllamaConfigurationError(
                    f"{field_name} must be a positive number."
                )

            if not math.isfinite(value) or value <= 0:
                raise OllamaConfigurationError(
                    f"{field_name} must be a finite positive number."
                )

        if self.maximum_delay_seconds < self.base_delay_seconds:
            raise OllamaConfigurationError(
                "maximum_delay_seconds cannot be lower than "
                "base_delay_seconds."
            )

    def calculate_delay(self, retry_number: int) -> float:
        """Calculate bounded exponential retry delay."""

        retry_number = max(retry_number, 0)

        delay = min(
            self.base_delay_seconds * (2 ** retry_number),
            self.maximum_delay_seconds,
        )

        if self.use_jitter:
            delay *= random.uniform(0.75, 1.25)

        return min(delay, self.maximum_delay_seconds)


@dataclass(frozen=True, slots=True)
class OllamaClientConfiguration:
    """Configuration for the local Ollama API client."""

    base_url: str = DEFAULT_OLLAMA_BASE_URL
    allow_non_local_host: bool = False
    verify_tls: bool = True
    follow_redirects: bool = False
    maximum_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    default_keep_alive: str | int | None = DEFAULT_KEEP_ALIVE
    user_agent: str = "LUMINA-Code-Builder/1.0"
    timeouts: OllamaTimeoutConfiguration = OllamaTimeoutConfiguration()
    retries: OllamaRetryConfiguration = OllamaRetryConfiguration()

    def __post_init__(self) -> None:
        """Validate and normalize client configuration."""

        normalized_base_url = _normalize_base_url(self.base_url)

        object.__setattr__(
            self,
            "base_url",
            normalized_base_url,
        )

        if (
            isinstance(self.maximum_response_bytes, bool)
            or self.maximum_response_bytes <= 0
        ):
            raise OllamaConfigurationError(
                "maximum_response_bytes must be a positive integer."
            )

        if self.maximum_response_bytes > 250_000_000:
            raise OllamaConfigurationError(
                "maximum_response_bytes cannot exceed 250,000,000 bytes."
            )

        if not self.user_agent.strip():
            raise OllamaConfigurationError(
                "user_agent cannot be empty."
            )

        parsed_url = urlparse(normalized_base_url)

        if (
            not self.allow_non_local_host
            and not _is_local_host(parsed_url.hostname)
        ):
            raise OllamaConfigurationError(
                "Ollama must use a local endpoint. Set "
                "allow_non_local_host=True only for an explicitly trusted "
                "private Ollama server."
            )


@dataclass(frozen=True, slots=True)
class OllamaModelInformation:
    """Metadata for one locally installed Ollama model."""

    name: str
    model: str | None
    modified_at: str | None
    size_bytes: int | None
    digest: str | None
    parameter_size: str | None
    quantization_level: str | None
    family: str | None
    families: tuple[str, ...]
    format: str | None

    @classmethod
    def from_api_data(
        cls,
        value: Mapping[str, Any],
    ) -> "OllamaModelInformation":
        """Build model information from an Ollama /api/tags entry."""

        details_value = value.get("details")
        details = (
            details_value
            if isinstance(details_value, Mapping)
            else {}
        )

        families_value = details.get("families")

        if isinstance(families_value, Sequence) and not isinstance(
            families_value,
            (str, bytes, bytearray),
        ):
            families = tuple(
                str(item)
                for item in families_value
                if item is not None
            )
        else:
            families = ()

        size_value = value.get("size")

        size_bytes = (
            size_value
            if isinstance(size_value, int)
            and not isinstance(size_value, bool)
            and size_value >= 0
            else None
        )

        return cls(
            name=str(value.get("name") or ""),
            model=(
                str(value["model"])
                if value.get("model") is not None
                else None
            ),
            modified_at=(
                str(value["modified_at"])
                if value.get("modified_at") is not None
                else None
            ),
            size_bytes=size_bytes,
            digest=(
                str(value["digest"])
                if value.get("digest") is not None
                else None
            ),
            parameter_size=(
                str(details["parameter_size"])
                if details.get("parameter_size") is not None
                else None
            ),
            quantization_level=(
                str(details["quantization_level"])
                if details.get("quantization_level") is not None
                else None
            ),
            family=(
                str(details["family"])
                if details.get("family") is not None
                else None
            ),
            families=families,
            format=(
                str(details["format"])
                if details.get("format") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class OllamaHealthInformation:
    """Structured Ollama connection and health information."""

    status: OllamaConnectionStatus
    available: bool
    base_url: str
    checked_at: datetime
    response_time_ms: float | None
    version: str | None
    installed_models: tuple[OllamaModelInformation, ...]
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable health information."""

        status_value = (
            self.status.value
            if isinstance(self.status, Enum)
            else str(self.status)
        )

        return {
            "status": status_value,
            "available": self.available,
            "base_url": self.base_url,
            "checked_at": self.checked_at.isoformat(),
            "response_time_ms": self.response_time_ms,
            "version": self.version,
            "installed_models": [
                {
                    "name": model.name,
                    "model": model.model,
                    "modified_at": model.modified_at,
                    "size_bytes": model.size_bytes,
                    "digest": model.digest,
                    "parameter_size": model.parameter_size,
                    "quantization_level": model.quantization_level,
                    "family": model.family,
                    "families": list(model.families),
                    "format": model.format,
                }
                for model in self.installed_models
            ],
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class OllamaRawResponse:
    """Normalized successful response from an Ollama generation endpoint."""

    endpoint: OllamaEndpoint
    model: str
    content: str
    raw_data: dict[str, Any]
    created_at: str | None
    done: bool
    done_reason: str | None
    total_duration_nanoseconds: int | None
    load_duration_nanoseconds: int | None
    prompt_eval_count: int | None
    prompt_eval_duration_nanoseconds: int | None
    eval_count: int | None
    eval_duration_nanoseconds: int | None
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable normalized response."""

        return {
            "endpoint": self.endpoint.value,
            "model": self.model,
            "content": self.content,
            "created_at": self.created_at,
            "done": self.done,
            "done_reason": self.done_reason,
            "total_duration_nanoseconds": (
                self.total_duration_nanoseconds
            ),
            "load_duration_nanoseconds": (
                self.load_duration_nanoseconds
            ),
            "prompt_eval_count": self.prompt_eval_count,
            "prompt_eval_duration_nanoseconds": (
                self.prompt_eval_duration_nanoseconds
            ),
            "eval_count": self.eval_count,
            "eval_duration_nanoseconds": (
                self.eval_duration_nanoseconds
            ),
            "elapsed_seconds": self.elapsed_seconds,
            "raw_data": self.raw_data,
        }


@dataclass(frozen=True, slots=True)
class OllamaStructuredResponse:
    """Normalized structured JSON response from Ollama."""

    raw_response: OllamaRawResponse
    data: dict[str, Any] | list[Any]
    validated_model: BaseModel | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable structured response."""

        result: dict[str, Any] = {
            "response": self.raw_response.to_dict(),
            "data": self.data,
        }

        if self.validated_model is not None:
            result["validated_model"] = (
                self.validated_model.model_dump(
                    mode="json",
                )
            )

        return result


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(UTC)


def _normalize_base_url(base_url: str) -> str:
    """Validate and normalize an Ollama base URL."""

    if not isinstance(base_url, str):
        raise OllamaConfigurationError(
            "Ollama base_url must be a string."
        )

    normalized = base_url.strip().rstrip("/")

    if not normalized:
        raise OllamaConfigurationError(
            "Ollama base_url cannot be empty."
        )

    if "\x00" in normalized:
        raise OllamaConfigurationError(
            "Ollama base_url contains a null byte."
        )

    parsed = urlparse(normalized)

    if parsed.scheme not in {"http", "https"}:
        raise OllamaConfigurationError(
            "Ollama base_url must use http or https."
        )

    if not parsed.hostname:
        raise OllamaConfigurationError(
            "Ollama base_url must contain a hostname."
        )

    if parsed.username is not None or parsed.password is not None:
        raise OllamaConfigurationError(
            "Credentials must not be embedded in the Ollama base URL."
        )

    if parsed.query or parsed.fragment:
        raise OllamaConfigurationError(
            "Ollama base_url cannot contain a query or fragment."
        )

    normalized_path = parsed.path.rstrip("/")

    if normalized_path not in {"", "/"}:
        raise OllamaConfigurationError(
            "Ollama base_url must not include an API endpoint path."
        )

    port = parsed.port

    if port is not None and not 1 <= port <= 65_535:
        raise OllamaConfigurationError(
            "Ollama base_url contains an invalid port."
        )

    host = parsed.hostname

    if host is None:
        raise OllamaConfigurationError(
            "Ollama base_url hostname is invalid."
        )

    if ":" in host and not host.startswith("["):
        rendered_host = f"[{host}]"
    else:
        rendered_host = host

    if port is not None:
        authority = f"{rendered_host}:{port}"
    else:
        authority = rendered_host

    return f"{parsed.scheme}://{authority}"


def _is_local_host(hostname: str | None) -> bool:
    """Return whether a hostname represents the local machine."""

    if hostname is None:
        return False

    normalized = hostname.strip().casefold().rstrip(".")

    if normalized in SAFE_LOCAL_HOST_NAMES:
        return True

    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False

    return address.is_loopback


def _coerce_connection_status(
    *,
    available: bool,
    timeout: bool = False,
    error: bool = False,
) -> OllamaConnectionStatus:
    """Create a compatible OllamaConnectionStatus enum value.

    The helper supports common enum naming conventions so the service remains
    compatible with the concrete enum values defined in models.py.
    """

    if timeout:
        preferred_names = (
            "TIMEOUT",
            "TIMED_OUT",
            "UNAVAILABLE",
            "DISCONNECTED",
            "ERROR",
            "UNKNOWN",
        )
        preferred_values = (
            "timeout",
            "timed_out",
            "unavailable",
            "disconnected",
            "error",
            "unknown",
        )
    elif available:
        preferred_names = (
            "AVAILABLE",
            "CONNECTED",
            "ONLINE",
            "READY",
            "HEALTHY",
        )
        preferred_values = (
            "available",
            "connected",
            "online",
            "ready",
            "healthy",
        )
    elif error:
        preferred_names = (
            "ERROR",
            "UNAVAILABLE",
            "DISCONNECTED",
            "OFFLINE",
            "UNKNOWN",
        )
        preferred_values = (
            "error",
            "unavailable",
            "disconnected",
            "offline",
            "unknown",
        )
    else:
        preferred_names = (
            "UNAVAILABLE",
            "DISCONNECTED",
            "OFFLINE",
            "UNKNOWN",
            "ERROR",
        )
        preferred_values = (
            "unavailable",
            "disconnected",
            "offline",
            "unknown",
            "error",
        )

    enum_members = getattr(
        OllamaConnectionStatus,
        "__members__",
        {},
    )

    for member_name in preferred_names:
        member = enum_members.get(member_name)

        if member is not None:
            return member

    for value in preferred_values:
        try:
            return OllamaConnectionStatus(value)
        except ValueError:
            continue

    try:
        return next(iter(OllamaConnectionStatus))
    except StopIteration as exc:
        raise OllamaConfigurationError(
            "OllamaConnectionStatus does not define any values."
        ) from exc


def _optional_int(value: Any) -> int | None:
    """Return a valid integer or None."""

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    return None


def _safe_error_body(
    response: httpx.Response,
    *,
    maximum_characters: int = 4_000,
) -> str:
    """Return a bounded error body suitable for logs and exceptions."""

    try:
        body = response.text.strip()
    except (UnicodeDecodeError, httpx.DecodingError):
        return "[response body could not be decoded]"

    if len(body) > maximum_characters:
        return f"{body[:maximum_characters]}β€¦"

    return body


def _extract_ollama_error_message(
    response: httpx.Response,
) -> str:
    """Extract a useful error message from an Ollama response."""

    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = None

    if isinstance(payload, Mapping):
        error_value = payload.get("error")

        if isinstance(error_value, str) and error_value.strip():
            return error_value.strip()

        message_value = payload.get("message")

        if isinstance(message_value, str) and message_value.strip():
            return message_value.strip()

    body = _safe_error_body(response)

    if body:
        return body

    return f"Ollama returned HTTP {response.status_code}."


def _looks_like_model_not_found(message: str) -> bool:
    """Return whether an Ollama error indicates a missing local model."""

    return any(
        pattern.search(message)
        for pattern in MODEL_NOT_FOUND_PATTERNS
    )


def _validate_model_name(model: str) -> str:
    """Validate an Ollama model identifier."""

    if not isinstance(model, str):
        raise OllamaConfigurationError(
            "The Ollama model name must be a string."
        )

    normalized = model.strip()

    if not normalized:
        raise OllamaConfigurationError(
            "The Ollama model name cannot be empty."
        )

    if "\x00" in normalized:
        raise OllamaConfigurationError(
            "The Ollama model name contains a null byte."
        )

    if len(normalized) > 512:
        raise OllamaConfigurationError(
            "The Ollama model name is too long."
        )

    if any(
        character in normalized
        for character in ("\r", "\n", "\t")
    ):
        raise OllamaConfigurationError(
            "The Ollama model name contains invalid whitespace."
        )

    return normalized


def _validate_prompt(prompt: str) -> str:
    """Validate a generation prompt."""

    if not isinstance(prompt, str):
        raise OllamaConfigurationError(
            "The Ollama prompt must be a string."
        )

    if not prompt.strip():
        raise OllamaConfigurationError(
            "The Ollama prompt cannot be empty."
        )

    if "\x00" in prompt:
        raise OllamaConfigurationError(
            "The Ollama prompt contains a null byte."
        )

    if len(prompt) > MAX_PROMPT_CHARACTERS:
        raise OllamaConfigurationError(
            "The Ollama prompt exceeds the maximum permitted length of "
            f"{MAX_PROMPT_CHARACTERS} characters."
        )

    return prompt


def _validate_system_prompt(
    system_prompt: str | None,
) -> str | None:
    """Validate an optional system prompt."""

    if system_prompt is None:
        return None

    if not isinstance(system_prompt, str):
        raise OllamaConfigurationError(
            "The Ollama system prompt must be a string."
        )

    if "\x00" in system_prompt:
        raise OllamaConfigurationError(
            "The Ollama system prompt contains a null byte."
        )

    if len(system_prompt) > MAX_PROMPT_CHARACTERS:
        raise OllamaConfigurationError(
            "The Ollama system prompt exceeds the maximum permitted "
            "length."
        )

    normalized = system_prompt.strip()

    return normalized or None


def _validate_messages(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate and normalize Ollama chat messages."""

    if isinstance(
        messages,
        (str, bytes, bytearray),
    ):
        raise OllamaConfigurationError(
            "Chat messages must be a sequence of message objects."
        )

    if not messages:
        raise OllamaConfigurationError(
            "At least one chat message is required."
        )

    if len(messages) > MAX_MESSAGES:
        raise OllamaConfigurationError(
            f"Chat messages cannot exceed {MAX_MESSAGES} entries."
        )

    normalized_messages: list[dict[str, Any]] = []

    allowed_roles = {
        "system",
        "user",
        "assistant",
        "tool",
    }

    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            raise OllamaConfigurationError(
                f"Chat message {index} must be an object."
            )

        role_value = message.get("role")
        content_value = message.get("content")

        if not isinstance(role_value, str):
            raise OllamaConfigurationError(
                f"Chat message {index} has an invalid role."
            )

        role = role_value.strip().casefold()

        if role not in allowed_roles:
            raise OllamaConfigurationError(
                f"Chat message {index} uses an unsupported role: "
                f"{role_value}"
            )

        if not isinstance(content_value, str):
            raise OllamaConfigurationError(
                f"Chat message {index} content must be a string."
            )

        if "\x00" in content_value:
            raise OllamaConfigurationError(
                f"Chat message {index} contains a null byte."
            )

        if len(content_value) > MAX_MESSAGE_CHARACTERS:
            raise OllamaConfigurationError(
                f"Chat message {index} exceeds the maximum permitted "
                "length."
            )

        normalized_message: dict[str, Any] = {
            "role": role,
            "content": content_value,
        }

        images_value = message.get("images")

        if images_value is not None:
            if (
                not isinstance(images_value, Sequence)
                or isinstance(
                    images_value,
                    (str, bytes, bytearray),
                )
            ):
                raise OllamaConfigurationError(
                    f"Chat message {index} images must be a sequence."
                )

            normalized_message["images"] = [
                str(image)
                for image in images_value
            ]

        tool_calls_value = message.get("tool_calls")

        if tool_calls_value is not None:
            if (
                not isinstance(tool_calls_value, Sequence)
                or isinstance(
                    tool_calls_value,
                    (str, bytes, bytearray),
                )
            ):
                raise OllamaConfigurationError(
                    f"Chat message {index} tool_calls must be a sequence."
                )

            normalized_message["tool_calls"] = list(
                tool_calls_value
            )

        normalized_messages.append(normalized_message)

    return normalized_messages


class OllamaService:
    """Asynchronous local Ollama API service.

    One service instance owns one reusable ``httpx.AsyncClient``. It should
    be closed during FastAPI application shutdown or used as an async context
    manager.
    """

    def __init__(
        self,
        configuration: OllamaClientConfiguration | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the Ollama service."""

        self.configuration = (
            configuration
            if configuration is not None
            else OllamaClientConfiguration()
        )

        self._owns_client = client is None
        self._closed = False

        if client is None:
            self._client = httpx.AsyncClient(
                base_url=self.configuration.base_url,
                timeout=self.configuration.timeouts.to_httpx_timeout(),
                verify=self.configuration.verify_tls,
                follow_redirects=(
                    self.configuration.follow_redirects
                ),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": self.configuration.user_agent,
                },
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=30.0,
                ),
                trust_env=False,
            )
        else:
            self._client = client

    async def __aenter__(self) -> "OllamaService":
        """Enter the async context manager."""

        self._ensure_open()
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        """Close owned HTTP resources when leaving the context."""

        await self.close()

    @property
    def base_url(self) -> str:
        """Return the normalized Ollama base URL."""

        return self.configuration.base_url

    @property
    def is_closed(self) -> bool:
        """Return whether the service has been closed."""

        return self._closed

    def _ensure_open(self) -> None:
        """Raise when the service has already been closed."""

        if self._closed:
            raise OllamaServiceError(
                "The Ollama service has already been closed."
            )

    async def close(self) -> None:
        """Close the owned asynchronous HTTP client."""

        if self._closed:
            return

        self._closed = True

        if self._owns_client:
            await self._client.aclose()

    async def _sleep_before_retry(
        self,
        retry_number: int,
    ) -> None:
        """Wait before retrying a transient request failure."""

        delay = self.configuration.retries.calculate_delay(
            retry_number
        )

        await asyncio.sleep(delay)

    def _response_exceeds_limit(
        self,
        response: httpx.Response,
    ) -> bool:
        """Return whether a response exceeds the configured byte limit."""

        content_length = response.headers.get(
            "content-length"
        )

        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = None

            if (
                declared_length is not None
                and declared_length
                > self.configuration.maximum_response_bytes
            ):
                return True

        return (
            len(response.content)
            > self.configuration.maximum_response_bytes
        )

    def _raise_for_ollama_status(
        self,
        response: httpx.Response,
    ) -> None:
        """Raise an explicit exception for an unsuccessful Ollama response."""

        if 200 <= response.status_code < 300:
            return

        error_message = _extract_ollama_error_message(
            response
        )

        message = (
            f"Ollama API request failed with HTTP "
            f"{response.status_code}: {error_message}"
        )

        if _looks_like_model_not_found(error_message):
            raise OllamaModelNotFoundError(
                message,
                status_code=response.status_code,
                response_body=_safe_error_body(response),
            )

        raise OllamaHTTPError(
            message,
            status_code=response.status_code,
            response_body=_safe_error_body(response),
        )

    def _decode_json_response(
        self,
        response: httpx.Response,
    ) -> dict[str, Any]:
        """Decode and validate an Ollama JSON object response."""

        if self._response_exceeds_limit(response):
            raise OllamaResponseError(
                "The Ollama response exceeds the maximum permitted size "
                f"of {self.configuration.maximum_response_bytes} bytes."
            )

        content_type = response.headers.get(
            "content-type",
            "",
        ).casefold()

        if (
            content_type
            and "application/json" not in content_type
            and "application/x-ndjson" not in content_type
        ):
            LOGGER.warning(
                "Ollama returned an unexpected Content-Type: %s",
                content_type,
            )

        try:
            payload = response.json()
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            body = _safe_error_body(response)

            raise OllamaResponseError(
                "Ollama returned malformed JSON. Response body: "
                f"{body}"
            ) from exc

        if not isinstance(payload, dict):
            raise OllamaResponseError(
                "Ollama returned JSON that is not an object."
            )

        error_value = payload.get("error")

        if isinstance(error_value, str) and error_value.strip():
            message = error_value.strip()

            if _looks_like_model_not_found(message):
                raise OllamaModelNotFoundError(
                    f"Ollama model error: {message}",
                    status_code=response.status_code,
                    response_body=_safe_error_body(response),
                )

            raise OllamaResponseError(
                f"Ollama returned an error: {message}"
            )

        return payload

    async def _request_json(
        self,
        method: str,
        endpoint: OllamaEndpoint,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout: httpx.Timeout | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Send an Ollama request and return a validated JSON object."""

        self._ensure_open()

        maximum_attempts = (
            self.configuration.retries.maximum_retries + 1
            if retry
            else 1
        )

        last_exception: BaseException | None = None

        for attempt in range(maximum_attempts):
            try:
                response = await self._client.request(
                    method=method,
                    url=endpoint.value,
                    json=(
                        dict(payload)
                        if payload is not None
                        else None
                    ),
                    timeout=timeout,
                )

                if (
                    response.status_code
                    in RETRYABLE_STATUS_CODES
                    and attempt + 1 < maximum_attempts
                ):
                    LOGGER.warning(
                        "Transient Ollama HTTP status %s from %s; "
                        "retrying request.",
                        response.status_code,
                        endpoint.value,
                    )

                    await self._sleep_before_retry(
                        attempt
                    )
                    continue

                self._raise_for_ollama_status(response)

                return self._decode_json_response(
                    response
                )

            except asyncio.CancelledError as exc:
                raise OllamaRequestCancelledError(
                    "The Ollama request was cancelled."
                ) from exc

            except httpx.TimeoutException as exc:
                last_exception = exc

                if attempt + 1 < maximum_attempts:
                    LOGGER.warning(
                        "Ollama request to %s timed out; retrying.",
                        endpoint.value,
                    )

                    await self._sleep_before_retry(
                        attempt
                    )
                    continue

                raise OllamaTimeoutError(
                    "Ollama did not respond before the configured timeout "
                    f"for endpoint {endpoint.value}."
                ) from exc

            except (
                httpx.ConnectError,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
                httpx.LocalProtocolError,
            ) as exc:
                last_exception = exc

                if attempt + 1 < maximum_attempts:
                    LOGGER.warning(
                        "Ollama connection failure for %s; retrying: %s",
                        endpoint.value,
                        exc,
                    )

                    await self._sleep_before_retry(
                        attempt
                    )
                    continue

                raise OllamaUnavailableError(
                    "Cannot connect to the local Ollama service at "
                    f"{self.configuration.base_url}. Ensure Ollama is "
                    "running and listening on the configured address."
                ) from exc

            except httpx.RequestError as exc:
                last_exception = exc

                if attempt + 1 < maximum_attempts:
                    LOGGER.warning(
                        "Ollama transport error for %s; retrying: %s",
                        endpoint.value,
                        exc,
                    )

                    await self._sleep_before_retry(
                        attempt
                    )
                    continue

                raise OllamaUnavailableError(
                    f"Ollama request failed for {endpoint.value}: {exc}"
                ) from exc

        raise OllamaUnavailableError(
            "Ollama request failed after all retry attempts."
        ) from last_exception
    async def get_version(self) -> str:
        """Return the installed Ollama server version.

        Raises:
            OllamaUnavailableError:
                If the local service cannot be reached.
            OllamaTimeoutError:
                If the health request times out.
            OllamaResponseError:
                If the response does not contain a valid version.
        """

        payload = await self._request_json(
            method="GET",
            endpoint=OllamaEndpoint.VERSION,
            timeout=(
                self.configuration.timeouts.to_health_timeout()
            ),
            retry=False,
        )

        version_value = payload.get("version")

        if not isinstance(version_value, str):
            raise OllamaResponseError(
                "Ollama /api/version did not return a valid version."
            )

        version = version_value.strip()

        if not version:
            raise OllamaResponseError(
                "Ollama /api/version returned an empty version."
            )

        return version

    async def list_models(
        self,
    ) -> tuple[OllamaModelInformation, ...]:
        """Return all locally installed Ollama models.

        Results are sorted deterministically by model name.
        """

        payload = await self._request_json(
            method="GET",
            endpoint=OllamaEndpoint.TAGS,
            timeout=(
                self.configuration.timeouts.to_health_timeout()
            ),
            retry=False,
        )

        models_value = payload.get("models")

        if models_value is None:
            return ()

        if (
            not isinstance(models_value, Sequence)
            or isinstance(
                models_value,
                (str, bytes, bytearray),
            )
        ):
            raise OllamaResponseError(
                "Ollama /api/tags returned an invalid models collection."
            )

        models: list[OllamaModelInformation] = []

        for index, value in enumerate(models_value):
            if not isinstance(value, Mapping):
                LOGGER.warning(
                    "Ignored malformed Ollama model entry at index %s.",
                    index,
                )
                continue

            model_information = (
                OllamaModelInformation.from_api_data(value)
            )

            if not model_information.name:
                LOGGER.warning(
                    "Ignored Ollama model entry without a name at "
                    "index %s.",
                    index,
                )
                continue

            models.append(model_information)

        models.sort(
            key=lambda model_information: (
                model_information.name.casefold()
            )
        )

        return tuple(models)

    async def is_model_available(
        self,
        model: str,
    ) -> bool:
        """Return whether a model is installed locally.

        Model names are compared case-insensitively. A model name with an
        explicit tag, such as ``qwen2.5-coder:7b``, must match that tag.
        When the requested name has no tag, both the bare name and the
        default ``latest`` tag are accepted.
        """

        normalized_model = _validate_model_name(
            model
        ).casefold()

        installed_models = await self.list_models()

        requested_has_tag = ":" in normalized_model

        for installed_model in installed_models:
            candidate_names = {
                installed_model.name.casefold(),
            }

            if installed_model.model:
                candidate_names.add(
                    installed_model.model.casefold()
                )

            if normalized_model in candidate_names:
                return True

            if not requested_has_tag:
                if (
                    f"{normalized_model}:latest"
                    in candidate_names
                ):
                    return True

                for candidate_name in candidate_names:
                    bare_candidate = candidate_name.rsplit(
                        ":",
                        maxsplit=1,
                    )[0]

                    if bare_candidate == normalized_model:
                        return True

        return False

    async def check_connection(
        self,
        *,
        include_models: bool = True,
    ) -> OllamaHealthInformation:
        """Check whether Ollama is running and responding.

        The method never raises ordinary connection, timeout, HTTP, or
        malformed-response errors. Instead, it returns structured status
        information suitable for the frontend.

        Cancellation is not suppressed.
        """

        self._ensure_open()

        checked_at = utc_now()
        started_at = time.monotonic()

        version: str | None = None
        models: tuple[OllamaModelInformation, ...] = ()

        try:
            version = await self.get_version()

            if include_models:
                models = await self.list_models()

            response_time_ms = max(
                (time.monotonic() - started_at) * 1_000,
                0.0,
            )

            return OllamaHealthInformation(
                status=_coerce_connection_status(
                    available=True
                ),
                available=True,
                base_url=self.configuration.base_url,
                checked_at=checked_at,
                response_time_ms=response_time_ms,
                version=version,
                installed_models=models,
                error=None,
            )

        except OllamaRequestCancelledError:
            raise

        except asyncio.CancelledError:
            raise

        except OllamaTimeoutError as exc:
            response_time_ms = max(
                (time.monotonic() - started_at) * 1_000,
                0.0,
            )

            return OllamaHealthInformation(
                status=_coerce_connection_status(
                    available=False,
                    timeout=True,
                ),
                available=False,
                base_url=self.configuration.base_url,
                checked_at=checked_at,
                response_time_ms=response_time_ms,
                version=version,
                installed_models=models,
                error=str(exc),
            )

        except OllamaUnavailableError as exc:
            response_time_ms = max(
                (time.monotonic() - started_at) * 1_000,
                0.0,
            )

            return OllamaHealthInformation(
                status=_coerce_connection_status(
                    available=False
                ),
                available=False,
                base_url=self.configuration.base_url,
                checked_at=checked_at,
                response_time_ms=response_time_ms,
                version=version,
                installed_models=models,
                error=str(exc),
            )

        except OllamaServiceError as exc:
            response_time_ms = max(
                (time.monotonic() - started_at) * 1_000,
                0.0,
            )

            return OllamaHealthInformation(
                status=_coerce_connection_status(
                    available=False,
                    error=True,
                ),
                available=False,
                base_url=self.configuration.base_url,
                checked_at=checked_at,
                response_time_ms=response_time_ms,
                version=version,
                installed_models=models,
                error=str(exc),
            )

        except Exception as exc:
            LOGGER.exception(
                "Unexpected Ollama connection-check failure."
            )

            response_time_ms = max(
                (time.monotonic() - started_at) * 1_000,
                0.0,
            )

            return OllamaHealthInformation(
                status=_coerce_connection_status(
                    available=False,
                    error=True,
                ),
                available=False,
                base_url=self.configuration.base_url,
                checked_at=checked_at,
                response_time_ms=response_time_ms,
                version=version,
                installed_models=models,
                error=(
                    "Unexpected Ollama connection error: "
                    f"{exc}"
                ),
            )

    async def require_connection(
        self,
        *,
        include_models: bool = False,
    ) -> OllamaHealthInformation:
        """Require Ollama to be available or raise a service exception."""

        health = await self.check_connection(
            include_models=include_models
        )

        if not health.available:
            raise OllamaUnavailableError(
                health.error
                or (
                    "The local Ollama service is not "
                    "available."
                )
            )

        return health

    async def require_model(
        self,
        model: str,
    ) -> str:
        """Require a model to exist locally and return its normalized name."""

        normalized_model = _validate_model_name(model)

        try:
            available = await self.is_model_available(
                normalized_model
            )
        except OllamaServiceError:
            raise

        if not available:
            raise OllamaModelNotFoundError(
                "The requested Ollama model is not installed locally: "
                f"{normalized_model}",
                status_code=404,
                response_body=None,
            )

        return normalized_model

    @staticmethod
    def _validate_options(
        options: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Validate optional Ollama runtime options."""

        if options is None:
            return None

        if not isinstance(options, Mapping):
            raise OllamaConfigurationError(
                "Ollama options must be a mapping."
            )

        normalized_options: dict[str, Any] = {}

        for key, value in options.items():
            if not isinstance(key, str):
                raise OllamaConfigurationError(
                    "Every Ollama option name must be a string."
                )

            normalized_key = key.strip()

            if not normalized_key:
                raise OllamaConfigurationError(
                    "Ollama option names cannot be empty."
                )

            if "\x00" in normalized_key:
                raise OllamaConfigurationError(
                    "An Ollama option name contains a null byte."
                )

            try:
                json.dumps(
                    value,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise OllamaConfigurationError(
                    "Ollama option values must be JSON serializable. "
                    f"Invalid option: {normalized_key}"
                ) from exc

            normalized_options[normalized_key] = value

        return normalized_options

    @staticmethod
    def _validate_images(
        images: Sequence[str] | None,
    ) -> list[str] | None:
        """Validate optional base64 image strings."""

        if images is None:
            return None

        if isinstance(
            images,
            (str, bytes, bytearray),
        ):
            raise OllamaConfigurationError(
                "Ollama images must be provided as a sequence."
            )

        normalized_images: list[str] = []

        for index, image in enumerate(images):
            if not isinstance(image, str):
                raise OllamaConfigurationError(
                    f"Ollama image {index} must be a base64 string."
                )

            normalized_image = image.strip()

            if not normalized_image:
                raise OllamaConfigurationError(
                    f"Ollama image {index} cannot be empty."
                )

            if "\x00" in normalized_image:
                raise OllamaConfigurationError(
                    f"Ollama image {index} contains a null byte."
                )

            normalized_images.append(
                normalized_image
            )

        return normalized_images

    @staticmethod
    def _validate_format(
        output_format: (
            str
            | Mapping[str, Any]
            | type[BaseModel]
            | None
        ),
    ) -> str | dict[str, Any] | None:
        """Normalize a structured-output format.

        Accepted values:

        - None for ordinary text.
        - ``"json"`` for JSON mode.
        - A JSON Schema mapping.
        - A Pydantic v2 model class.
        """

        if output_format is None:
            return None

        if isinstance(output_format, str):
            normalized = output_format.strip().casefold()

            if normalized != "json":
                raise OllamaConfigurationError(
                    'The only supported string format is "json".'
                )

            return "json"

        if (
            isinstance(output_format, type)
            and issubclass(output_format, BaseModel)
        ):
            schema = output_format.model_json_schema()

            try:
                json.dumps(
                    schema,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise OllamaConfigurationError(
                    "The Pydantic model produced an invalid JSON Schema."
                ) from exc

            return schema

        if isinstance(output_format, Mapping):
            schema = dict(output_format)

            if not schema:
                raise OllamaConfigurationError(
                    "The JSON Schema cannot be empty."
                )

            try:
                json.dumps(
                    schema,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise OllamaConfigurationError(
                    "The structured-output schema must be valid JSON."
                ) from exc

            return schema

        raise OllamaConfigurationError(
            "output_format must be None, 'json', a JSON Schema mapping, "
            "or a Pydantic model class."
        )

    @staticmethod
    def _validate_keep_alive(
        keep_alive: str | int | None,
    ) -> str | int | None:
        """Validate the Ollama model keep-alive setting."""

        if keep_alive is None:
            return None

        if isinstance(keep_alive, bool):
            raise OllamaConfigurationError(
                "keep_alive must be a duration string or integer."
            )

        if isinstance(keep_alive, int):
            return keep_alive

        if isinstance(keep_alive, str):
            normalized = keep_alive.strip()

            if not normalized:
                raise OllamaConfigurationError(
                    "keep_alive cannot be an empty string."
                )

            if len(normalized) > 128:
                raise OllamaConfigurationError(
                    "keep_alive is too long."
                )

            if "\x00" in normalized:
                raise OllamaConfigurationError(
                    "keep_alive contains a null byte."
                )

            return normalized

        raise OllamaConfigurationError(
            "keep_alive must be a duration string, integer, or None."
        )

    @staticmethod
    def _validate_think(
        think: bool | str | None,
    ) -> bool | str | None:
        """Validate the optional Ollama thinking configuration."""

        if think is None or isinstance(think, bool):
            return think

        if isinstance(think, str):
            normalized = think.strip().casefold()

            if normalized not in {
                "low",
                "medium",
                "high",
            }:
                raise OllamaConfigurationError(
                    "think must be true, false, low, medium, or high."
                )

            return normalized

        raise OllamaConfigurationError(
            "think must be a boolean, supported thinking level, or None."
        )

    @staticmethod
    def _validate_request_timeout(
        timeout_seconds: float | None,
        *,
        configuration: OllamaClientConfiguration,
    ) -> httpx.Timeout | None:
        """Create an optional per-request HTTP timeout."""

        if timeout_seconds is None:
            return None

        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise OllamaConfigurationError(
                "timeout_seconds must be a finite positive number."
            )

        return httpx.Timeout(
            connect=min(
                configuration.timeouts.connect_seconds,
                timeout_seconds,
            ),
            read=timeout_seconds,
            write=min(
                configuration.timeouts.write_seconds,
                timeout_seconds,
            ),
            pool=min(
                configuration.timeouts.pool_seconds,
                timeout_seconds,
            ),
        )

    @staticmethod
    def _validate_json_serializable(
        value: Any,
        *,
        field_name: str,
    ) -> Any:
        """Require a value to be JSON serializable without NaN values."""

        try:
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise OllamaConfigurationError(
                f"{field_name} must be valid JSON-serializable data."
            ) from exc

        return value

    def _normalize_raw_response(
        self,
        *,
        endpoint: OllamaEndpoint,
        requested_model: str,
        payload: dict[str, Any],
        elapsed_seconds: float,
    ) -> OllamaRawResponse:
        """Normalize a successful generate or chat API response."""

        response_model_value = payload.get("model")

        response_model = (
            response_model_value.strip()
            if isinstance(response_model_value, str)
            and response_model_value.strip()
            else requested_model
        )

        if endpoint == OllamaEndpoint.GENERATE:
            content_value = payload.get("response")

            if not isinstance(content_value, str):
                raise OllamaResponseError(
                    "Ollama /api/generate did not return a string "
                    "in the response field."
                )

            content = content_value

        elif endpoint == OllamaEndpoint.CHAT:
            message_value = payload.get("message")

            if not isinstance(message_value, Mapping):
                raise OllamaResponseError(
                    "Ollama /api/chat did not return a valid "
                    "message object."
                )

            content_value = message_value.get("content")

            if not isinstance(content_value, str):
                raise OllamaResponseError(
                    "Ollama /api/chat did not return string content "
                    "inside the message object."
                )

            content = content_value

        else:
            raise OllamaResponseError(
                "Unsupported Ollama response endpoint."
            )

        done_value = payload.get("done")

        if not isinstance(done_value, bool):
            raise OllamaResponseError(
                "Ollama response did not contain a valid done flag."
            )

        if not done_value:
            raise OllamaResponseError(
                "Ollama returned an incomplete non-streaming response."
            )

        created_at_value = payload.get("created_at")
        done_reason_value = payload.get("done_reason")

        return OllamaRawResponse(
            endpoint=endpoint,
            model=response_model,
            content=content,
            raw_data=payload,
            created_at=(
                created_at_value
                if isinstance(created_at_value, str)
                else None
            ),
            done=done_value,
            done_reason=(
                done_reason_value
                if isinstance(done_reason_value, str)
                else None
            ),
            total_duration_nanoseconds=_optional_int(
                payload.get("total_duration")
            ),
            load_duration_nanoseconds=_optional_int(
                payload.get("load_duration")
            ),
            prompt_eval_count=_optional_int(
                payload.get("prompt_eval_count")
            ),
            prompt_eval_duration_nanoseconds=_optional_int(
                payload.get("prompt_eval_duration")
            ),
            eval_count=_optional_int(
                payload.get("eval_count")
            ),
            eval_duration_nanoseconds=_optional_int(
                payload.get("eval_duration")
            ),
            elapsed_seconds=max(
                elapsed_seconds,
                0.0,
            ),
        )

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        output_format: (
            str
            | Mapping[str, Any]
            | type[BaseModel]
            | None
        ) = None,
        options: Mapping[str, Any] | None = None,
        images: Sequence[str] | None = None,
        suffix: str | None = None,
        raw: bool = False,
        think: bool | str | None = None,
        keep_alive: str | int | None = None,
        timeout_seconds: float | None = None,
        verify_model: bool = False,
    ) -> OllamaRawResponse:
        """Generate a non-streaming response using /api/generate."""

        normalized_model = _validate_model_name(model)
        normalized_prompt = _validate_prompt(prompt)
        normalized_system = _validate_system_prompt(
            system_prompt
        )
        normalized_format = self._validate_format(
            output_format
        )
        normalized_options = self._validate_options(
            options
        )
        normalized_images = self._validate_images(
            images
        )
        normalized_keep_alive = self._validate_keep_alive(
            (
                self.configuration.default_keep_alive
                if keep_alive is None
                else keep_alive
            )
        )
        normalized_think = self._validate_think(
            think
        )

        if suffix is not None:
            if not isinstance(suffix, str):
                raise OllamaConfigurationError(
                    "suffix must be a string."
                )

            if "\x00" in suffix:
                raise OllamaConfigurationError(
                    "suffix contains a null byte."
                )

            if len(suffix) > MAX_PROMPT_CHARACTERS:
                raise OllamaConfigurationError(
                    "suffix exceeds the maximum permitted length."
                )

        if verify_model:
            await self.require_model(
                normalized_model
            )

        payload: dict[str, Any] = {
            "model": normalized_model,
            "prompt": normalized_prompt,
            "stream": False,
            "raw": bool(raw),
        }

        if normalized_system is not None:
            payload["system"] = normalized_system

        if normalized_format is not None:
            payload["format"] = normalized_format

        if normalized_options is not None:
            payload["options"] = normalized_options

        if normalized_images is not None:
            payload["images"] = normalized_images

        if suffix is not None:
            payload["suffix"] = suffix

        if normalized_think is not None:
            payload["think"] = normalized_think

        if normalized_keep_alive is not None:
            payload["keep_alive"] = normalized_keep_alive

        request_timeout = self._validate_request_timeout(
            timeout_seconds,
            configuration=self.configuration,
        )

        started_at = time.monotonic()

        response_payload = await self._request_json(
            method="POST",
            endpoint=OllamaEndpoint.GENERATE,
            payload=payload,
            timeout=request_timeout,
            retry=True,
        )

        elapsed_seconds = (
            time.monotonic() - started_at
        )

        return self._normalize_raw_response(
            endpoint=OllamaEndpoint.GENERATE,
            requested_model=normalized_model,
            payload=response_payload,
            elapsed_seconds=elapsed_seconds,
        )

    async def chat(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        output_format: (
            str
            | Mapping[str, Any]
            | type[BaseModel]
            | None
        ) = None,
        options: Mapping[str, Any] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        think: bool | str | None = None,
        keep_alive: str | int | None = None,
        timeout_seconds: float | None = None,
        verify_model: bool = False,
    ) -> OllamaRawResponse:
        """Generate a non-streaming response using /api/chat."""

        normalized_model = _validate_model_name(model)
        normalized_messages = _validate_messages(
            messages
        )
        normalized_format = self._validate_format(
            output_format
        )
        normalized_options = self._validate_options(
            options
        )
        normalized_keep_alive = self._validate_keep_alive(
            (
                self.configuration.default_keep_alive
                if keep_alive is None
                else keep_alive
            )
        )
        normalized_think = self._validate_think(
            think
        )

        normalized_tools: list[dict[str, Any]] | None = None

        if tools is not None:
            if isinstance(
                tools,
                (str, bytes, bytearray),
            ):
                raise OllamaConfigurationError(
                    "tools must be a sequence of objects."
                )

            normalized_tools = []

            for index, tool in enumerate(tools):
                if not isinstance(tool, Mapping):
                    raise OllamaConfigurationError(
                        f"Tool {index} must be an object."
                    )

                normalized_tool = dict(tool)

                self._validate_json_serializable(
                    normalized_tool,
                    field_name=f"Tool {index}",
                )

                normalized_tools.append(
                    normalized_tool
                )

        if verify_model:
            await self.require_model(
                normalized_model
            )

        payload: dict[str, Any] = {
            "model": normalized_model,
            "messages": normalized_messages,
            "stream": False,
        }

        if normalized_format is not None:
            payload["format"] = normalized_format

        if normalized_options is not None:
            payload["options"] = normalized_options

        if normalized_tools is not None:
            payload["tools"] = normalized_tools

        if normalized_think is not None:
            payload["think"] = normalized_think

        if normalized_keep_alive is not None:
            payload["keep_alive"] = normalized_keep_alive

        request_timeout = self._validate_request_timeout(
            timeout_seconds,
            configuration=self.configuration,
        )

        started_at = time.monotonic()

        response_payload = await self._request_json(
            method="POST",
            endpoint=OllamaEndpoint.CHAT,
            payload=payload,
            timeout=request_timeout,
            retry=True,
        )

        elapsed_seconds = (
            time.monotonic() - started_at
        )

        return self._normalize_raw_response(
            endpoint=OllamaEndpoint.CHAT,
            requested_model=normalized_model,
            payload=response_payload,
            elapsed_seconds=elapsed_seconds,
        )

    @staticmethod
    def _remove_json_code_fence(
        content: str,
    ) -> str:
        """Remove a surrounding Markdown JSON code fence."""

        match = JSON_CODE_FENCE_PATTERN.match(
            content
        )

        if match is None:
            return content.strip()

        return match.group("body").strip()

    @staticmethod
    def _extract_balanced_json(
        content: str,
    ) -> str | None:
        """Extract the first balanced JSON object or array.

        The scanner respects JSON string escaping and therefore does not
        terminate on braces or brackets that appear inside strings.
        """

        start_index: int | None = None
        opening_character: str | None = None
        closing_character: str | None = None
        depth = 0
        in_string = False
        escaped = False

        for index, character in enumerate(content):
            if start_index is None:
                if character == "{":
                    start_index = index
                    opening_character = "{"
                    closing_character = "}"
                    depth = 1
                    continue

                if character == "[":
                    start_index = index
                    opening_character = "["
                    closing_character = "]"
                    depth = 1
                    continue

                continue

            if in_string:
                if escaped:
                    escaped = False
                    continue

                if character == "\\":
                    escaped = True
                    continue

                if character == '"':
                    in_string = False

                continue

            if character == '"':
                in_string = True
                continue

            if character == opening_character:
                depth += 1
                continue

            if character == closing_character:
                depth -= 1

                if depth == 0:
                    return content[
                        start_index:index + 1
                    ]

        return None

    @classmethod
    def parse_structured_content(
        cls,
        content: str,
        *,
        require_object: bool = False,
    ) -> dict[str, Any] | list[Any]:
        """Parse structured JSON returned by an Ollama model.

        The parser first attempts strict decoding. It then supports one
        surrounding Markdown JSON fence and, as a final compatibility step,
        extracts the first balanced JSON object or array.
        """

        if not isinstance(content, str):
            raise OllamaStructuredOutputError(
                "Structured Ollama content must be a string."
            )

        normalized_content = cls._remove_json_code_fence(
            content
        )

        if not normalized_content:
            raise OllamaStructuredOutputError(
                "Ollama returned empty structured content."
            )

        parsed: Any

        try:
            parsed = json.loads(
                normalized_content
            )
        except json.JSONDecodeError as first_error:
            extracted = cls._extract_balanced_json(
                normalized_content
            )

            if extracted is None:
                object_match = JSON_OBJECT_PATTERN.search(
                    normalized_content
                )
                array_match = JSON_ARRAY_PATTERN.search(
                    normalized_content
                )

                matches = [
                    match
                    for match in (
                        object_match,
                        array_match,
                    )
                    if match is not None
                ]

                if matches:
                    earliest_match = min(
                        matches,
                        key=lambda match: match.start(),
                    )
                    extracted = earliest_match.group(0)

            if extracted is None:
                raise OllamaStructuredOutputError(
                    "Ollama did not return a recognizable JSON object "
                    "or array."
                ) from first_error

            try:
                parsed = json.loads(extracted)
            except json.JSONDecodeError as second_error:
                raise OllamaStructuredOutputError(
                    "Ollama returned malformed structured JSON: "
                    f"{second_error.msg} at line "
                    f"{second_error.lineno}, column "
                    f"{second_error.colno}."
                ) from second_error

        if not isinstance(parsed, (dict, list)):
            raise OllamaStructuredOutputError(
                "Ollama structured output must be a JSON object or array."
            )

        if require_object and not isinstance(parsed, dict):
            raise OllamaStructuredOutputError(
                "Ollama structured output must be a JSON object."
            )

        return parsed

    @staticmethod
    def _schema_prompt_instruction(
        schema: Mapping[str, Any] | None,
    ) -> str:
        """Build a concise structured-output instruction for the model."""

        if schema is None:
            return (
                "Return only valid JSON. Do not use Markdown, code fences, "
                "comments, or explanatory text."
            )

        serialized_schema = json.dumps(
            dict(schema),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )

        return (
            "Return only valid JSON matching the following JSON Schema. "
            "Do not use Markdown, code fences, comments, or explanatory "
            "text.\n\nJSON Schema:\n"
            f"{serialized_schema}"
        )

    @staticmethod
    def _append_instruction_to_prompt(
        prompt: str,
        instruction: str,
    ) -> str:
        """Append a structured-output instruction without duplication."""

        normalized_prompt = prompt.rstrip()
        normalized_instruction = instruction.strip()

        return (
            f"{normalized_prompt}\n\n"
            f"{normalized_instruction}"
        )

    @staticmethod
    def _append_instruction_to_messages(
        messages: Sequence[Mapping[str, Any]],
        instruction: str,
    ) -> list[dict[str, Any]]:
        """Append a structured-output instruction to chat messages."""

        normalized_messages = _validate_messages(
            messages
        )

        updated_messages = [
            dict(message)
            for message in normalized_messages
        ]

        if (
            updated_messages
            and updated_messages[-1]["role"] == "user"
        ):
            updated_messages[-1]["content"] = (
                updated_messages[-1]["content"].rstrip()
                + "\n\n"
                + instruction.strip()
            )
        else:
            updated_messages.append(
                {
                    "role": "user",
                    "content": instruction.strip(),
                }
            )

        return updated_messages

    async def generate_structured(
        self,
        *,
        model: str,
        prompt: str,
        response_model: type[StructuredModelT] | None = None,
        json_schema: Mapping[str, Any] | None = None,
        system_prompt: str | None = None,
        options: Mapping[str, Any] | None = None,
        images: Sequence[str] | None = None,
        keep_alive: str | int | None = None,
        timeout_seconds: float | None = None,
        verify_model: bool = False,
        include_schema_in_prompt: bool = True,
        require_object: bool = True,
    ) -> OllamaStructuredResponse:
        """Generate and validate structured JSON through /api/generate.

        ``response_model`` and ``json_schema`` are mutually exclusive.
        When a Pydantic model is supplied, its JSON Schema is sent to Ollama
        and the returned data is validated using Pydantic v2.
        """

        if (
            response_model is not None
            and json_schema is not None
        ):
            raise OllamaConfigurationError(
                "response_model and json_schema cannot both be supplied."
            )

        effective_schema: dict[str, Any] | None
        validated_model_type: type[StructuredModelT] | None = None

        if response_model is not None:
            if (
                not isinstance(response_model, type)
                or not issubclass(
                    response_model,
                    BaseModel,
                )
            ):
                raise OllamaConfigurationError(
                    "response_model must be a Pydantic BaseModel class."
                )

            validated_model_type = response_model
            effective_schema = (
                response_model.model_json_schema()
            )
        elif json_schema is not None:
            effective_schema = self._validate_format(
                json_schema
            )

            if not isinstance(
                effective_schema,
                dict,
            ):
                raise OllamaConfigurationError(
                    "json_schema must produce a JSON Schema object."
                )
        else:
            effective_schema = None

        effective_prompt = _validate_prompt(
            prompt
        )

        if include_schema_in_prompt:
            instruction = self._schema_prompt_instruction(
                effective_schema
            )

            effective_prompt = (
                self._append_instruction_to_prompt(
                    effective_prompt,
                    instruction,
                )
            )

        raw_response = await self.generate(
            model=model,
            prompt=effective_prompt,
            system_prompt=system_prompt,
            output_format="json",
            options=options,
            images=images,
            raw=False,
            keep_alive=keep_alive,
            timeout_seconds=timeout_seconds,
            verify_model=verify_model,
        )

        data = self.parse_structured_content(
            raw_response.content,
            require_object=(
                require_object
                or validated_model_type is not None
            ),
        )

        validated_model: BaseModel | None = None

        if validated_model_type is not None:
            try:
                validated_model = (
                    validated_model_type.model_validate(
                        data
                    )
                )
            except ValidationError as exc:
                raise OllamaResponseValidationError(
                    "Ollama structured output failed "
                    f"{validated_model_type.__name__} validation: "
                    f"{exc}"
                ) from exc

        return OllamaStructuredResponse(
            raw_response=raw_response,
            data=data,
            validated_model=validated_model,
        )

    async def chat_structured(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        response_model: type[StructuredModelT] | None = None,
        json_schema: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        keep_alive: str | int | None = None,
        timeout_seconds: float | None = None,
        verify_model: bool = False,
        include_schema_in_prompt: bool = True,
        require_object: bool = True,
    ) -> OllamaStructuredResponse:
        """Generate and validate structured JSON through /api/chat."""

        if (
            response_model is not None
            and json_schema is not None
        ):
            raise OllamaConfigurationError(
                "response_model and json_schema cannot both be supplied."
            )

        effective_schema: dict[str, Any] | None
        validated_model_type: type[StructuredModelT] | None = None

        if response_model is not None:
            if (
                not isinstance(response_model, type)
                or not issubclass(
                    response_model,
                    BaseModel,
                )
            ):
                raise OllamaConfigurationError(
                    "response_model must be a Pydantic BaseModel class."
                )

            validated_model_type = response_model
            effective_schema = (
                response_model.model_json_schema()
            )
        elif json_schema is not None:
            normalized_schema = self._validate_format(
                json_schema
            )

            if not isinstance(
                normalized_schema,
                dict,
            ):
                raise OllamaConfigurationError(
                    "json_schema must produce a JSON Schema object."
                )

            effective_schema = normalized_schema
        else:
            effective_schema = None

        effective_messages = _validate_messages(
            messages
        )

        if include_schema_in_prompt:
            instruction = self._schema_prompt_instruction(
                effective_schema
            )

            effective_messages = (
                self._append_instruction_to_messages(
                    effective_messages,
                    instruction,
                )
            )

        raw_response = await self.chat(
            model=model,
            messages=effective_messages,
            output_format="json",
            options=options,
            tools=tools,
            keep_alive=keep_alive,
            timeout_seconds=timeout_seconds,
            verify_model=verify_model,
        )

        data = self.parse_structured_content(
            raw_response.content,
            require_object=(
                require_object
                or validated_model_type is not None
            ),
        )

        validated_model: BaseModel | None = None

        if validated_model_type is not None:
            try:
                validated_model = (
                    validated_model_type.model_validate(
                        data
                    )
                )
            except ValidationError as exc:
                raise OllamaResponseValidationError(
                    "Ollama structured output failed "
                    f"{validated_model_type.__name__} validation: "
                    f"{exc}"
                ) from exc

        return OllamaStructuredResponse(
            raw_response=raw_response,
            data=data,
            validated_model=validated_model,
        )

    async def generate_json(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        options: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        verify_model: bool = False,
        require_object: bool = True,
    ) -> dict[str, Any] | list[Any]:
        """Convenience method returning only parsed generate JSON data."""

        response = await self.generate_structured(
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            options=options,
            timeout_seconds=timeout_seconds,
            verify_model=verify_model,
            require_object=require_object,
        )

        return response.data

    async def chat_json(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        options: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        verify_model: bool = False,
        require_object: bool = True,
    ) -> dict[str, Any] | list[Any]:
        """Convenience method returning only parsed chat JSON data."""

        response = await self.chat_structured(
            model=model,
            messages=messages,
            options=options,
            timeout_seconds=timeout_seconds,
            verify_model=verify_model,
            require_object=require_object,
        )

        return response.data

    async def generate_validated(
        self,
        *,
        model: str,
        prompt: str,
        response_model: type[StructuredModelT],
        system_prompt: str | None = None,
        options: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        verify_model: bool = False,
    ) -> StructuredModelT:
        """Generate structured output and return a validated model."""

        response = await self.generate_structured(
            model=model,
            prompt=prompt,
            response_model=response_model,
            system_prompt=system_prompt,
            options=options,
            timeout_seconds=timeout_seconds,
            verify_model=verify_model,
        )

        validated_model = response.validated_model

        if validated_model is None:
            raise OllamaResponseValidationError(
                "Structured generation did not produce a validated model."
            )

        if not isinstance(
            validated_model,
            response_model,
        ):
            raise OllamaResponseValidationError(
                "Structured generation returned an unexpected model type."
            )

        return validated_model

    async def chat_validated(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, Any]],
        response_model: type[StructuredModelT],
        options: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        verify_model: bool = False,
    ) -> StructuredModelT:
        """Chat with Ollama and return a validated Pydantic model."""

        response = await self.chat_structured(
            model=model,
            messages=messages,
            response_model=response_model,
            options=options,
            timeout_seconds=timeout_seconds,
            verify_model=verify_model,
        )

        validated_model = response.validated_model

        if validated_model is None:
            raise OllamaResponseValidationError(
                "Structured chat did not produce a validated model."
            )

        if not isinstance(
            validated_model,
            response_model,
        ):
            raise OllamaResponseValidationError(
                "Structured chat returned an unexpected model type."
            )

        return validated_model


def create_ollama_service(
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    allow_non_local_host: bool = False,
    verify_tls: bool = True,
    follow_redirects: bool = False,
    connect_timeout_seconds: float = (
        DEFAULT_CONNECT_TIMEOUT_SECONDS
    ),
    read_timeout_seconds: float = (
        DEFAULT_READ_TIMEOUT_SECONDS
    ),
    write_timeout_seconds: float = (
        DEFAULT_WRITE_TIMEOUT_SECONDS
    ),
    pool_timeout_seconds: float = (
        DEFAULT_POOL_TIMEOUT_SECONDS
    ),
    health_timeout_seconds: float = (
        DEFAULT_HEALTH_TIMEOUT_SECONDS
    ),
    maximum_retries: int = DEFAULT_MAX_RETRIES,
    retry_base_delay_seconds: float = (
        DEFAULT_RETRY_BASE_DELAY_SECONDS
    ),
    retry_max_delay_seconds: float = (
        DEFAULT_RETRY_MAX_DELAY_SECONDS
    ),
    maximum_response_bytes: int = (
        DEFAULT_MAX_RESPONSE_BYTES
    ),
    default_keep_alive: str | int | None = (
        DEFAULT_KEEP_ALIVE
    ),
) -> OllamaService:
    """Create a configured OllamaService instance.

    The returned service owns its HTTP client and must be closed during
    application shutdown.
    """

    timeout_configuration = (
        OllamaTimeoutConfiguration(
            connect_seconds=connect_timeout_seconds,
            read_seconds=read_timeout_seconds,
            write_seconds=write_timeout_seconds,
            pool_seconds=pool_timeout_seconds,
            health_seconds=health_timeout_seconds,
        )
    )

    retry_configuration = (
        OllamaRetryConfiguration(
            maximum_retries=maximum_retries,
            base_delay_seconds=(
                retry_base_delay_seconds
            ),
            maximum_delay_seconds=(
                retry_max_delay_seconds
            ),
            use_jitter=True,
        )
    )

    client_configuration = (
        OllamaClientConfiguration(
            base_url=base_url,
            allow_non_local_host=(
                allow_non_local_host
            ),
            verify_tls=verify_tls,
            follow_redirects=follow_redirects,
            maximum_response_bytes=(
                maximum_response_bytes
            ),
            default_keep_alive=(
                default_keep_alive
            ),
            timeouts=timeout_configuration,
            retries=retry_configuration,
        )
    )

    return OllamaService(
        configuration=client_configuration
    )


async def check_ollama_connection(
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    include_models: bool = True,
) -> OllamaHealthInformation:
    """Perform a one-time Ollama connection check."""

    async with create_ollama_service(
        base_url=base_url
    ) as service:
        return await service.check_connection(
            include_models=include_models
        )


async def list_ollama_models(
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
) -> tuple[OllamaModelInformation, ...]:
    """Perform a one-time query for locally installed models."""

    async with create_ollama_service(
        base_url=base_url
    ) as service:
        return await service.list_models()


async def generate_ollama_json(
    *,
    model: str,
    prompt: str,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    system_prompt: str | None = None,
    json_schema: Mapping[str, Any] | None = None,
    timeout_seconds: float | None = None,
    verify_model: bool = False,
) -> dict[str, Any] | list[Any]:
    """Perform one structured JSON generation request."""

    async with create_ollama_service(
        base_url=base_url
    ) as service:
        response = await service.generate_structured(
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            json_schema=json_schema,
            timeout_seconds=timeout_seconds,
            verify_model=verify_model,
            require_object=True,
        )

        return response.data


async def chat_ollama_json(
    *,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    json_schema: Mapping[str, Any] | None = None,
    timeout_seconds: float | None = None,
    verify_model: bool = False,
) -> dict[str, Any] | list[Any]:
    """Perform one structured JSON chat request."""

    async with create_ollama_service(
        base_url=base_url
    ) as service:
        response = await service.chat_structured(
            model=model,
            messages=messages,
            json_schema=json_schema,
            timeout_seconds=timeout_seconds,
            verify_model=verify_model,
            require_object=True,
        )

        return response.data


__all__ = [
    "DEFAULT_OLLAMA_BASE_URL",
    "OllamaClientConfiguration",
    "OllamaConfigurationError",
    "OllamaEndpoint",
    "OllamaHTTPError",
    "OllamaHealthInformation",
    "OllamaModelInformation",
    "OllamaModelNotFoundError",
    "OllamaRawResponse",
    "OllamaRequestCancelledError",
    "OllamaResponseError",
    "OllamaResponseValidationError",
    "OllamaRetryConfiguration",
    "OllamaService",
    "OllamaServiceError",
    "OllamaStructuredOutputError",
    "OllamaStructuredResponse",
    "OllamaTimeoutConfiguration",
    "OllamaTimeoutError",
    "OllamaUnavailableError",
    "chat_ollama_json",
    "check_ollama_connection",
    "create_ollama_service",
    "generate_ollama_json",
    "list_ollama_models",
]
