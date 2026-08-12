"""Lazy, bounded adapter from Document Studio to the existing Ollama service."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import Any

from code_builder.ollama_service import (
    OllamaClientConfiguration,
    OllamaModelNotFoundError,
    OllamaService,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from pydantic import BaseModel

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_DOCUMENT_MODEL = "qwen2.5-coder:7b"
DEFAULT_STRUCTURED_DOCUMENT_MODEL = "qwen2.5-coder:1.5b"
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
    """Document generation adapter that creates no network client at startup."""

    def __init__(
        self,
        *,
        service: OllamaService | None = None,
        service_factory: Callable[[OllamaClientConfiguration], OllamaService] = OllamaService,
        ollama_url: str | None = None,
    ) -> None:
        self.ollama_url = ollama_url or os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL)
        self._service = service
        self._service_factory = service_factory

    @property
    def document_model(self) -> str:
        return os.getenv("OLLAMA_DOCUMENT_MODEL", DEFAULT_DOCUMENT_MODEL)

    @property
    def structured_document_model(self) -> str:
        return os.getenv("OLLAMA_STRUCTURED_DOCUMENT_MODEL", DEFAULT_STRUCTURED_DOCUMENT_MODEL)

    def _get_service(self) -> OllamaService:
        if self._service is None:
            configuration = OllamaClientConfiguration(base_url=self.ollama_url)
            self._service = self._service_factory(configuration)
        return self._service

    @staticmethod
    def _bounded_timeout(timeout_seconds: float) -> float:
        try:
            requested = float(timeout_seconds)
        except (TypeError, ValueError):
            requested = MAX_GENERATION_TIMEOUT_SECONDS
        return min(max(requested, 0.1), MAX_GENERATION_TIMEOUT_SECONDS)

    async def check_availability(self) -> dict[str, Any]:
        try:
            health = await asyncio.wait_for(
                self._get_service().check_connection(include_models=True),
                timeout=AVAILABILITY_TIMEOUT_SECONDS,
            )
            installed_models = [model.name for model in health.installed_models]
            requested = self.document_model.casefold()
            requested_base = requested.split(":", 1)[0]
            model_installed = any(
                candidate.casefold() == requested
                or candidate.casefold() == f"{requested_base}:latest"
                or candidate.casefold().split(":", 1)[0] == requested_base
                for candidate in installed_models
            )
            return {
                "available": bool(health.available),
                "ollama_reachable": bool(health.available),
                "base_url": health.base_url,
                "version": health.version,
                "installed_models": installed_models,
                "selected_document_model": self.document_model,
                "model_installed": model_installed,
                "response_time_ms": health.response_time_ms,
                "error": health.error,
            }
        except TimeoutError:
            return self._unavailable_status("Ollama availability check timed out")
        except Exception as exc:
            return self._unavailable_status(
                f"Ollama availability check failed: {type(exc).__name__}"
            )

    def _unavailable_status(self, error: str) -> dict[str, Any]:
        return {
            "available": False,
            "ollama_reachable": False,
            "base_url": self.ollama_url,
            "version": None,
            "installed_models": [],
            "selected_document_model": self.document_model,
            "model_installed": False,
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
        try:
            response = await asyncio.wait_for(
                self._get_service().generate(
                    model=model,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    timeout_seconds=bounded_timeout,
                    output_format=output_format,
                    options=options,
                ),
                timeout=bounded_timeout,
            )
            content = getattr(response, "content", None)
            response_model = getattr(response, "model", None)
            if not isinstance(content, str) or not content.strip() or not response_model:
                return self._failure(started_at, model, "Malformed Ollama response")
            return DocumentGenerationResult(
                content=content,
                model_used=str(response_model),
                elapsed_seconds=max(time.monotonic() - started_at, 0.0),
                success=True,
            )
        except (TimeoutError, OllamaTimeoutError):
            return self._failure(
                started_at, model, f"Generation timed out after {bounded_timeout:g}s"
            )
        except OllamaModelNotFoundError:
            return self._failure(started_at, model, f"Ollama model is not installed: {model}")
        except OllamaUnavailableError:
            return self._failure(started_at, model, "Ollama is unavailable")
        except Exception as exc:
            return self._failure(
                started_at, model, f"Ollama generation failed: {type(exc).__name__}"
            )

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
        if self._service is not None:
            await self._service.close()
            self._service = None


_ollama_adapter: OllamaDocumentAdapter | None = None


def get_ollama_adapter() -> OllamaDocumentAdapter:
    global _ollama_adapter
    if _ollama_adapter is None:
        _ollama_adapter = OllamaDocumentAdapter()
    return _ollama_adapter
