from __future__ import annotations

import asyncio
import io
import json
import sys

import pytest
import server
from PIL import Image
from video_providers import get_video_provider
from video_providers.base import GeneratedVideo, VideoGenerationInput
from video_providers.huggingface_provider import HuggingFaceVideoProvider
from video_providers.pollinations_provider import PollinationsVideoProvider


def _source_png() -> bytes:
    image = Image.new("RGB", (40, 30), "#c49b5a")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _job_doc() -> dict:
    return {
        "id": "video-job-1",
        "owner_email": "owner@lumina.local",
        "status": "queued",
        "provider": "huggingface",
        "mode": "text-to-video",
        "prompt": "A serene galaxy drifting through deep space.",
        "negative_prompt": "",
        "duration_seconds": 5,
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "source_media_ids": [],
        "metadata": {},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


class _FakeVideoJobs:
    def __init__(self, job):
        self.job = dict(job)

    async def find_one(self, query, projection=None):
        if query.get("id") == self.job.get("id") and query.get("owner_email") == self.job.get("owner_email"):
            return dict(self.job)
        return None

    async def update_one(self, query, update):
        for key, value in update.get("$set", {}).items():
            target = self.job
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        return None

    async def insert_many(self, docs):
        return None


class _FakeMedia:
    async def find_one(self, query, projection=None):
        return None

    async def insert_one(self, payload):
        return None


class _FakeProvider:
    name = "huggingface"
    capabilities = HuggingFaceVideoProvider.capabilities
    supports_async_jobs = False

    def __init__(self, exc=None):
        self.exc = exc

    async def generate(self, spec):
        if self.exc:
            raise self.exc


def test_video_provider_failure_surfaces_real_safe_message(monkeypatch):
    from video_providers.base import VideoProviderError

    jobs = _FakeVideoJobs(_job_doc())
    provider_error = VideoProviderError(
        "huggingface",
        "Workflow.PredictionQueueError(\"queue is full\") zero_gpu blocked",
        "The free Hugging Face Space is busy right now. Retry in a few minutes.",
        retryable=True,
    )

    monkeypatch.setattr(server, "video_generation_jobs_coll", jobs)
    monkeypatch.setattr(server, "media_coll", _FakeMedia())
    monkeypatch.setattr(server, "get_video_provider", lambda name=None: _FakeProvider(exc=provider_error))
    monkeypatch.setattr(server, "read_bytes", lambda filename, kind: b"source-bytes")

    asyncio.run(server._run_video_generation("video-job-1", "owner@lumina.local"))

    assert jobs.job["status"] == "failed"
    assert jobs.job["error"] == "The free Hugging Face Space is busy right now. Retry in a few minutes."


def test_video_provider_rewrites_generic_runtime_failure(monkeypatch):
    jobs = _FakeVideoJobs(_job_doc())

    async def _explode(runtime_job, progress):
        raise RuntimeError("boom inside executor")

    class _FakeExplodingProvider:
        name = "huggingface"
        capabilities = HuggingFaceVideoProvider.capabilities
        supports_async_jobs = False

        async def generate(self, spec):
            raise RuntimeError("boom inside executor")

    monkeypatch.setattr(server, "video_generation_jobs_coll", jobs)
    monkeypatch.setattr(server, "media_coll", _FakeMedia())
    monkeypatch.setattr(server, "get_video_provider", lambda name=None: _FakeExplodingProvider())

    asyncio.run(server._run_video_generation("video-job-1", "owner@lumina.local"))

    assert jobs.job["status"] == "failed"
    assert jobs.job["error"] == "boom inside executor"
    assert jobs.job["error"] != "Video generation could not be completed."


def test_default_video_provider_is_real_huggingface():
    assert get_video_provider().name == "huggingface"


def test_mock_video_provider_creates_animated_gif():
    result = asyncio.run(get_video_provider("mock").generate(VideoGenerationInput(
        mode="image-to-video", source_images=[_source_png()], source_mimes=["image/png"],
        prompt="Slow cinematic movement", duration_seconds=3, aspect_ratio="9:16",
    )))

    assert result.mime_type == "image/gif"
    assert result.preview_kind == "animated-image"
    assert result.data.startswith((b"GIF87a", b"GIF89a"))
    animation = Image.open(io.BytesIO(result.data))
    assert animation.n_frames >= 8
    assert animation.size == (360, 640)


def test_mock_video_provider_is_available_without_credentials():
    from video_providers import available_video_providers

    assert "mock" in available_video_providers()


def test_mock_provider_supports_text_only_request_for_local_workflows():
    result = asyncio.run(get_video_provider("mock").generate(VideoGenerationInput(
        mode="text-to-video", prompt="golden abstract motion", duration_seconds=3, aspect_ratio="16:9",
    )))
    assert result.data.startswith((b"GIF87a", b"GIF89a"))


def test_pollinations_is_optional_without_api_key(monkeypatch):
    monkeypatch.delenv("POLLINATIONS_API_KEY", raising=False)
    assert PollinationsVideoProvider.is_configured() is False


def test_huggingface_timeout_uses_pollinations_when_configured(monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "sk_test")
    provider = HuggingFaceVideoProvider()

    async def timeout(_spec):
        raise TimeoutError()

    async def fallback(_self, _spec):
        return GeneratedVideo(
            data=b"\x00\x00\x00\x18ftypmp42test",
            mime_type="video/mp4",
            metadata={"provider": "pollinations"},
        )

    monkeypatch.setattr(provider, "_generate_image_to_video_via_gradio", timeout)
    monkeypatch.setattr(PollinationsVideoProvider, "generate", fallback)

    result = asyncio.run(provider.generate(VideoGenerationInput(
        mode="image-to-video", source_images=[_source_png()], source_mimes=["image/png"],
        prompt="Slow cinematic movement", duration_seconds=3, aspect_ratio="9:16",
    )))

    assert result.mime_type == "video/mp4"
    assert result.metadata["provider"] == "pollinations"
    assert result.metadata["fallback_from"] == "huggingface"
