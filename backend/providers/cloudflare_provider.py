"""Cloudflare Workers AI image provider for Lumina AI Desktop.

Uses Cloudflare-hosted FLUX models through the Workers AI REST API. The
provider supports text-to-image and identity-reference generation. FLUX.2
Workers AI models currently accept at most four reference images, so a Lumina
Identity Pack with five references is deterministically reduced to four for
this fallback provider.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import mimetypes
import os
import random
import urllib.error
import urllib.request
import uuid
from typing import List

from PIL import Image

from .base import (
    ErrorKind,
    GeneratedImage,
    GenerationInput,
    ImageProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderInvalidResponseError,
)


DEFAULT_MODEL = "@cf/black-forest-labs/flux-2-dev"
REFERENCE_LIMIT = 4
REFERENCE_MAX_SIDE = 511


class CloudflareWorkersAIProvider(ImageProvider):
    name = "cloudflare"
    priority = 11
    capabilities = ProviderCapabilities(
        generation=True,
        editing=False,
        identity_references=True,
        masks=False,
        multiple_outputs=True,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        models=(
            "@cf/black-forest-labs/flux-2-dev",
            "@cf/black-forest-labs/flux-2-klein-4b",
            "@cf/black-forest-labs/flux-1-schnell",
        ),
        # Lumina packs may contain five refs; Workers AI receives the first four.
        maximum_reference_images=5,
        maximum_outputs=4,
    )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("CLOUDFLARE_API_TOKEN") and os.getenv("CLOUDFLARE_ACCOUNT_ID"))

    def _model(self, spec: GenerationInput) -> str:
        return spec.model or os.getenv("CLOUDFLARE_IMAGE_MODEL") or DEFAULT_MODEL

    @staticmethod
    def _dimensions(aspect_ratio: str) -> tuple[int, int]:
        return {
            "1:1": (1024, 1024),
            "16:9": (1344, 768),
            "9:16": (768, 1344),
            "4:5": (896, 1120),
            "3:2": (1216, 832),
        }.get(aspect_ratio, (1024, 1024))

    @staticmethod
    def _prompt(spec: GenerationInput, reference_count: int) -> str:
        parts = [spec.prompt.strip()]
        if spec.scene:
            parts.append(f"Scene/location: {spec.scene}.")
        if spec.outfit:
            parts.append(f"Outfit: {spec.outfit}.")
        if spec.negative_prompt:
            parts.append(f"Avoid: {spec.negative_prompt}.")
        if reference_count:
            parts.append(
                "The attached input images are identity references of the same person. "
                "Preserve the exact identity, facial structure, hairline, grey hair, "
                "wrinkles, skin texture, natural age, asymmetry and body proportions. "
                "Do not beautify or make the person younger. Use the references only "
                "to preserve identity while following the requested scene and outfit."
            )
        return " ".join(part for part in parts if part)

    @staticmethod
    def _prepare_reference(raw: bytes) -> tuple[bytes, str]:
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
            image.thumbnail((REFERENCE_MAX_SIDE, REFERENCE_MAX_SIDE), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True)
            return output.getvalue(), "image/jpeg"

    @staticmethod
    def _multipart(fields: dict[str, str], files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
        boundary = "----LuminaCloudflare" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        for field_name, filename, content_type, payload in files:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    (
                        f'Content-Disposition: form-data; name="{field_name}"; '
                        f'filename="{filename}"\r\n'
                    ).encode(),
                    f"Content-Type: {content_type}\r\n\r\n".encode(),
                    payload,
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode())
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _safe_error(status: int, body: str) -> ProviderError:
        code = None
        message = "Cloudflare Workers AI request failed."
        try:
            payload = json.loads(body)
            errors = payload.get("errors") or []
            if errors:
                code = errors[0].get("code")
                message = errors[0].get("message") or message
        except Exception:
            pass

        if status in {401, 403}:
            return ProviderError(
                "cloudflare",
                message,
                kind=ErrorKind.AUTH,
                retryable=False,
                status_code=status,
                safe_message="Cloudflare Workers AI credentials or account access are invalid.",
            )
        if status == 429 and code == 3036:
            return ProviderError(
                "cloudflare",
                message,
                kind=ErrorKind.QUOTA,
                retryable=True,
                status_code=status,
                safe_message="Cloudflare Workers AI daily free allocation is exhausted.",
            )
        if status == 429:
            return ProviderError(
                "cloudflare",
                message,
                kind=ErrorKind.RATE_LIMIT,
                retryable=True,
                status_code=status,
                safe_message="Cloudflare Workers AI is temporarily rate-limited or out of capacity.",
            )
        if status == 400:
            return ProviderError(
                "cloudflare",
                message,
                kind=ErrorKind.INVALID_REQUEST,
                retryable=False,
                status_code=status,
                safe_message="Cloudflare Workers AI rejected the image request.",
            )
        return ProviderError(
            "cloudflare",
            message,
            kind=ErrorKind.UNAVAILABLE,
            retryable=status >= 500,
            status_code=status,
            safe_message="Cloudflare Workers AI is temporarily unavailable.",
        )

    def _call_sync(self, spec: GenerationInput) -> GeneratedImage:
        token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        if not token or not account_id:
            raise ProviderError(
                self.name,
                "Cloudflare credentials are not configured.",
                kind=ErrorKind.AUTH,
                retryable=False,
            )

        model = self._model(spec)
        width, height = self._dimensions(spec.aspect_ratio)
        refs = list(spec.reference_images[:REFERENCE_LIMIT])
        prompt = self._prompt(spec, len(refs))
        seed = spec.seed if spec.seed is not None else random.randint(1, 2_147_483_647)

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        headers = {"Authorization": f"Bearer {token}"}

        if model.endswith("flux-1-schnell"):
            payload = json.dumps({"prompt": prompt, "seed": seed, "steps": 4}).encode("utf-8")
            content_type = "application/json"
        else:
            fields = {
                "prompt": prompt,
                "width": str(width),
                "height": str(height),
                "seed": str(seed),
            }
            if model.endswith("flux-2-dev"):
                fields["steps"] = str(int(os.getenv("CLOUDFLARE_FLUX2_STEPS", "20")))
            files: list[tuple[str, str, str, bytes]] = []
            for index, raw in enumerate(refs):
                prepared, mime = self._prepare_reference(raw)
                ext = mimetypes.guess_extension(mime) or ".jpg"
                files.append((f"input_image_{index}", f"identity_{index}{ext}", mime, prepared))
            payload, content_type = self._multipart(fields, files)

        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={**headers, "Content-Type": content_type},
        )
        timeout = float(os.getenv("CLOUDFLARE_AI_TIMEOUT_SECONDS", "120"))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise self._safe_error(exc.code, body) from exc
        except Exception as exc:
            raise ProviderError(
                self.name,
                str(exc),
                kind=ErrorKind.UNAVAILABLE,
                retryable=True,
                safe_message="Cloudflare Workers AI request failed.",
            ) from exc

        try:
            parsed = json.loads(body)
            result = parsed.get("result") or {}
            encoded = result.get("image")
            if not encoded:
                raise ValueError("missing result.image")
            image_bytes = base64.b64decode(encoded)
        except Exception as exc:
            raise ProviderInvalidResponseError(
                self.name,
                "Cloudflare Workers AI returned no valid image bytes.",
            ) from exc

        if len(image_bytes) < 1024:
            raise ProviderInvalidResponseError(self.name)
        return GeneratedImage(data=image_bytes, mime_type="image/jpeg")

    async def generate(self, spec: GenerationInput) -> List[GeneratedImage]:
        count = max(1, min(int(spec.count or 1), 4))
        tasks = [asyncio.to_thread(self._call_sync, spec) for _ in range(count)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        images: list[GeneratedImage] = []
        first_error: Exception | None = None
        for result in results:
            if isinstance(result, Exception):
                first_error = first_error or result
            else:
                images.append(result)
        if images:
            return images
        if isinstance(first_error, ProviderError):
            raise first_error
        if first_error:
            raise ProviderError(
                self.name,
                str(first_error),
                kind=ErrorKind.UNAVAILABLE,
                retryable=True,
                safe_message="Cloudflare Workers AI generation failed.",
            ) from first_error
        raise ProviderInvalidResponseError(self.name)
