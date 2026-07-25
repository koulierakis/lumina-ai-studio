import asyncio
import io
import wave

from voice_providers import get_voice_provider, voice_provider_catalog


def test_mock_voice_provider_creates_valid_wav_with_metadata():
    data, mime, metadata = asyncio.run(get_voice_provider("mock").generate("Hello from Lumina", "lumina", "wav"))
    assert mime == "audio/wav"
    with wave.open(io.BytesIO(data)) as output:
        assert output.getframerate() == 24000
        assert output.getnchannels() == 1
    assert metadata["duration_seconds"] >= 1


def test_voice_provider_catalog_keeps_future_adapters_unavailable():
    catalog = {item["name"]: item for item in voice_provider_catalog()}
    assert catalog["mock"]["available"] is True
    assert catalog["elevenlabs"]["available"] is False
    assert "text-to-speech" in catalog["mock"]["capabilities"]["modes"]
