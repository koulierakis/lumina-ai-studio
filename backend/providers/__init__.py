"""Lumina provider registry and provider manager."""
from __future__ import annotations

from typing import Dict, Type

from .base import (
    ErrorKind,
    GeneratedImage,
    GenerationInput,
    ImageProvider,
    ProviderAuthenticationError,
    ProviderCapabilities,
    ProviderConfigurationError,
    ProviderContentPolicyError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ProviderStatus,
    ProviderTimeoutError,
    ProviderUnsupportedCapabilityError,
)
from .comfyui_provider import ComfyUIProvider
from .gemini_provider import GeminiImageProvider
from .manager import ProviderManager
from .mock_provider import MockImageProvider
from .openai_provider import OpenAIImageProvider
from .skeletons import BflImageProvider, FalImageProvider, ReplicateImageProvider
from .stable_diffusion_provider import LocalImageProvider, StableDiffusionProvider

_REGISTRY: Dict[str, Type[ImageProvider]] = {
    "comfyui": ComfyUIProvider,
    "fal": FalImageProvider,
    "bfl": BflImageProvider,
    "replicate": ReplicateImageProvider,
    "gemini": GeminiImageProvider,
    "mock": MockImageProvider,
    "openai": OpenAIImageProvider,
    "local": LocalImageProvider,
    "stable-diffusion": StableDiffusionProvider,
}
manager = ProviderManager(_REGISTRY)
provider_manager = manager


def available_providers() -> list[str]:
    return manager.configured_names()


def get_provider(name: str | None = None) -> ImageProvider:
    key = (name or "gemini").lower()
    if key not in _REGISTRY:
        raise ValueError(f"Unknown provider: {key}")
    return _REGISTRY[key]()


__all__ = [
    "ImageProvider",
    "ErrorKind",
    "GenerationInput",
    "GeneratedImage",
    "ProviderCapabilities",
    "ProviderStatus",
    "ProviderError",
    "ProviderTimeoutError",
    "ProviderRateLimitError",
    "ProviderQuotaError",
    "ProviderAuthenticationError",
    "ProviderConfigurationError",
    "ProviderUnsupportedCapabilityError",
    "ProviderContentPolicyError",
    "ProviderInvalidResponseError",
    "get_provider",
    "available_providers",
    "manager",
    "provider_manager",
]
