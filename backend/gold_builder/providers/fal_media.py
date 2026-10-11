"""fal.ai media providers using the public queue REST API.

No fal SDK dependency is required. Binary inputs are sent as data URIs; queue
responses provide status/result URLs which are polled with bounded deadlines.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import (
    ImageProvider, ImageRequest, ImageResponse,
    ProviderError, ProviderTimeoutError,
    VideoProvider, VideoJob, VideoRequest, VideoResponse,
    provider_exception,
)


def _mime_image(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderError("fal input is not a supported image")


def _mime_video(data: bytes) -> str:
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    raise ProviderError("fal input is not a supported video")


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _validate_public_https_url(url: str, *, queue_only: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProviderError("fal returned a non-public media URL")
    if queue_only and parsed.hostname != "queue.fal.run":
        raise ProviderError("fal queue returned an unexpected callback host")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProviderError("fal media host could not be resolved") from exc
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved:
            raise ProviderError("fal media URL resolved to a private or reserved address")
    return url


def _size(req: ImageRequest) -> Any:
    if req.width and req.height:
        return {"width": int(req.width), "height": int(req.height)}
    mapping = {
        "1024x1024": "square_hd",
        "1536x1024": "landscape_4_3",
        "1024x1536": "portrait_4_3",
    }
    return mapping.get(req.size, "square_hd")


class _FalQueue:
    base = "https://queue.fal.run"

    def _key(self) -> str:
        key = os.environ.get("FAL_KEY", "").strip()
        if not key:
            raise ProviderError("FAL_KEY not configured")
        return key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {self._key()}", "Content-Type": "application/json"}

    async def submit_json(self, model: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                r = await client.post(f"{self.base}/{model}", headers=self._headers(), json=payload)
                r.raise_for_status()
                body = r.json()
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(f"fal:{model}", exc) from None
        if not isinstance(body, dict) or not body.get("request_id"):
            raise ProviderError("fal queue returned no request_id")
        return body

    async def wait_result(self, submitted: dict, *, timeout_s: float = 150.0) -> dict:
        status_url = submitted.get("status_url")
        result_url = submitted.get("response_url")
        if not status_url or not result_url:
            raise ProviderError("fal queue response missing status/result URL")
        status_url = _validate_public_https_url(status_url, queue_only=True)
        result_url = _validate_public_https_url(result_url, queue_only=True)
        deadline = asyncio.get_running_loop().time() + timeout_s
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise ProviderTimeoutError("fal media job timed out")
                    r = await client.get(status_url, headers=self._headers())
                    r.raise_for_status()
                    status = r.json()
                    state = str(status.get("status") or "").upper()
                    if state == "COMPLETED":
                        rr = await client.get(result_url, headers=self._headers())
                        rr.raise_for_status()
                        body = rr.json()
                        return body.get("data") if isinstance(body.get("data"), dict) else body
                    if state in {"FAILED", "CANCELLED"}:
                        raise ProviderError(f"fal media job {state.lower()}")
                    await asyncio.sleep(min(2.0, max(0.2, remaining)))
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise provider_exception("fal-queue", exc) from None

    async def fetch_media(self, url: str, *, max_bytes: int) -> tuple[bytes, str]:
        if not isinstance(url, str):
            raise ProviderError("fal returned an invalid media URL")
        url = _validate_public_https_url(url)
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.content
                if not data or len(data) > max_bytes:
                    raise ProviderError("fal media download is empty or too large")
                mime = (r.headers.get("content-type") or "").split(";")[0]
                return data, mime
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise provider_exception("fal-download", exc) from None


class FalImageProvider(ImageProvider, _FalQueue):
    id = "fal-flux"
    billable_async_job = True
    provider = "fal"
    model = os.environ.get("GB_FAL_IMAGE_MODEL", "fal-ai/flux-2")
    edit_model = os.environ.get("GB_FAL_IMAGE_EDIT_MODEL", "fal-ai/flux-2/edit")
    capabilities = frozenset({"text_to_image", "image_to_image", "reference_images"})

    def available(self) -> bool:
        return bool(os.environ.get("FAL_KEY", "").strip())

    async def _run(self, req: ImageRequest, model: str, *, edit: bool) -> ImageResponse:
        payload: dict[str, Any] = {
            "prompt": req.prompt,
            "num_images": max(1, min(req.n, 4)),
            "image_size": _size(req),
            "output_format": "jpeg" if req.output_format.lower() in {"jpg", "jpeg"} else req.output_format.lower(),
            "enable_safety_checker": True,
        }
        if req.seed is not None:
            payload["seed"] = req.seed
        if edit:
            if not req.input_images:
                raise ProviderError("fal image edit requires an input image")
            payload["image_urls"] = [
                _data_uri(data, _mime_image(data)) for data in req.input_images[:4]
            ]
        submitted = await self.submit_json(model, payload)
        body = await self.wait_result(submitted)
        images = body.get("images") or []
        out: list[bytes] = []
        mimes: list[str] = []
        for item in images:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            data, declared = await self.fetch_media(item["url"], max_bytes=25 * 1024 * 1024)
            out.append(data)
            mimes.append((item.get("content_type") or declared or _mime_image(data)).split(";")[0])
        if not out:
            raise ProviderError("fal image response contained no images")
        return ImageResponse(out, self.provider, model, mimes)

    async def generate(self, req: ImageRequest) -> ImageResponse:
        return await self._run(req, self.model, edit=False)

    async def edit(self, req: ImageRequest) -> ImageResponse:
        return await self._run(req, self.edit_model, edit=True)


class FalVideoProvider(VideoProvider, _FalQueue):
    """Wan 2.6 provider with Kling V3 fallback exposed as separate instances."""

    capabilities = frozenset({"text_to_video", "image_to_video", "text_image_to_video", "video_to_video"})

    def __init__(self, *, family: str = "wan"):
        self.family = family
        self.provider = "fal"
        if family == "kling":
            self.capabilities = frozenset({"text_to_video", "image_to_video", "text_image_to_video"})
            self.id = "fal-kling-video"
            self.model = os.environ.get(
                "GB_FAL_KLING_TEXT_MODEL",
                "fal-ai/kling-video/v3/standard/text-to-video",
            )
        else:
            self.id = "fal-wan-video"
            self.model = os.environ.get("GB_FAL_VIDEO_TEXT_MODEL", "wan/v2.6/text-to-video")

    def available(self) -> bool:
        return bool(os.environ.get("FAL_KEY", "").strip())

    def _model_for(self, operation: str) -> str:
        if self.family == "kling":
            if operation in {"animate", "text_image"}:
                return os.environ.get(
                    "GB_FAL_KLING_IMAGE_MODEL",
                    "fal-ai/kling-video/v3/standard/image-to-video",
                )
            if operation == "transform":
                raise ProviderError("Kling fallback does not expose video_to_video in this adapter")
            return self.model
        if operation in {"animate", "text_image"}:
            return os.environ.get("GB_FAL_VIDEO_IMAGE_MODEL", "wan/v2.6/image-to-video")
        if operation == "transform":
            return os.environ.get("GB_FAL_VIDEO_REFERENCE_MODEL", "wan/v2.6/reference-to-video")
        return self.model

    async def submit(self, req: VideoRequest) -> VideoJob:
        model = self._model_for(req.operation or "generate")
        if self.family == "wan":
            duration = min((5, 10, 15), key=lambda value: abs(value - req.seconds))
        else:
            duration = max(3, min(15, int(round(req.seconds))))
        payload: dict[str, Any] = {
            "prompt": req.prompt,
            "duration": str(duration),
            "aspect_ratio": req.aspect_ratio or "16:9",
        }
        if req.seed is not None and self.family == "wan":
            payload["seed"] = req.seed
        if req.negative_prompt:
            payload["negative_prompt"] = req.negative_prompt

        if req.operation in {"animate", "text_image"}:
            image = req.input_image or (req.reference_images[0] if req.reference_images else None)
            if not image:
                raise ProviderError("fal image-to-video requires an image")
            payload["image_url"] = _data_uri(image, _mime_image(image))
        elif req.operation == "transform":
            if not req.input_video:
                raise ProviderError("fal video transform requires input video")
            payload["video_urls"] = [_data_uri(req.input_video, _mime_video(req.input_video))]

        submitted = await self.submit_json(model, payload)
        job = VideoJob(
            id=submitted["request_id"],
            status="queued",
            provider=self.provider,
            model=model,
        )
        setattr(job, "_fal_status_url", submitted.get("status_url"))
        setattr(job, "_fal_response_url", submitted.get("response_url"))
        setattr(job, "_actual_duration", float(duration))
        return job

    async def status(self, job: VideoJob) -> VideoJob:
        status_url = getattr(job, "_fal_status_url", None)
        if not status_url:
            raise ProviderError("fal video job missing status URL")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(status_url, headers=self._headers())
                r.raise_for_status()
                body = r.json()
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None
        state = str(body.get("status") or "").upper()
        job.status = {
            "COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled",
            "IN_PROGRESS": "running", "IN_QUEUE": "queued",
        }.get(state, "running")
        return job

    async def download(self, job: VideoJob) -> VideoResponse:
        response_url = getattr(job, "_fal_response_url", None)
        if not response_url:
            raise ProviderError("fal video job missing result URL")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(response_url, headers=self._headers())
                r.raise_for_status()
                body = r.json()
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        item = data.get("video") if isinstance(data, dict) else None
        if not isinstance(item, dict) or not item.get("url"):
            raise ProviderError("fal video response contained no video")
        video, declared = await self.fetch_media(item["url"], max_bytes=250 * 1024 * 1024)
        return VideoResponse(
            video=video,
            mime=(item.get("content_type") or declared or "video/mp4").split(";")[0],
            provider=self.provider,
            model=job.model,
            duration=float(getattr(job, "_actual_duration", 0.0)) or None,
        )
