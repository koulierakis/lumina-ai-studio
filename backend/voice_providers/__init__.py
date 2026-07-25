"""Provider-neutral Voice Studio registry."""
from .mock_provider import MockVoiceProvider

_REGISTRY = {"mock": MockVoiceProvider}

def get_voice_provider(name=None):
    provider = _REGISTRY.get((name or "mock").lower())
    if not provider: raise ValueError("The selected voice provider is not available.")
    return provider()

def voice_provider_catalog():
    configured = set(_REGISTRY)
    known = ("mock", "elevenlabs", "openai", "google", "azure", "cartesia")
    result = []
    for name in known:
        provider = _REGISTRY.get(name)
        result.append({"name": name, "available": name in configured, "configured": name in configured,
            "capabilities": provider.capabilities if provider else {"modes": [], "formats": [], "credential_ready": False}})
    return result
