"""Unified AI health and provider registry.

Aggregates the status of every AI subsystem into one credential-safe payload so
the UI (and Mind) can show a truthful READY / CONFIGURATION REQUIRED /
TEMPORARILY UNAVAILABLE / UNSUPPORTED state per capability.

This module is additive: it reuses the existing per-subsystem catalogs instead
of duplicating provider logic, and never raises when a subsystem is missing.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger("lumina")


class AiCapability(str, Enum):
    TEXT = "TEXT"
    CODE = "CODE"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    DOCUMENT = "DOCUMENT"
    VOICE = "VOICE"
    STT = "STT"
    TALKING_FACE = "TALKING_FACE"


class HealthState(str, Enum):
    READY = "READY"
    CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass
class ProviderHealth:
    provider: str
    capability: str
    model: str = ""
    configured: bool = False
    healthy: bool = False
    available: bool = False
    state: str = HealthState.UNSUPPORTED.value
    cooldown: bool = False
    quota_state: str = "unknown"
    last_error: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ErrorDisposition(str, Enum):
    TRANSIENT = "transient"  # retry later with cooldown / fallback
    PERMANENT = "permanent"  # quarantine until configuration changes
    AUTH = "auth"  # credentials rejected
    QUOTA = "quota"  # rate/^quota limited


# HTTP status -> disposition. Deterministic, documented, no opaque routing.
_STATUS_DISPOSITION: dict[int, ErrorDisposition] = {
    400: ErrorDisposition.PERMANENT,
    401: ErrorDisposition.AUTH,
    402: ErrorDisposition.QUOTA,
    403: ErrorDisposition.AUTH,
    404: ErrorDisposition.PERMANENT,
    408: ErrorDisposition.TRANSIENT,
    409: ErrorDisposition.TRANSIENT,
    422: ErrorDisposition.PERMANENT,
    429: ErrorDisposition.QUOTA,
    500: ErrorDisposition.TRANSIENT,
    502: ErrorDisposition.TRANSIENT,
    503: ErrorDisposition.TRANSIENT,
    504: ErrorDisposition.TRANSIENT,
}


def classify_provider_error(status_code: int | None = None, *, message: str = "") -> ErrorDisposition:
    """Classify a provider failure so callers can cooldown vs quarantine.

    Transient failures should cool down and fall back. Permanent configuration
    failures should be quarantined until configuration changes so the app never
    hammers a provider known to be misconfigured.
    """
    if status_code is not None and status_code in _STATUS_DISPOSITION:
        return _STATUS_DISPOSITION[status_code]
    lowered = message.lower()
    if any(token in lowered for token in ("timeout", "timed out", "connection reset", "temporarily")):
        return ErrorDisposition.TRANSIENT
    if any(token in lowered for token in ("invalid api key", "unauthorized", "forbidden", "permission")):
        return ErrorDisposition.AUTH
    if any(token in lowered for token in ("quota", "rate limit", "too many requests")):
        return ErrorDisposition.QUOTA
    if any(token in lowered for token in ("not found", "unknown model", "invalid model", "missing")):
        return ErrorDisposition.PERMANENT
    return ErrorDisposition.TRANSIENT


def _state_for(configured: bool, available: bool, healthy: bool, unsupported: bool) -> HealthState:
    if unsupported:
        return HealthState.UNSUPPORTED
    if not configured:
        return HealthState.CONFIGURATION_REQUIRED
    if healthy and available:
        return HealthState.READY
    if configured and not (healthy and available):
        return HealthState.TEMPORARILY_UNAVAILABLE
    return HealthState.CONFIGURATION_REQUIRED


def _truthy_flag(entry: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if key in entry and entry[key] is not None:
            return bool(entry[key])
    return False


def _from_entries(capability: AiCapability, entries: list[dict[str, Any]]) -> list[ProviderHealth]:
    out: list[ProviderHealth] = []
    for entry in entries or []:
        capabilities = entry.get("capabilities") or {}
        simulated = bool(entry.get("simulation") or (isinstance(capabilities, dict) and capabilities.get("simulation")))
        configured = _truthy_flag(entry, "configured", "credential_ready")
        available = _truthy_flag(entry, "available", "configured", "credential_ready")
        healthy = _truthy_flag(entry, "healthy", "ready", "available", "configured", "credential_ready")
        # A simulation-only provider is available without credentials but must be
        # labelled truthfully so it is never mistaken for real inference.
        unsupported = "unsupported" in str(entry.get("state", "")).lower()
        state = _state_for(configured=configured or simulated, available=available or simulated, healthy=healthy or simulated, unsupported=unsupported)
        out.append(
            ProviderHealth(
                provider=str(entry.get("name") or entry.get("id") or "unknown"),
                capability=capability.value,
                model=str(entry.get("model") or ""),
                configured=configured or simulated,
                healthy=healthy or simulated,
                available=available or simulated,
                state=state.value,
                quota_state=str(entry.get("quota_state") or "unknown"),
                last_error=str(entry.get("last_error") or ""),
                detail=("simulation only" if simulated else str(entry.get("detail") or "")),
            )
        )
    return out


async def _safe(coro_factory: Callable[[], Awaitable[Any]], fallback: Any) -> Any:
    try:
        return await coro_factory()
    except Exception:  # a missing/broken subsystem must never break the dashboard
        logger.warning("AI health probe failed", exc_info=True)
        return fallback


def _safe_sync(factory: Callable[[], Any], fallback: Any) -> Any:
    try:
        return factory()
    except Exception:
        logger.warning("AI health probe failed", exc_info=True)
        return fallback


async def collect_ai_health() -> dict[str, Any]:
    """Return one unified, credential-safe AI health payload."""
    providers: list[ProviderHealth] = []

    # IMAGE
    from providers import provider_manager

    image_statuses = await _safe(provider_manager.statuses, [])
    providers += _from_entries(AiCapability.IMAGE, image_statuses)

    # VIDEO
    from video_providers import video_provider_catalog

    providers += _from_entries(AiCapability.VIDEO, _safe_sync(video_provider_catalog, []))

    # VOICE / STT / TALKING_FACE
    from voice_providers import voice_provider_catalog
    from stt_providers import stt_provider_catalog
    from talking_face_providers import talking_face_catalog
    from talking_portrait_providers import talking_portrait_catalog

    providers += _from_entries(AiCapability.VOICE, _safe_sync(voice_provider_catalog, []))
    providers += _from_entries(AiCapability.STT, _safe_sync(stt_provider_catalog, []))
    providers += _from_entries(AiCapability.TALKING_FACE, _safe_sync(talking_face_catalog, []))
    providers += _from_entries(AiCapability.TALKING_FACE, _safe_sync(talking_portrait_catalog, []))

    # DOCUMENT
    from document_studio.provider_status import collect_document_provider_status

    doc_payload = await _safe(collect_document_provider_status, {})
    doc_entries = []
    if isinstance(doc_payload, dict):
        for name, status in (doc_payload.get("providers") or {}).items():
            if isinstance(status, dict):
                doc_entries.append({"name": name, **status})
    providers += _from_entries(AiCapability.DOCUMENT, doc_entries)

    # CODE engines
    from code_builder.engine_registry import CodingEngineRegistry

    code_status = _safe_sync(lambda: CodingEngineRegistry().public_status(), {})
    code_entries = []
    for engine in (code_status.get("engines") or []) if isinstance(code_status, dict) else []:
        if isinstance(engine, dict):
            code_entries.append(
                {
                    "name": engine.get("name"),
                    "available": engine.get("available"),
                    "configured": engine.get("available"),
                    "detail": "experimental" if engine.get("experimental") else "",
                }
            )
    providers += _from_entries(AiCapability.CODE, code_entries)

    # TEXT (Mind advisor provider)
    providers += _from_entries(AiCapability.TEXT, _text_provider_entries())

    by_capability: dict[str, list[dict[str, Any]]] = {cap.value: [] for cap in AiCapability}
    for provider in providers:
        by_capability.setdefault(provider.capability, []).append(provider.to_dict())

    summary = {cap: _summarise(entries) for cap, entries in by_capability.items()}
    return {"capabilities": summary, "providers": [p.to_dict() for p in providers], "any_ready": any(s["state"] == HealthState.READY.value for s in summary.values())}


def _text_provider_entries() -> list[dict[str, Any]]:
    import os

    entries: list[dict[str, Any]] = []
    for name, envs in (
        ("groq", ("GROQ_API_KEY",)),
        ("openrouter", ("OPENROUTER_API_KEY",)),
        ("gemini", ("GEMINI_API_KEY",)),
        ("ollama", ()),
    ):
        configured = any(os.environ.get(var, "").strip() for var in envs) if envs else True
        entries.append({"name": name, "configured": configured, "available": configured, "healthy": configured})
    return entries


def _summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        return {"state": HealthState.UNSUPPORTED.value, "configured": 0, "total": 0, "ready": 0}
    ready = sum(1 for e in entries if e["state"] == HealthState.READY.value)
    configured = sum(1 for e in entries if e["configured"])
    if ready:
        state = HealthState.READY
    elif configured:
        state = HealthState.TEMPORARILY_UNAVAILABLE
    elif all(e["state"] == HealthState.UNSUPPORTED.value for e in entries):
        state = HealthState.UNSUPPORTED
    else:
        state = HealthState.CONFIGURATION_REQUIRED
    return {"state": state.value, "configured": configured, "total": len(entries), "ready": ready}
