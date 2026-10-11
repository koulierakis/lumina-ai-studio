"""Optional generic adapter for a self-hosted media gateway.

The gateway is configured only by trusted server-side environment variables.
It can point at ComfyUI wrappers, Diffusers services, RunPod/Modal/Vast
gateways, or a private GPU service without changing Gold Builder routing.
"""
from __future__ import annotations

import base64
import os
from urllib.parse import urlparse

import httpx

from .base import (
    ImageProvider, ImageRequest, ImageResponse, ProviderError,
    VideoProvider, VideoRequest, VideoResponse, provider_exception,
)


def _base_url() -> str:
    value = os.environ.get("GB_MEDIA_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise ProviderError("GB_MEDIA_BASE_URL not configured")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderError("GB_MEDIA_BASE_URL must be an http(s) URL")
    return value


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("GB_MEDIA_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderError("unsupported image input for self-hosted media")


def _video_mime(data: bytes) -> str:
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    raise ProviderError("unsupported video input for self-hosted media")


def _decode_output(item, *, media_type: str) -> tuple[bytes, str]:
    if isinstance(item, str):
        encoded = item
        mime = "image/png" if media_type == "image" else "video/mp4"
    elif isinstance(item, dict):
        encoded = item.get("base64") or item.get("data") or item.get("content")
        mime = item.get("mime") or item.get("mime_type") or item.get("content_type")
        if not mime:
            mime = "image/png" if media_type == "image" else "video/mp4"
    else:
        raise ProviderError("self-hosted media response has invalid output shape")
    if not encoded:
        raise ProviderError("self-hosted media response contains no base64 output")
    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ProviderError("self-hosted media returned invalid base64") from exc
    return data, str(mime).split(";")[0]


class _SelfHostedTransport:
    provider = "self-hosted"

    def available(self) -> bool:
        return bool(os.environ.get("GB_MEDIA_BASE_URL", "").strip())

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{_base_url()}{path}",
                    headers=_headers(),
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.provider, exc) from None
        if not isinstance(body, dict):
            raise ProviderError("self-hosted media response must be a JSON object")
        return body


class SelfHostedImageProvider(ImageProvider, _SelfHostedTransport):
    id = "self-hosted-image"
    model = os.environ.get("GB_MEDIA_IMAGE_MODEL", "self-hosted-image")
    capabilities = frozenset({"text_to_image", "image_to_image", "reference_images"})

    def available(self) -> bool:
        return _SelfHostedTransport.available(self)

    async def _run(self, req: ImageRequest, *, edit: bool) -> ImageResponse:
        payload = {
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "size": req.size,
            "width": req.width,
            "height": req.height,
            "aspect_ratio": req.aspect_ratio,
            "quality": req.quality,
            "style": req.style,
            "seed": req.seed,
            "n": req.n,
            "output_format": req.output_format,
        }
        if req.input_images:
            payload["images"] = [
                _data_uri(data, _image_mime(data)) for data in req.input_images
            ]
        body = await self._post("/image/edit" if edit else "/image/generate", payload)
        raw = body.get("images")
        if raw is None and body.get("image") is not None:
            raw = [body["image"]]
        if not isinstance(raw, list) or not raw:
            raise ProviderError("self-hosted image response contained no images")
        images, mimes = [], []
        for item in raw:
            data, mime = _decode_output(item, media_type="image")
            images.append(data)
            mimes.append(mime)
        return ImageResponse(
            images=images,
            provider=self.provider,
            model=str(body.get("model") or self.model),
            mime_types=mimes,
        )

    async def generate(self, req: ImageRequest) -> ImageResponse:
        return await self._run(req, edit=False)

    async def edit(self, req: ImageRequest) -> ImageResponse:
        if not req.input_images:
            raise ProviderError("self-hosted image edit requires input image")
        return await self._run(req, edit=True)


class SelfHostedVideoProvider(VideoProvider, _SelfHostedTransport):
    id = "self-hosted-video"
    model = os.environ.get("GB_MEDIA_VIDEO_MODEL", "self-hosted-video")
    capabilities = frozenset({
        "text_to_video", "image_to_video", "text_image_to_video", "video_to_video",
    })

    def available(self) -> bool:
        return _SelfHostedTransport.available(self)

    async def generate(self, req: VideoRequest) -> VideoResponse:
        payload = {
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "operation": req.operation,
            "seconds": req.seconds,
            "size": req.size,
            "aspect_ratio": req.aspect_ratio,
            "quality": req.quality,
            "seed": req.seed,
            "output_format": req.output_format,
        }
        if req.input_image:
            payload["input_image"] = _data_uri(req.input_image, _image_mime(req.input_image))
        if req.reference_images:
            payload["reference_images"] = [
                _data_uri(data, _image_mime(data)) for data in req.reference_images
            ]
        if req.input_video:
            payload["input_video"] = _data_uri(req.input_video, _video_mime(req.input_video))
        body = await self._post("/video/generate", payload)
        raw = body.get("video")
        if raw is None:
            raise ProviderError("self-hosted video response contained no video")
        data, mime = _decode_output(raw, media_type="video")
        duration = body.get("duration")
        try:
            duration = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        return VideoResponse(
            video=data,
            mime=mime,
            provider=self.provider,
            model=str(body.get("model") or self.model),
            duration=duration,
        )
