"""Luma Dream Machine adapter; credentials never leave the backend."""
from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

import requests

from .base import (
    GeneratedVideo,
    ProviderJob,
    VideoGenerationInput,
    VideoProvider,
    VideoProviderCapabilities,
    VideoProviderError,
)


class LumaVideoProvider(VideoProvider):
    name = "luma"
    supports_async_jobs = True
    capabilities = VideoProviderCapabilities(
        text_to_video=True, image_to_video=True, output_formats=("video/mp4",),
        resolutions=("540p", "720p", "1080p", "4k"), durations=(5,),
        aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
        cancellation=True, max_image_inputs=1, max_prompt_length=1000,
    )

    def __init__(self) -> None:
        self.api_key = os.environ.get("LUMA_API_KEY", "").strip()
        self.base_url = os.environ.get("LUMA_API_BASE", "https://api.lumalabs.ai/dream-machine/v1").rstrip("/")
        self.model = os.environ.get("LUMA_MODEL", "ray-2").strip() or "ray-2"
        self.timeout = max(1, int(os.environ.get("LUMA_TIMEOUT_SECONDS", "30")))
        self.image_url_base = os.environ.get("LUMA_IMAGE_URL_BASE", "").strip().rstrip("/")

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("LUMA_API_KEY", "").strip())

    async def _request(self, method: str, path_or_url: str, *, json: dict | None = None, authenticated: bool = True) -> requests.Response:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        headers = {"Authorization": f"Bearer {self.api_key}"} if authenticated else {}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await asyncio.to_thread(requests.request, method, url, json=json, headers=headers, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.25 * (attempt + 1)); continue
                raise VideoProviderError(self.name, "Luma network request failed", "The video service is temporarily unavailable. Please retry.", retryable=True) from exc
            if response.status_code in {401, 403}:
                raise VideoProviderError(self.name, f"Luma authentication failed ({response.status_code})", "The Luma video service is not configured correctly.")
            if response.status_code in {400, 404, 409, 422}:
                raise VideoProviderError(self.name, f"Luma request rejected ({response.status_code})", "The video request was rejected by the provider. Check the selected settings.")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    await asyncio.sleep(0.25 * (attempt + 1)); continue
                raise VideoProviderError(self.name, f"Luma service error ({response.status_code})", "The video service is temporarily unavailable. Please retry.", retryable=True)
            if response.status_code >= 300:
                raise VideoProviderError(self.name, f"Unexpected Luma response ({response.status_code})")
            return response
        raise VideoProviderError(self.name, "Luma request exhausted", retryable=True) from last_error

    def _payload(self, spec: VideoGenerationInput) -> dict[str, Any]:
        if spec.mode not in {"text-to-video", "image-to-video"}:
            raise VideoProviderError(self.name, "Unsupported Luma mode", "This provider currently supports text-to-video and image-to-video only.")
        if len(spec.prompt) > self.capabilities.max_prompt_length:
            raise VideoProviderError(self.name, "Luma prompt too long", "The prompt is too long for the selected video provider.")
        if spec.duration_seconds not in self.capabilities.durations or spec.resolution not in self.capabilities.resolutions or spec.aspect_ratio not in self.capabilities.aspect_ratios:
            raise VideoProviderError(self.name, "Unsupported Luma setting", "One or more selected settings are not supported by this video provider.")
        prompt = spec.prompt.strip()
        if spec.negative_prompt.strip(): prompt += f". Avoid: {spec.negative_prompt.strip()}"
        payload: dict[str, Any] = {"prompt": prompt, "model": self.model, "resolution": spec.resolution, "duration": f"{spec.duration_seconds}s", "aspect_ratio": spec.aspect_ratio}
        if spec.mode == "image-to-video":
            if not spec.source_urls:
                raise VideoProviderError(self.name, "No public source URL", "Image-to-video requires a configured private media CDN URL.")
            payload["keyframes"] = {"frame0": {"type": "image", "url": spec.source_urls[0]}}
        return payload

    async def submit(self, spec: VideoGenerationInput) -> ProviderJob:
        response = await self._request("POST", "/generations", json=self._payload(spec))
        try: data = response.json()
        except ValueError as exc: raise VideoProviderError(self.name, "Malformed Luma submission response") from exc
        job_id = data.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise VideoProviderError(self.name, "Luma submission response missing id")
        return ProviderJob(id=job_id, state=str(data.get("state", "queued")), metadata={"model": self.model})

    async def poll(self, provider_job_id: str) -> ProviderJob:
        response = await self._request("GET", f"/generations/{provider_job_id}")
        try: data = response.json()
        except ValueError as exc: raise VideoProviderError(self.name, "Malformed Luma status response") from exc
        state = str(data.get("state", ""))
        if not state: raise VideoProviderError(self.name, "Luma status response missing state")
        assets = data.get("assets") or {}
        output_url = assets.get("video") if isinstance(assets, dict) else None
        failure = data.get("failure_reason")
        return ProviderJob(id=provider_job_id, state=state, output_url=output_url if isinstance(output_url, str) else None, metadata={"failure_reason": bool(failure), "model": self.model})

    async def download(self, provider_job: ProviderJob) -> GeneratedVideo:
        if not provider_job.output_url or urlparse(provider_job.output_url).scheme not in {"https", "http"}:
            raise VideoProviderError(self.name, "Luma completed job has no valid video URL")
        response = await self._request("GET", provider_job.output_url, authenticated=False)
        data = response.content
        if not data: raise VideoProviderError(self.name, "Luma returned an empty video")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        mime = "video/webm" if content_type == "video/webm" or provider_job.output_url.lower().split("?", 1)[0].endswith(".webm") else "video/mp4"
        return GeneratedVideo(data, mime, duration_seconds=None, resolution=None, metadata={"provider_job_id": provider_job.id, "model": self.model})

    async def cancel(self, provider_job_id: str) -> None:
        await self._request("DELETE", f"/generations/{provider_job_id}")
