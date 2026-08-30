"""Credential-safe Document Studio AI provider readiness route."""

from __future__ import annotations

import asyncio
from typing import Any

from auth import require_owner
from fastapi import APIRouter, Depends

from .generation_orchestrator import DocumentAIProviderRegistry, SUPPORTED_PROVIDERS

router = APIRouter()


async def collect_document_provider_status(
    registry: DocumentAIProviderRegistry | None = None,
) -> dict[str, Any]:
    provider_registry = registry or DocumentAIProviderRegistry()

    async def status_for(name: str) -> tuple[str, dict[str, Any]]:
        try:
            payload = await provider_registry.get(name).status()
            sanitized = {
                key: value
                for key, value in dict(payload or {}).items()
                if "key" not in key.casefold() and "secret" not in key.casefold() and "token" not in key.casefold()
            }
            return name, {"name": name, **sanitized}
        except Exception as exc:
            return name, {
                "name": name,
                "available": False,
                "ready": False,
                "error": f"Provider status unavailable: {type(exc).__name__}",
            }

    pairs = await asyncio.gather(*(status_for(name) for name in sorted(SUPPORTED_PROVIDERS)))
    providers = {name: status for name, status in pairs}
    return {
        "default_provider": "ollama",
        "providers": providers,
        "any_ready": any(
            bool(status.get("ready", status.get("available", False)))
            for status in providers.values()
        ),
    }


@router.get("/ai/providers/status")
async def document_provider_status(_: str = Depends(require_owner)) -> dict[str, Any]:
    return await collect_document_provider_status()
