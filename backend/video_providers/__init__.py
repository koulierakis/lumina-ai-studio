"""Video provider registry. Add external adapters here without changing routes or UI."""
from __future__ import annotations

from .base import GeneratedVideo, VideoGenerationInput, VideoProvider, VideoProviderError
from .luma_provider import LumaVideoProvider
from .mock_provider import MockVideoProvider

_REGISTRY: dict[str, type[VideoProvider]] = {"mock": MockVideoProvider, "luma": LumaVideoProvider}


def get_video_provider(name: str | None = None) -> VideoProvider:
    key = (name or "mock").strip().lower()
    provider_class = _REGISTRY.get(key)
    if not provider_class:
        raise VideoProviderError(key, "Unknown video provider", "The selected video engine is not available.")
    if not provider_class.is_configured():
        raise VideoProviderError(key, "Video provider is not configured", "This video engine is not configured yet.")
    return provider_class()


def available_video_providers() -> list[str]:
    return [name for name, provider in _REGISTRY.items() if provider.is_configured()]


def video_provider_catalog() -> list[dict]:
    """Safe UI metadata; credentials and vendor implementation details stay server-side."""
    planned = ("google", "openai", "runway", "kling", "pika", "luma", "veo")
    configured = set(available_video_providers())
    catalog = []
    for name in ("mock", *planned):
        provider = _REGISTRY.get(name)
        capabilities = provider.capabilities if provider else None
        catalog.append({
            "name": name, "configured": name in configured, "available": name in configured,
            "capabilities": {
                "modes": [mode for mode, supported in {
                    "text-to-video": getattr(capabilities, "text_to_video", False),
                    "image-to-video": getattr(capabilities, "image_to_video", False),
                    "multi-image": getattr(capabilities, "multiple_images", False),
                    "extend": getattr(capabilities, "extension", False),
                    "variation": getattr(capabilities, "variation", False),
                    "interpolation": getattr(capabilities, "interpolation", False),
                    "edit": getattr(capabilities, "editing", False),
                }.items() if supported],
                "resolutions": list(getattr(capabilities, "resolutions", ())),
                "durations": list(getattr(capabilities, "durations", ())),
                "aspect_ratios": list(getattr(capabilities, "aspect_ratios", ())),
                "output_formats": list(getattr(capabilities, "output_formats", ())),
                "cancellation": getattr(capabilities, "cancellation", False),
                "max_image_inputs": getattr(capabilities, "max_image_inputs", 0),
                "max_prompt_length": getattr(capabilities, "max_prompt_length", 0),
                "credential_ready": name in configured,
            } if capabilities else {"modes": [], "resolutions": [], "durations": [], "output_formats": []},
        })
    return catalog


__all__ = [
    "GeneratedVideo", "VideoGenerationInput", "VideoProvider", "VideoProviderError",
    "available_video_providers", "video_provider_catalog", "get_video_provider",
]
