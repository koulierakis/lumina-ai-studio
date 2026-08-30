"""Lazy, bounded Ollama adapter owned by Document Studio.

This module intentionally talks to Ollama directly instead of importing the
Code Builder subsystem. Documents must remain independently runnable.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_DOCUMENT_MODEL = "qwen2.5-coder:7b"
AVAILABILITY_TIMEOUT_SECONDS = 10.0
MAX_GENERATION_TIMEOUT_SECONDS = 180.0


class DocumentGenerationResult(BaseModel):
    content: str
    model_used: str
    provider: str = "ollama"
    elapsed_seconds: float
    success: bool
    error: str | None = None


class OllamaDocumentAdapter:
    """Document-specific Ollama client with bounded requests and lazy startup."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        ollama_url: str | None = None,
    ) -> None:
        self.ollama_url = (ollama_url or os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL)).rstrip("/")
        self._client = client
        self._owns_client = client is None

    @property
    def document_model(self) -> str:
        return os.getenv("OLLAMA_DOCUMENT_MODEL", DEFAULT_DOCUMENT_MODEL).strip() or DEFAULT_DOCUMENT_MODEL

    @property
    def structured_document_model(self) -> str:
        configured = os.getenv("OLLAMA_STRUCTURED_DOCUMENT_MODEL", "").strip()
        return configured or self.document_model

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.ollama_url)
        return self._client

    @staticmethod
    def _bounded_timeout(timeout_seconds: float) -> float:
        try:
            requested = float(timeout_seconds)
        except (TypeError, ValueError):
            requested = MAX_GENERATION_TIMEOUT_SECONDS
        return min(max(requested, 0.1), MAX_GENERATION_TIMEOUT_SECONDS)

    @staticmethod
    def _model_matches(installed: list[str], requested: str) -> bool:
        requested_cf = requested.casefold()
        requested_base = requested_cf.split(":", 1)[0]
        return any(
            candidate.casefold() == requested_cf
            or candidate.casefold() == f"{requested_base}:latest"
            or candidate.casefold().split(":", 1)[0] == requested_base
            for candidate in installed
        )

    async def check_availability(self) -> dict[str, Any]:
        started = time.monotonic()
        try:
            client = self._get_client()
            version_response, tags_response = await asyncio.gather(
                client.get("/api/version", timeout=AVAILABILITY_TIMEOUT_SECONDS),
                client.get("/api/tags", timeout=AVAILABILITY_TIMEOUT_SECONDS),
            )
            version_response.raise_for_status()
            tags_response.raise_for_status()
            version_payload = version_response.json()
            tags_payload = tags_response.json()
            installed_models = [
                str(item.get("name") or item.get("model") or "").strip()
                for item in tags_payload.get("models", [])
                if isinstance(item, dict) and (item.get("name") or item.get("model"))
            ]
            document_installed = self._model_matches(installed_models, self.document_model)
            structured_installed = self._model_matches(installed_models, self.structured_document_model)
            return {
                "available": True,
                "ollama_reachable": True,
                "base_url": self.ollama_url,
                "version": version_payload.get("version"),
                "installed_models": installed_models,
                "selected_document_model": self.document_model,
                "selected_structured_document_model": self.structured_document_model,
                "model_installed": document_installed,
                "structured_model_installed": structured_installed,
                "ready": document_installed and structured_installed,
                "response_time_ms": max(round((time.monotonic() - started) * 1000), 0),
                "error": None if document_installed and structured_installed else "Required Ollama model is not installed",
            }
        except (TimeoutError, httpx.TimeoutException):
            return self._unavailable_status("Ollama availability check timed out")
        except Exception as exc:
            return self._unavailable_status(f"Ollama availability check failed: {type(exc).__name__}")

    def _unavailable_status(self, error: str) -> dict[str, Any]:
        return {
            "available": False,
            "ollama_reachable": False,
            "base_url": self.ollama_url,
            "version": None,
            "installed_models": [],
            "selected_document_model": self.document_model,
            "selected_structured_document_model": self.structured_document_model,
            "model_installed": False,
            "structured_model_installed": False,
            "ready": False,
            "response_time_ms": None,
            "error": error,
        }

    async def generate_document(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout_seconds: float = MAX_GENERATION_TIMEOUT_SECONDS,
    ) -> DocumentGenerationResult:
        return await self._generate(
            model=self.document_model,
            prompt=prompt,
            system_prompt=system_prompt,
            timeout_seconds=timeout_seconds,
            output_format=None,
            options={"temperature": 0.7, "top_p": 0.9, "num_predict": 4096},
        )

    async def generate_structured_document(
        self, prompt: str, timeout_seconds: float = 90.0
    ) -> DocumentGenerationResult:
        return await self._generate(
            model=self.structured_document_model,
            prompt=prompt,
            system_prompt=(
                "You are LUMINA Document Intelligence. Return exactly one valid JSON object. "
                "Never return HTML, Markdown, commentary, or facts not supplied by the user or "
                "verified profile."
            ),
            timeout_seconds=timeout_seconds,
            output_format="json",
            options={"temperature": 0.15, "top_p": 0.8, "num_predict": 3500},
        )

    async def _generate(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None,
        timeout_seconds: float,
        output_format: str | None,
        options: dict[str, Any],
    ) -> DocumentGenerationResult:
        started_at = time.monotonic()
        bounded_timeout = self._bounded_timeout(timeout_seconds)
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if output_format:
            payload["format"] = output_format

        try:
            response = await self._get_client().post(
                "/api/generate", json=payload, timeout=bounded_timeout
            )
            if response.status_code == 404:
                return self._failure(started_at, model, f"Ollama model is not installed: {model}")
            response.raise_for_status()
            data = response.json()
            content = data.get("response")
            response_model = data.get("model") or model
            if not isinstance(content, str) or not content.strip():
                return self._failure(started_at, model, "Malformed Ollama response")
            return DocumentGenerationResult(
                content=content,
                model_used=str(response_model),
                elapsed_seconds=max(time.monotonic() - started_at, 0.0),
                success=True,
            )
        except (TimeoutError, httpx.TimeoutException):
            return self._failure(started_at, model, f"Generation timed out after {bounded_timeout:g}s")
        except httpx.ConnectError:
            return self._failure(started_at, model, "Ollama is unavailable")
        except httpx.HTTPStatusError as exc:
            return self._failure(started_at, model, f"Ollama generation failed with HTTP {exc.response.status_code}")
        except Exception as exc:
            return self._failure(started_at, model, f"Ollama generation failed: {type(exc).__name__}")

    @staticmethod
    def _failure(started_at: float, model: str, error: str) -> DocumentGenerationResult:
        return DocumentGenerationResult(
            content="",
            model_used=model,
            elapsed_seconds=max(time.monotonic() - started_at, 0.0),
            success=False,
            error=error,
        )

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None


_ollama_adapter: OllamaDocumentAdapter | None = None


def get_ollama_adapter() -> OllamaDocumentAdapter:
    global _ollama_adapter
    if _ollama_adapter is None:
        _ollama_adapter = OllamaDocumentAdapter()
    return _ollama_adapter
