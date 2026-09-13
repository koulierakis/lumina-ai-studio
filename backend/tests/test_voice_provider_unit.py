import asyncio
import io
import sys
import types
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
        "professional",
        "energetic",
        "storytelling",
    ]


def test_style_engine_v2_has_six_distinct_delivery_signatures():
    from voice_providers.style_engine import VoiceStyleEngine

    profiles = [VoiceStyleEngine.resolve(style) for style in VoiceStyleEngine.catalog()]
    signatures = {(item.rate, item.pitch, item.volume, item.sentence_pause) for item in profiles}
    assert len(profiles) == len(signatures) == 6
    assert VoiceStyleEngine.resolve("podcast").id == "natural"
    assert VoiceStyleEngine.resolve("corporate").id == "professional"
    assert VoiceStyleEngine.resolve("audiobook").id == "storytelling"


def test_style_engine_v2_shapes_timing_without_changing_words():
    from voice_providers.style_engine import VoiceStyleEngine

    source = "Μία πρώτη πρόταση. Και μία δεύτερη!"
    natural = VoiceStyleEngine.resolve("natural").prepare_text(source)
    storytelling = VoiceStyleEngine.resolve("storytelling").prepare_text(source)
    assert natural == source
    assert storytelling == "Μία πρώτη πρόταση. … Και μία δεύτερη! …"


def test_edge_provider_applies_style_engine_v2_to_generation(monkeypatch):
    captured = {}

    class FakeCommunicate:
        def __init__(self, text, voice, **prosody):
            captured.update(text=text, voice=voice, **prosody)

        async def stream(self):
            yield {"type": "audio", "data": b"a" * 512}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))
    data, mime, metadata = asyncio.run(
        get_voice_provider("edge").generate(
            "Μία ιστορία. Με συνέχεια.",
            "lumina-female",
            "mp3",
            style="storytelling",
        )
    )

    assert len(data) == 512
    assert mime == "audio/mpeg"
    assert captured == {
        "text": "Μία ιστορία. … Με συνέχεια. …",
        "voice": "el-GR-AthinaNeural",
        "rate": "-14%",
        "pitch": "-11Hz",
        "volume": "+2%",
    }
    assert metadata["style_engine"] == "v2"
    assert metadata["style"] == "storytelling"


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
