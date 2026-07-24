"""ComfyUI provider adapter."""
from __future__ import annotations

import os

import requests

from .base import ImageProvider, ProviderCapabilities, ProviderConfigurationError


class ComfyUIProvider(ImageProvider):
    name = "comfyui"
    priority = 5
    capabilities = ProviderCapabilities(
        generation=True,
        editing=False,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        maximum_outputs=4,
    )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("COMFYUI_WORKFLOW_PATH"))

    async def health_check(self):
        status = await super().health_check()
        base_url = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/")
        workflow = os.getenv("COMFYUI_WORKFLOW_PATH")
        if not workflow:
            status.healthy = False
            status.available = False
            status.detail = "COMFYUI_WORKFLOW_PATH is not configured"
            return status
        try:
            response = requests.get(f"{base_url}/system_stats", timeout=3)
            status.healthy = response.status_code < 500
            status.available = status.configured and status.healthy
            status.detail = "ready" if status.available else "ComfyUI server is unavailable"
        except requests.RequestException:
            status.healthy = False
            status.available = False
            status.detail = "ComfyUI server is unreachable"
        return status

    async def generate(self, spec):
        raise ProviderConfigurationError(
            self.name,
            "ComfyUI workflow execution is not implemented; configure a concrete workflow runner before production use.",
        )
