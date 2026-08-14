"""Provider-neutral Voice Studio registry."""

from .elevenlabs_provider import ElevenLabsVoiceProvider
from .gemini_provider import GeminiVoiceProvider
from .mock_provider import MockVoiceProvider

_REGISTRY = {
    "elevenlabs": ElevenLabsVoiceProvider,
    "gemini": GeminiVoiceProvider,
    "mock": MockVoiceProvider,
}


def get_voice_provider(name=None):
    provider = _REGISTRY.get((name or "gemini").lower())
    if not provider:
        raise ValueError("The selected voice provider is not available.")
    return provider()


def _configured(provider) -> bool:
    if provider is None:
        return False
    checker = getattr(provider, "is_configured", None)
    return bool(checker()) if callable(checker) else True


def voice_provider_catalog():
    known = ("gemini", "elevenlabs", "mock", "openai", "azure", "cartesia")
    result = []
    for name in known:
        provider = _REGISTRY.get(name)
        result.append({
            "name": name,
            "available": provider is not None,
            "configured": _configured(provider),
            "capabilities": provider.capabilities if provider else {
                "modes": [],
                "formats": [],
                "credential_ready": False,
            },
        })
    return result
