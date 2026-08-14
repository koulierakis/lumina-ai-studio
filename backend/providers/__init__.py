"""Lumina provider registry and provider manager."""
from __future__ import annotations

import os
from typing import Dict, Type


def _hydrate_windows_user_environment() -> None:
    """Load selected per-user Windows environment values into this process.

    LUMINA is commonly launched from a long-lived desktop process. Windows user
    environment variables created after that parent process started are stored
    in HKCU\Environment but are not necessarily present in ``os.environ`` of
    the spawned backend. Read only the provider keys we support, never log
    values, and never overwrite an explicit process-level value.
    """
    if os.name != "nt":
        return

    try:
        import winreg
    except ImportError:
        return

    names = (
        "GEMINI_API_KEY_ROTATION",
        "GEMINI_API_KEY",
        "EMERGENT_LLM_KEY",
        "OPENAI_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_IMAGE_MODEL",
    )

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for name in names:
                if os.environ.get(name):
                    continue
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                value = str(value).strip() if value is not None else ""
                if value:
                    os.environ[name] = value
    except OSError:
        return


_hydrate_windows_user_environment()

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
from .cloudflare_provider import CloudflareWorkersAIProvider
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
    "cloudflare": CloudflareWorkersAIProvider,
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
