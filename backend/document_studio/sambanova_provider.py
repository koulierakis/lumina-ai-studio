"""Strict, mockable SambaNova Cloud transport for Document Studio generation.

SambaNova is consumed through its OpenAI-compatible Chat Completions API. The
base URL is never invented: ``SAMBANOVA_BASE_URL`` is required and defines the
API root exactly as the operator supplies it (e.g. ``https://api.sambanova.ai/v1``);
the documented ``/chat/completions`` path is appended. Credentials (``SAMBANOVA_API_KEY``)
and the model (``SAMBANOVA_MODEL``) are read lazily from the environment.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from .document_ai_provider import (
    DocumentAIProvider,
    DocumentAIProviderError,
    DocumentAIProviderTimeout,
    MalformedDocumentAIResponse,
)
from .natural_creation import NaturalProviderOutput

DEFAULT_SAMBANOVA_MODEL = "Qwen2.5-Coder-32B-Instruct"
CHAT_COMPLETIONS_PATH = "/chat/completions"
DEFAULT_OVERALL_TIMEOUT_SECONDS = 45.0
MAX_OVERALL_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_ATTEMPTS = 2
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class SambaNovaProviderUnavailable(DocumentAIProviderError):
    """Raised when SambaNova is not configured or cannot be reached."""


class SambaNovaProviderHTTPError(DocumentAIProviderError):
    """Sanitized HTTP failure without request or credential material."""

    def __init__(self, status_code: int, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


async def _default_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


class SambaNovaDocumentProvider(DocumentAIProvider):
    """OpenAI-compatible SambaNova provider returning strict natural-document output."""

    name = "sambanova"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        overall_timeout_seconds: float = DEFAULT_OVERALL_TIMEOUT_SECONDS,
        sleeper: Callable[[float], Awaitable[None]] = _default_sleep,
    ) -> None:
        self._injected_api_key = api_key
        self._injected_base_url = (base_url or "").strip().rstrip("/")
        self.model = (
            model
            or os.getenv("SAMBANOVA_MODEL", DEFAULT_SAMBANOVA_MODEL).strip()
            or DEFAULT_SAMBANOVA_MODEL
        )
        self._client = client
        self.max_attempts = min(max(int(max_attempts), 1), 4)
        self.overall_timeout_seconds = min(
            max(float(overall_timeout_seconds), 0.1), MAX_OVERALL_TIMEOUT_SECONDS
        )
        self._sleep = sleeper

    @property
    def base_url(self) -> str:
        """Required endpoint root; never a hard-coded default."""
        configured_base = self._injected_base_url or os.getenv(
            "SAMBANOVA_BASE_URL", ""
        ).strip().rstrip("/")
        if configured_base:
            self._validate_base_url(configured_base)
        return configured_base

    @property
    def chat_completions_url(self) -> str:
        return self.base_url + CHAT_COMPLETIONS_PATH

    @property
    def api_key(self) -> str:
        """Read environment credentials only when state or generation is requested."""
        if self._injected_api_key is not None:
            return self._injected_api_key.strip()
        return os.getenv("SAMBANOVA_API_KEY", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and bool(self.base_url)

    @staticmethod
    def _validate_base_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("SambaNova base URL must be an absolute HTTPS URL")

    async def status(self) -> dict[str, Any]:
        base_url = self.base_url
        return {
            "name": self.name,
            "configured": self.configured,
            "available": self.configured,
            "model": self.model,
            "endpoint": (base_url + CHAT_COMPLETIONS_PATH) if base_url else "",
            "network_checked": False,
            "error": None if self.configured else "SambaNova is not configured",
        }

    @staticmethod
    def _system_prompt() -> str:
        schema = json.dumps(
            NaturalProviderOutput.model_json_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
        return (
            "Return exactly one JSON object (no Markdown, no commentary) conforming to this JSON "
            f"JSON Schema: {schema}. Use only verified facts and explicit user facts supplied in "
            "context. Every factual claim must declare origin as verified, user, or generated. "
            "Never label unsupported content verified or user. Unknown identity, legal, "
            "regulatory, banking, ownership, address, or financial values must remain contextual "
            "square-bracket placeholders."
        )

    def _payload(self, request: str, context: dict[str, Any]) -> dict[str, Any]:
        safe_context = {
            "document_type": context.get("document_type"),
            "document_title": context.get("document_title"),
            "category": context.get("category"),
            "language": context.get("language"),
            "tone": context.get("tone"),
            "style": context.get("style"),
            "verified_facts": context.get("verified_facts", {}),
            "fact_provenance": context.get("fact_provenance", {}),
            "user_supplied_facts": context.get("user_supplied_facts", {}),
            "intentional_blank_fields": context.get("intentional_blank_fields", []),
            "fact_safety": context.get("fact_safety"),
        }
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"request": request, "context": safe_context},
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            value = response.headers.get("Retry-After")
            if value:
                try:
                    return min(max(float(value), 0.0), 1.0)
                except ValueError:
                    pass
        return min(0.05 * attempt, 0.2)

    async def _post(self, payload: dict[str, Any], timeout: float) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "LUMINA-Document-Studio/2",
        }
        if self._client is not None:
            return await self._client.post(
                self.chat_completions_url,
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(timeout),
            )
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            return await client.post(
                self.chat_completions_url, json=payload, headers=headers
            )

    async def generate_document(
        self, request: str, context: dict[str, Any]
    ) -> NaturalProviderOutput:
        if not self.configured:
            raise SambaNovaProviderUnavailable("SambaNova is not configured")
        payload = self._payload(request, context)
        requested_timeout = context.get("timeout_seconds", self.overall_timeout_seconds)
        overall_timeout = min(
            max(float(requested_timeout), 0.1),
            self.overall_timeout_seconds,
            MAX_OVERALL_TIMEOUT_SECONDS,
        )
        deadline = time.monotonic() + overall_timeout
        last_failure: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DocumentAIProviderTimeout(
                    "SambaNova generation exceeded its overall deadline"
                )
            response: httpx.Response | None = None
            try:
                response = await asyncio.wait_for(
                    self._post(payload, remaining), timeout=remaining
                )
            except (TimeoutError, httpx.TimeoutException) as exc:
                last_failure = exc
                if attempt >= self.max_attempts:
                    raise DocumentAIProviderTimeout(
                        "SambaNova generation timed out"
                    ) from exc
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last_failure = exc
                if attempt >= self.max_attempts:
                    raise SambaNovaProviderUnavailable("SambaNova is unavailable") from exc
            else:
                if response.status_code >= 400:
                    retryable = response.status_code in TRANSIENT_STATUS_CODES
                    error = SambaNovaProviderHTTPError(
                        response.status_code,
                        self._safe_http_message(response.status_code),
                        retryable=retryable,
                    )
                    if not retryable or attempt >= self.max_attempts:
                        raise error
                    last_failure = error
                else:
                    return self._parse_response(response)

            if attempt < self.max_attempts:
                delay = self._retry_delay(response, attempt)
                remaining = deadline - time.monotonic()
                if remaining <= delay:
                    raise DocumentAIProviderTimeout(
                        "SambaNova generation exceeded its overall deadline"
                    ) from last_failure
                await self._sleep(delay)

        raise SambaNovaProviderUnavailable("SambaNova generation failed") from last_failure

    @staticmethod
    def _safe_http_message(status_code: int) -> str:
        return {
            400: "SambaNova rejected the generation request",
            401: "SambaNova authentication failed",
            403: "SambaNova access was denied",
            404: "SambaNova endpoint or model was not found",
            429: "SambaNova rate limit was reached",
        }.get(
            status_code,
            "SambaNova service failed" if status_code >= 500 else "SambaNova request failed",
        )

    @staticmethod
    def _parse_response(response: httpx.Response) -> NaturalProviderOutput:
        try:
            envelope = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise MalformedDocumentAIResponse("SambaNova returned malformed JSON") from exc
        try:
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise MalformedDocumentAIResponse(
                "SambaNova returned an invalid response envelope"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise MalformedDocumentAIResponse("SambaNova returned empty structured content")
        try:
            document_payload = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MalformedDocumentAIResponse(
                "SambaNova returned malformed structured content"
            ) from exc
        if not isinstance(document_payload, dict):
            raise MalformedDocumentAIResponse("SambaNova structured content must be an object")
        try:
            return NaturalProviderOutput.model_validate(document_payload, strict=True)
        except ValueError as exc:
            raise MalformedDocumentAIResponse(
                "SambaNova returned invalid typed document output"
            ) from exc