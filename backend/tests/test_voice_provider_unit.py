import asyncio
import io
import sys
import types
import wave

import httpx

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
    assert catalog["omnivoice"]["available"] is True
    assert catalog["omnivoice"]["capabilities"]["modes"] == ["voice-clone"]


def test_omnivoice_provider_runs_upload_queue_and_download_protocol():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/gradio_api/upload":
            return httpx.Response(200, json=["/tmp/gradio/sample/reference.wav"])
        if request.url.path == "/gradio_api/call/_clone_fn" and request.method == "POST":
            return httpx.Response(200, json={"event_id": "voice-123"})
        if request.url.path == "/gradio_api/call/_clone_fn/voice-123":
            body = 'event: complete\ndata: [{"url":"https://voice.test/gradio_api/file=/tmp/output.wav"},"Done."]\n\n'
            return httpx.Response(200, text=body)
        if request.url.path == "/gradio_api/file=/tmp/output.wav":
            return httpx.Response(200, content=b"R" * 512)
        return httpx.Response(404)

    provider = get_voice_provider("omnivoice")
    provider.base_url = "https://voice.test"
    provider._origin = ("https", "voice.test")
    provider._transport = httpx.MockTransport(handler)
    data, mime, metadata = asyncio.run(
        provider.generate(
            "Καλώς ήρθατε στο LUMINA.",
            "personal-user",
            "wav",
            reference_audio=b"sample-audio",
            reference_filename="reference.wav",
            reference_mime="audio/wav",
        )
    )
    assert data == b"R" * 512
    assert mime == "audio/wav"
    assert metadata["voice_cloning"] is True
    assert calls == [
        ("POST", "/gradio_api/upload"),
        ("POST", "/gradio_api/call/_clone_fn"),
        ("GET", "/gradio_api/call/_clone_fn/voice-123"),
        ("GET", "/gradio_api/file=/tmp/output.wav"),
    ]


def test_omnivoice_provider_requires_a_sample_and_blocks_foreign_output():
    provider = get_voice_provider("omnivoice")
    try:
        asyncio.run(provider.generate("Test", "personal-user", "wav"))
        assert False, "missing sample should fail"
    except ValueError as exc:
        assert "sample" in str(exc).lower()

    def handler(request):
        if request.url.path == "/gradio_api/upload":
            return httpx.Response(200, json=["/tmp/reference.wav"])
        if request.url.path == "/gradio_api/call/_clone_fn" and request.method == "POST":
            return httpx.Response(200, json={"event_id": "unsafe"})
        return httpx.Response(200, text='event: complete\ndata: [{"url":"https://attacker.test/audio.wav"}]\n\n')

    provider.base_url = "https://voice.test"
    provider._origin = ("https", "voice.test")
    provider._transport = httpx.MockTransport(handler)
    try:
        asyncio.run(provider.generate("Test", "personal-user", "wav", reference_audio=b"audio"))
        assert False, "foreign output URL should fail"
    except RuntimeError as exc:
        assert "unsafe" in str(exc).lower()


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
