"""Base contracts for Voice Studio providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseVoiceProvider(ABC):
    """Minimal async provider contract consumed by Voice Studio."""

    name = "base"
    capabilities = {
        "modes": [],
        "formats": [],
        "credential_ready": False,
    }

    @abstractmethod
    async def generate(
        self,
        text: str,
        voice: str,
        output_format: str,
        **options,
    ) -> tuple[bytes, str, dict]:
        """Return audio bytes, MIME type, and provider metadata."""
        raise NotImplementedError
