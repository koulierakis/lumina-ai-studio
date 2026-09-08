"""Provider-neutral speech-to-text registry."""
from .whisper_hf_provider import WhisperHFProvider

_REGISTRY = {
    "whisper-hf": WhisperHFProvider,
    "whisper": WhisperHFProvider,
    # Backward-compatible alias because server.py currently requests "mock".
    # It now resolves to the real Whisper provider, not a mock transcript.
    "mock": WhisperHFProvider,
}


def get_stt_provider(name="whisper-hf"):
    provider = _REGISTRY.get((name or "whisper-hf").lower())
    if not provider:
        raise ValueError("The selected transcription provider is not configured.")
    return provider()


def stt_provider_catalog():
    known = ("whisper-hf", "openai", "elevenlabs", "google", "azure")
    result = []
    for name in known:
        provider = _REGISTRY.get(name)
        result.append(
            {
                "name": name,
                "available": provider is not None,
                "configured": provider is not None,
                "capabilities": provider.capabilities
                if provider
                else {"timestamps": False, "languages": [], "credential_ready": False},
            }
        )
    return result
