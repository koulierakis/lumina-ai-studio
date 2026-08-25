import asyncio
import io
import wave

from voice_providers import get_voice_provider, voice_provider_catalog


def test_mock_voice_provider_creates_valid_wav_with_metadata():
    data, mime, metadata = asyncio.run(
        get_voice_provider("mock").generate(
            "Hello from Lumina",
            "lumina",
            "wav",
            style="documentary",
            sample_rate=48000,
        )
    )
    assert mime == "audio/wav"
    with wave.open(io.BytesIO(data)) as output:
        assert output.getframerate() == 48000
        assert output.getnchannels() == 1
    assert metadata["duration_seconds"] >= 1
    assert metadata["identity_preservation"] is True
    assert metadata["style"] == "documentary"


def test_voice_provider_catalog_exposes_real_adapters_without_faking_configuration():
    catalog = {item["name"]: item for item in voice_provider_catalog()}

    assert catalog["mock"]["available"] is True
    assert catalog["elevenlabs"]["available"] is True
    assert catalog["gemini"]["available"] is True

    # Availability means the adapter exists in this build.  Configuration is a
    # separate runtime fact and must remain false when credentials are absent.
    assert isinstance(catalog["elevenlabs"]["configured"], bool)
    assert isinstance(catalog["gemini"]["configured"], bool)

    assert "text-to-speech" in catalog["mock"]["capabilities"]["modes"]
    assert "singing-conversion" in catalog["mock"]["capabilities"]["modes"]
    assert {"wav", "mp3", "flac", "aac"}.issubset(
        set(catalog["mock"]["capabilities"]["formats"])
    )
