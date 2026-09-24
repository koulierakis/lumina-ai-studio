"""Configured-only provider adapter skeletons."""
from __future__ import annotations

import os
import asyncio
import base64
import httpx

from .base import (
    ImageProvider,
    ProviderCapabilities,
    ProviderConfigurationError,
    ProviderError,
    ErrorKind,
    GeneratedImage,
)


class CredentialedSkeletonProvider(ImageProvider):
    env_key = ""
    config_label = "API credentials"
    capabilities = ProviderCapabilities(
        generation=True,
        editing=False,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        maximum_outputs=4,
    )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv(cls.env_key))

    async def generate(self, spec):
        raise ProviderConfigurationError(
            self.name,
            f"{self.name} adapter requires a concrete API implementation before production use.",
        )


class FalImageProvider(CredentialedSkeletonProvider):
    """Qwen-Image-Edit-2509 on fal.ai.

    The model contract supports multi-image editing and Qwen officially documents
    keypoint-map conditioning. Factory callers must supply identity reference(s)
    first and the rendered pose condition last. This adapter is unavailable until
    FAL_KEY is configured; no request is made merely by health checking it.
    """
    name = "fal"
    priority = 30
    env_key = "FAL_KEY"
    model = "fal-ai/qwen-image-edit-2509"
    capabilities = ProviderCapabilities(
        generation=True,
        editing=True,
        identity_references=True,
        pose_conditioning=True,
        deterministic_seed=True,
        resolution_control=False,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        models=(model,),
        maximum_reference_images=3,
        maximum_outputs=1,
    )

    @staticmethod
    def _data_uri(data: bytes, mime: str) -> str:
        return f"data:{mime or 'image/png'};base64,{base64.b64encode(data).decode('ascii')}"

    async def generate(self, spec):
        key=os.getenv(self.env_key,"").strip()
        if not key:
            raise ProviderConfigurationError(self.name,"FAL_KEY is not configured.")
        refs=list(spec.reference_images or [])
        if len(refs)<2:
            raise ProviderError(self.name,"Qwen Factory generation requires identity reference plus pose condition.",kind=ErrorKind.INVALID_REQUEST,retryable=False,safe_message="Select an Identity Pack and provide a pose condition.")
        if len(refs)>self.capabilities.maximum_reference_images:
            raise ProviderError(self.name,"Too many Qwen reference images.",kind=ErrorKind.INVALID_REQUEST,retryable=False)
        mimes=list(spec.reference_mimes or [])
        image_urls=[self._data_uri(data,mimes[i] if i<len(mimes) else "image/png") for i,data in enumerate(refs)]
        payload={"prompt":spec.prompt,"image_urls":image_urls,"num_images":1,"output_format":"png","enable_safety_checker":True}
        if spec.negative_prompt: payload["negative_prompt"]=spec.negative_prompt
        if spec.seed is not None: payload["seed"]=int(spec.seed)
        url=f"https://queue.fal.run/{self.model}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0),trust_env=False) as client:
                response=await client.post(url,headers={"Authorization":f"Key {key}","Content-Type":"application/json"},json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name,str(exc),kind=ErrorKind.TIMEOUT,retryable=True,safe_message="Qwen image generation timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.name,str(exc),kind=ErrorKind.UNAVAILABLE,retryable=True,safe_message="fal.ai is temporarily unavailable.") from exc
        if response.status_code>=400:
            kind=ErrorKind.AUTH if response.status_code in {401,403} else ErrorKind.RATE_LIMIT if response.status_code==429 else ErrorKind.UNAVAILABLE
            raise ProviderError(self.name,f"fal HTTP {response.status_code}",kind=kind,retryable=response.status_code in {429,500,502,503,504},status_code=response.status_code,safe_message="Qwen image request could not be submitted.")
        body=response.json()
        # queue.fal.run may return a completed payload or a queue request. Do not
        # pretend queued work is a generated image; explicit queue polling is the
        # next integration step once credentials are approved.
        images=body.get("images") if isinstance(body,dict) else None
        if not images:
            raise ProviderError(self.name,"Qwen request was accepted but no synchronous image was returned.",kind=ErrorKind.UNAVAILABLE,retryable=True,safe_message="Qwen request was queued; asynchronous result polling is required.")
        item=images[0]; image_url=item.get("url")
        if not image_url:
            raise ProviderError(self.name,"Qwen returned no image URL.",kind=ErrorKind.UNAVAILABLE,retryable=True)
        async with httpx.AsyncClient(timeout=60.0,trust_env=False) as client:
            fetched=await client.get(image_url); fetched.raise_for_status()
        return [GeneratedImage(fetched.content,item.get("content_type","image/png"))]


class BflImageProvider(CredentialedSkeletonProvider):
    name = "bfl"
    priority = 40
    env_key = "BFL_API_KEY"


class ReplicateImageProvider(CredentialedSkeletonProvider):
    name = "replicate"
    priority = 50
    env_key = "REPLICATE_API_TOKEN"
