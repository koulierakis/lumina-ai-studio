import asyncio
import base64

import pytest

from voice_providers import openvoice_v2
from voice_providers.openvoice_v2 import OpenVoiceV2ToneConverter, ToneConversionError


def test_from_env_not_configured(monkeypatch):
    monkeypatch.delenv("OPENVOICE_V2_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENVOICE_V2_API_KEY", raising=False)
    monkeypatch.setenv("OPENVOICE_V2_REQUIRED", "0")
    converter = OpenVoiceV2ToneConverter.from_env()
    assert converter.configured is False
    assert converter.required is False


def test_convert_rejects_missing_endpoint():
    converter = OpenVoiceV2ToneConverter()
    with pytest.raises(ToneConversionError) as exc:
        asyncio.run(converter.convert(b"base", "audio/mpeg", b"ref", "audio/wav"))
    assert exc.value.code == "not_configured"


def test_convert_accepts_raw_audio(monkeypatch):
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "audio/wav"}
        content = b"converted-audio"

        def json(self):
            raise AssertionError("raw audio response must not be decoded as JSON")

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            assert url == "https://voice.example/convert"
            assert "source_audio" in kwargs["files"]
            assert "reference_audio" in kwargs["files"]
            return FakeResponse()

    monkeypatch.setattr(openvoice_v2.httpx, "AsyncClient", FakeClient)
    converter = OpenVoiceV2ToneConverter(endpoint="https://voice.example/convert")
    result = asyncio.run(converter.convert(b"base", "audio/mpeg", b"ref", "audio/wav"))
    assert result.audio == b"converted-audio"
    assert result.mime_type == "audio/wav"
    assert result.metadata["tone_converter"] == "openvoice-v2"


def test_convert_accepts_json_base64(monkeypatch):
    encoded = base64.b64encode(b"voice-clone").decode("ascii")

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b""

        def json(self):
            return {"audio_base64": encoded, "mime_type": "audio/mpeg"}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(openvoice_v2.httpx, "AsyncClient", FakeClient)
    converter = OpenVoiceV2ToneConverter(endpoint="https://voice.example/convert")
    result = asyncio.run(converter.convert(b"base", "audio/mpeg", b"ref", "audio/wav"))
    assert result.audio == b"voice-clone"
    assert result.mime_type == "audio/mpeg"
