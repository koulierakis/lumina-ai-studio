"""Provider-neutral speech-to-text registry; external adapters remain backend-only."""
class MockSTTProvider:
    name = "mock"
    capabilities = {"timestamps": True, "languages": ["auto", "en", "el"], "credential_ready": True}
    async def transcribe(self, data: bytes, language: str):
        return {"text": "Local mock transcript. Connect a speech provider for accurate transcription.", "timestamps": [{"start": 0, "end": 1, "text": "Local mock transcript."}]}

def get_stt_provider(name="mock"):
    if name != "mock": raise ValueError("The selected transcription provider is not configured.")
    return MockSTTProvider()

def stt_provider_catalog():
    return [{"name": "mock", "available": True, "capabilities": MockSTTProvider.capabilities}, *[{"name": n, "available": False, "capabilities": {"timestamps": False, "languages": [], "credential_ready": False}} for n in ("openai", "elevenlabs", "google", "azure")]]
