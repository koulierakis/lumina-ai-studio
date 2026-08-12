"""Strict, mockable Groq transport for Document Studio generation."""

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

DEFAULT_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_OVERALL_TIMEOUT_SECONDS = 45.0
MAX_OVERALL_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_ATTEMPTS = 2
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class GroqProviderUnavailable(DocumentAIProviderError):
    """Raised when Groq is not configured or cannot be reached."""


class GroqProviderHTTPError(DocumentAIProviderError):
    """Sanitized HTTP failure without request or credential material."""

    def __init__(self, status_code: int, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


async def _default_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


class GroqDocumentProvider(DocumentAIProvider):
    """OpenAI-compatible Groq provider returning strict natural-document output."""

    name = "groq"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        api_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        overall_timeout_seconds: float = DEFAULT_OVERALL_TIMEOUT_SECONDS,
        sleeper: Callable[[float], Awaitable[None]] = _default_sleep,
    ) -> None:
        self._injected_api_key = api_key
        self.model = model or os.getenv("GROQ_DOCUMENT_MODEL", DEFAULT_GROQ_MODEL)
        self.api_url = api_url or os.getenv("GROQ_API_URL", DEFAULT_GROQ_API_URL)
        self._client = client
        self.max_attempts = min(max(int(max_attempts), 1), 4)
        self.overall_timeout_seconds = min(
            max(float(overall_timeout_seconds), 0.1), MAX_OVERALL_TIMEOUT_SECONDS
        )
        self._sleep = sleeper
        self._validate_api_url(self.api_url)

    @property
    def api_key(self) -> str:
        """Read environment credentials only when provider state or generation is requested."""
        if self._injected_api_key is not None:
            return self._injected_api_key.strip()
        return os.getenv("GROQ_API_KEY", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _validate_api_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Groq API URL must be an absolute HTTPS URL")

    async def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configured": self.configured,
            "available": self.configured,
            "model": self.model,
            "network_checked": False,
            "error": None if self.configured else "Groq is not configured",
        }

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Return exactly one JSON object matching the supplied schema. Use only verified facts "
            "and explicit user facts supplied in context. Every factual claim must declare origin "
            "as verified, user, or generated. Never label unsupported content verified or user. "
            "Unknown identity, legal, regulatory, banking, ownership, address, or financial values "
            "must remain contextual square-bracket placeholders. Return no Markdown or commentary."
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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "lumina_natural_document",
                    "strict": True,
                    "schema": NaturalProviderOutput.model_json_schema(),
                },
            },
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
                self.api_url,
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(timeout),
            )
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            return await client.post(self.api_url, json=payload, headers=headers)

    async def generate_document(
        self, request: str, context: dict[str, Any]
    ) -> NaturalProviderOutput:
        if not self.configured:
            raise GroqProviderUnavailable("Groq is not configured")
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
                raise DocumentAIProviderTimeout("Groq generation exceeded its overall deadline")
            response: httpx.Response | None = None
            try:
                response = await asyncio.wait_for(self._post(payload, remaining), timeout=remaining)
            except (TimeoutError, httpx.TimeoutException) as exc:
                last_failure = exc
                if attempt >= self.max_attempts:
                    raise DocumentAIProviderTimeout("Groq generation timed out") from exc
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                last_failure = exc
                if attempt >= self.max_attempts:
                    raise GroqProviderUnavailable("Groq is unavailable") from exc
            else:
                if response.status_code >= 400:
                    retryable = response.status_code in TRANSIENT_STATUS_CODES
                    error = GroqProviderHTTPError(
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
                        "Groq generation exceeded its overall deadline"
                    ) from last_failure
                await self._sleep(delay)

        raise GroqProviderUnavailable("Groq generation failed") from last_failure

    @staticmethod
    def _safe_http_message(status_code: int) -> str:
        return {
            400: "Groq rejected the generation request",
            401: "Groq authentication failed",
            403: "Groq access was denied",
            404: "Groq endpoint or model was not found",
            429: "Groq rate limit was reached",
        }.get(
            status_code,
            "Groq service failed" if status_code >= 500 else "Groq request failed",
        )

    @staticmethod
    def _parse_response(response: httpx.Response) -> NaturalProviderOutput:
        try:
            envelope = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise MalformedDocumentAIResponse("Groq returned malformed JSON") from exc
        try:
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise MalformedDocumentAIResponse("Groq returned an invalid response envelope") from exc
        if not isinstance(content, str) or not content.strip():
            raise MalformedDocumentAIResponse("Groq returned empty structured content")
        try:
            document_payload = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MalformedDocumentAIResponse("Groq returned malformed structured content") from exc
        if not isinstance(document_payload, dict):
            raise MalformedDocumentAIResponse("Groq structured content must be an object")
        try:
            return NaturalProviderOutput.model_validate(document_payload, strict=True)
        except ValueError as exc:
            raise MalformedDocumentAIResponse(
                "Groq returned invalid typed document output"
            ) from exc
