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


def test_voice_provider_catalog_includes_free_edge_provider():
    catalog = {item["name"]: item for item in voice_provider_catalog()}
    assert catalog["mock"]["available"] is True
    assert catalog["edge"]["available"] is True
    assert catalog["edge"]["configured"] is True
    assert catalog["elevenlabs"]["available"] is False
    assert "text-to-speech" in catalog["edge"]["capabilities"]["modes"]
    assert catalog["edge"]["capabilities"]["formats"] == ["mp3"]


def test_edge_provider_exposes_two_greek_lumina_voices_and_styles():
    provider = get_voice_provider("edge")
    voices = {item["id"]: item for item in provider.list_voices()}
    assert voices["lumina-male"]["provider_voice_id"] == "el-GR-NestorasNeural"
    assert voices["lumina-female"]["provider_voice_id"] == "el-GR-AthinaNeural"
    assert voices["lumina-male"]["language"] == "el-GR"
    assert voices["lumina-female"]["language"] == "el-GR"
    assert provider.capabilities["styles"] == [
        "natural",
        "calm",
        "warm",
        "confident",
        "energetic",
    ]


def test_voice_provider_catalog_keeps_future_adapters_unavailable():
    catalog = {item["name"]: item for item in voice_provider_catalog()}
    assert catalog["elevenlabs"]["available"] is False
    assert catalog["openai"]["available"] is False
    assert catalog["google"]["available"] is False
    assert catalog["azure"]["available"] is False
    assert catalog["cartesia"]["available"] is False
    assert "singing-conversion" in catalog["mock"]["capabilities"]["modes"]
    assert {"wav", "mp3", "flac", "aac"}.issubset(
        set(catalog["mock"]["capabilities"]["formats"])
    )
