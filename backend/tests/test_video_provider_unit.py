from __future__ import annotations

import asyncio
import io

from PIL import Image
from video_providers import available_video_providers, get_video_provider
from video_providers.base import VideoGenerationInput


def _source_png() -> bytes:
    image = Image.new("RGB", (40, 30), "#c49b5a")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


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
    assert "mock" in available_video_providers()


def test_mock_provider_supports_text_only_request_for_local_workflows():
    result = asyncio.run(get_video_provider("mock").generate(VideoGenerationInput(
        mode="text-to-video", prompt="golden abstract motion", duration_seconds=3, aspect_ratio="16:9",
    )))
    assert result.data.startswith((b"GIF87a", b"GIF89a"))
