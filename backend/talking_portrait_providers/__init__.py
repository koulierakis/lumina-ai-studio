"""Talking Portrait Studio provider registry."""
from __future__ import annotations

from .base import (
    GeneratedTalkingPortrait,
    TalkingPortraitInput,
    TalkingPortraitProvider,
    TalkingPortraitProviderError,
)
from .liveportrait_provider import LivePortraitProvider

_REGISTRY: dict[str, type[TalkingPortraitProvider]] = {"liveportrait": LivePortraitProvider}
_FUTURE = ("musetalk", "echomimic", "hallo", "sadtalker", "wav2lip")


def get_talking_portrait_provider(name: str | None = None, *, require_installed: bool = True) -> TalkingPortraitProvider:
    key = (name or auto_detect_talking_portrait_provider()).strip().lower()
    provider_class = _REGISTRY.get(key)
    if not provider_class:
        raise TalkingPortraitProviderError(key, "Unknown talking portrait provider", "The selected talking portrait engine is not available.")
    if require_installed and not provider_class.is_installed():
        raise TalkingPortraitProviderError(key, "Provider is not installed", "Install LivePortrait before generating talking portraits.")
    return provider_class()


def auto_detect_talking_portrait_provider() -> str:
    return "liveportrait"


def available_talking_portrait_providers() -> list[str]:
    return [name for name, provider in _REGISTRY.items() if provider.generation_readiness(provider.diagnostics(quick=True)).get("operational")]


def talking_portrait_catalog() -> list[dict]:
    catalog = []
    for name, provider in _REGISTRY.items():
        diagnostics = provider.diagnostics()
        readiness = provider.generation_readiness(diagnostics)
        catalog.append({
            "name": name,
            "display_name": provider.display_name,
            "available": bool(readiness.get("operational")),
            "installed": bool(diagnostics.get("installed")),
            "healthy": bool(readiness.get("operational")),
            "repository_url": provider.repository_url,
            "install_root": diagnostics.get("install_root"),
            "diagnostics": diagnostics,
            "readiness": readiness,
            "capabilities": {"output_formats": list(provider.capabilities.output_formats), "identity_lock": provider.capabilities.identity_lock, "natural_blinking": provider.capabilities.natural_blinking, "head_motion": provider.capabilities.head_motion, "expression_intensity": provider.capabilities.expression_intensity, "audio_driven_lip_sync": bool(diagnostics.get("lip_sync_engine")), "lip_sync_engine": diagnostics.get("lip_sync_engine"), "gpu": diagnostics.get("gpu", False), "cpu_fallback": diagnostics.get("compute_mode") == "cpu", "windows": True},
        })
    for name in _FUTURE:
        catalog.append({"name": name, "display_name": name.title(), "available": False, "installed": False, "healthy": False, "capabilities": {"output_formats": ["video/mp4"]}})
    return catalog


__all__ = ["GeneratedTalkingPortrait", "TalkingPortraitInput", "TalkingPortraitProvider", "TalkingPortraitProviderError", "available_talking_portrait_providers", "auto_detect_talking_portrait_provider", "get_talking_portrait_provider", "talking_portrait_catalog"]
