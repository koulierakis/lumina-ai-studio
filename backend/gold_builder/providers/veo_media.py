"""Google Veo 3.1 video provider using Gemini REST long-running operations."""
from __future__ import annotations

import base64
import os

import httpx

from .base import (
    ProviderError, VideoJob, VideoProvider, VideoRequest, VideoResponse, provider_exception,
)


def _mime_image(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ProviderError("Veo input is not a supported image")


def _mime_video(data: bytes) -> str:
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    raise ProviderError("Veo input is not a supported video")


class VeoVideoProvider(VideoProvider):
    id = "gemini-veo"
    provider = "gemini"
    model = os.environ.get("GB_VEO_MODEL", "veo-3.1-generate-preview")
    capabilities = frozenset({"text_to_video", "image_to_video", "text_image_to_video"})

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    def _key(self) -> str:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise ProviderError("GEMINI_API_KEY not configured")
        return key

    async def submit(self, req: VideoRequest) -> VideoJob:
        if req.negative_prompt:
            raise ProviderError("Veo adapter does not support negative_prompt; try another video provider")
        if req.operation == "transform":
            raise ProviderError(
                "Veo video extension only accepts recent Veo-generated video handles; "
                "generic video_to_video is not supported by this adapter"
            )
        if float(req.seconds) not in {4.0, 6.0, 8.0}:
            raise ProviderError(
                "Veo 3.1 supports only 4, 6, or 8 second generation; try another video provider"
            )
        instance: dict = {"prompt": req.prompt}
        if req.input_image:
            instance["image"] = {
                "inlineData": {
                    "mimeType": _mime_image(req.input_image),
                    "data": base64.b64encode(req.input_image).decode("ascii"),
                }
            }
        elif req.reference_images and req.operation in {"animate", "text_image"}:
            first = req.reference_images[0]
            instance["image"] = {
                "inlineData": {
                    "mimeType": _mime_image(first),
                    "data": base64.b64encode(first).decode("ascii"),
                }
            }
        seconds = int(req.seconds)
        parameters: dict = {
            "numberOfVideos": 1,
            "durationSeconds": str(seconds),
            "aspectRatio": req.aspect_ratio if req.aspect_ratio in {"16:9", "9:16"} else "16:9",
            "resolution": "720p",
        }
        if req.seed is not None:
            parameters["seed"] = req.seed

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:predictLongRunning"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    url,
                    headers={"x-goog-api-key": self._key(), "Content-Type": "application/json"},
                    json={"instances": [instance], "parameters": parameters},
                )
                r.raise_for_status()
                body = r.json()
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None
        name = body.get("name")
        if not name:
            raise ProviderError("Veo response contained no operation name")
        job = VideoJob(id=name, status="queued", provider=self.provider, model=self.model)
        setattr(job, "_actual_duration", float(seconds))
        return job

    async def status(self, job: VideoJob) -> VideoJob:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/{job.id}",
                    headers={"x-goog-api-key": self._key()},
                )
                r.raise_for_status()
                body = r.json()
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None
        if body.get("error"):
            job.status = "failed"
            job.error = "Veo operation failed"
            return job
        job.status = "completed" if body.get("done") else "running"
        setattr(job, "_veo_body", body)
        return job

    async def download(self, job: VideoJob) -> VideoResponse:
        body = getattr(job, "_veo_body", None)
        if not isinstance(body, dict):
            job = await self.status(job)
            body = getattr(job, "_veo_body", None)
        samples = (((body or {}).get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or []
        if not samples:
            raise ProviderError("Veo operation contained no generated video")
        video = (samples[0] or {}).get("video") or {}
        uri = video.get("uri")
        if not isinstance(uri, str) or not uri.startswith("https://"):
            raise ProviderError("Veo operation contained no downloadable video URI")
        try:
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
                r = await client.get(uri, headers={"x-goog-api-key": self._key()})
                r.raise_for_status()
                data = r.content
        except Exception as exc:  # noqa: BLE001
            raise provider_exception(self.id, exc) from None
        if not data or len(data) > 250 * 1024 * 1024:
            raise ProviderError("Veo video download is empty or too large")
        return VideoResponse(
            video=data,
            mime="video/mp4",
            provider=self.provider,
            model=self.model,
            duration=float(getattr(job, "_actual_duration", 8.0)),
        )
