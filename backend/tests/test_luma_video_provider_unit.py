from __future__ import annotations

import asyncio
import os

import pytest
import requests

from video_providers import video_provider_catalog
from video_providers.base import VideoGenerationInput, VideoProviderError
from video_providers.luma_provider import LumaVideoProvider


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b"", headers=None):
        self.status_code, self._payload, self.content = status, payload, content
        self.headers = headers or {}
    def json(self):
        if isinstance(self._payload, Exception): raise self._payload
        return self._payload


def spec(mode="text-to-video", **kwargs):
    return VideoGenerationInput(mode=mode, prompt="a quiet sea at sunrise", duration_seconds=5, aspect_ratio="16:9", resolution="720p", **kwargs)


@pytest.fixture(autouse=True)
def luma_env(monkeypatch):
    monkeypatch.setenv("LUMA_API_KEY", "test-secret-key")
    monkeypatch.setenv("LUMA_API_BASE", "https://provider.example/v1")


def test_submit_text_and_poll_completed(monkeypatch):
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse(payload={"id": "generation-1", "state": "queued"} if method == "POST" else {"state": "completed", "assets": {"video": "https://cdn.example/video.mp4"}})
    monkeypatch.setattr(requests, "request", request)
    provider = LumaVideoProvider()
    submitted = asyncio.run(provider.submit(spec()))
    completed = asyncio.run(provider.poll(submitted.id))
    assert submitted.id == "generation-1" and completed.output_url.endswith(".mp4")
    assert calls[0][2]["headers"]["Authorization"] == "Bearer test-secret-key"
    assert calls[0][2]["json"]["model"] == "ray-2"


def test_submit_image_uses_configured_public_source_url(monkeypatch):
    monkeypatch.setenv("LUMA_IMAGE_URL_BASE", "https://assets.example/private")
    seen = {}
    monkeypatch.setattr(requests, "request", lambda *a, **kw: (seen.update(kw) or FakeResponse(payload={"id": "a", "state": "queued"})))
    asyncio.run(LumaVideoProvider().submit(spec("image-to-video", source_urls=["https://assets.example/private/file.png"])))
    assert seen["json"]["keyframes"]["frame0"]["url"].startswith("https://assets.example/")


def test_image_without_public_source_is_rejected():
    with pytest.raises(VideoProviderError, match="No public source URL"):
        asyncio.run(LumaVideoProvider().submit(spec("image-to-video")))


def test_download_preserves_native_mime(monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **kw: FakeResponse(content=b"webm-data", headers={"Content-Type": "video/webm"}))
    completed = asyncio.run(LumaVideoProvider().download(type("J", (), {"id": "j", "output_url": "https://cdn.example/v.webm"})()))
    assert completed.mime_type == "video/webm" and completed.data == b"webm-data"


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failure_is_safe_and_not_secret(monkeypatch, status):
    monkeypatch.setattr(requests, "request", lambda *a, **kw: FakeResponse(status=status))
    with pytest.raises(VideoProviderError) as error:
        asyncio.run(LumaVideoProvider().submit(spec()))
    assert "test-secret-key" not in str(error.value)
    assert "configured correctly" in error.value.safe_message


def test_malformed_failed_timeout_and_cancel(monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **kw: FakeResponse(payload={}))
    with pytest.raises(VideoProviderError): asyncio.run(LumaVideoProvider().submit(spec()))
    monkeypatch.setattr(requests, "request", lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout()))
    with pytest.raises(VideoProviderError) as error: asyncio.run(LumaVideoProvider().poll("j"))
    assert error.value.retryable
    monkeypatch.setattr(requests, "request", lambda *a, **kw: FakeResponse(status=204))
    asyncio.run(LumaVideoProvider().cancel("j"))


def test_missing_credentials_and_capability_catalog(monkeypatch):
    monkeypatch.delenv("LUMA_API_KEY", raising=False)
    assert not LumaVideoProvider.is_configured()
    catalog = {item["name"]: item for item in video_provider_catalog()}
    luma = catalog["luma"]
    assert not luma["available"]
    assert {"text-to-video", "image-to-video"}.issubset(luma["capabilities"]["modes"])
    assert luma["capabilities"]["cancellation"] is True
