"""Base interface for LUMINA speech-to-text providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseSTTProvider(ABC):
    """Provider-neutral asynchronous speech-to-text interface."""

    name = "base"
    capabilities = {
        "timestamps": False,
        "languages": ["auto"],
        "credential_ready": False,
    }

    @abstractmethod
    async def transcribe(self, data: bytes, language: str = "auto") -> dict:
        """Return a mapping with at least ``text`` and ``timestamps`` keys."""
        raise NotImplementedError
