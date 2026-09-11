"""Provider-neutral Voice Studio registry."""
from .edge_tts_provider import EdgeTTSVoiceProvider
from .mock_provider import MockVoiceProvider

# "mock" must resolve to the deterministic MockVoiceProvider so tests and
# development callers receive the mock provider contract. "default",
# "microsoft", and "edge-tts" resolve to the real free Edge TTS provider.
_REGISTRY = {
    "mock": MockVoiceProvider,
    "default": EdgeTTSVoiceProvider,
    "microsoft": EdgeTTSVoiceProvider,
    "edge-tts": EdgeTTSVoiceProvider,
}


def get_voice_provider(name=None):
    provider = _REGISTRY.get((name or "default").lower())
    if not provider:
        raise ValueError("The selected voice provider is not available.")
    return provider()


def voice_provider_catalog():
    configured = set(_REGISTRY)
    known = (
        "default",
        "microsoft",
        "edge-tts",
        "mock",
        "elevenlabs",
        "openai",
        "google",
        "azure",
        "cartesia",
    )
    result = []
    for name in known:
        provider = _REGISTRY.get(name)
        result.append(
            {
                "name": name,
                "available": name in configured,
                "configured": name in configured,
                "capabilities": provider.capabilities
                if provider
                else {"modes": [], "formats": [], "credential_ready": False},
            }
        )
    return result


__all__ = [
    "EdgeTTSVoiceProvider",
    "MockVoiceProvider",
    "get_voice_provider",
    "voice_provider_catalog",
]
