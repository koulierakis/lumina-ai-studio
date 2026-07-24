"""Official Google Gemini image provider for Lumina AI Desktop.

Uses the supported ``google-genai`` SDK for image generation and editing.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import random
from collections.abc import Iterable
from typing import List, Optional

from PIL import Image

try:
    from google import genai
    from google.genai import types
except ImportError:  # dependency validation is exposed through provider status
    genai = None
    types = None

from .base import ErrorKind, GeneratedImage, GenerationInput, ImageProvider, ProviderCapabilities, ProviderError


IDENTITY_PRESERVATION_SYSTEM = (
    "You are a photorealistic image-generation assistant that PRESERVES the "
    "identity of the person shown in the provided reference photographs with "
    "maximum accuracy. Preserve facial structure, forehead, hairline, hair "
    "colour and greying pattern, eyebrows, eye shape and colour, nose, lips, "
    "ears, jawline, beard density, wrinkles, skin texture and pores, natural "
    "age, facial asymmetry, neck, shoulders and body proportions. DO NOT "
    "beautify. DO NOT make the person younger. DO NOT smooth the skin. DO NOT "
    "alter facial features. Reproduce the SAME person, not a similar person. "
    "Only change scene, environment, outfit, pose, lighting and camera as "
    "instructed."
)

EDIT_SYSTEM = (
    "You are a photorealistic photo editor. Apply the requested edit while "
    "preserving everything else as closely as technically possible. If "
    "reference photographs of a person are supplied, preserve that person's "
    "identity exactly, including facial structure, hairline, grey hair, "
    "wrinkles, skin texture, natural age, asymmetry, beard density and body "
    "proportions. DO NOT beautify, make the person younger, or smooth the skin. "
    "When a mask is supplied, edit only the white or opaque region and keep "
    "the remainder of the source image unchanged."
)

ASPECT_HINT = {
    "1:1": "Square 1:1 aspect ratio.",
    "16:9": "Widescreen 16:9 aspect ratio.",
    "9:16": "Vertical 9:16 aspect ratio.",
    "4:5": "Portrait 4:5 aspect ratio.",
    "3:2": "Classic 3:2 aspect ratio.",
}

MIN_VALID_IMAGE_BYTES = 1024
MIN_VALID_DIMENSION = 16


def _api_keys() -> list[str]:
    raw = os.environ.get("GEMINI_API_KEY_ROTATION")
    if raw:
        keys = [key.strip() for key in raw.split(",") if key.strip()]
        if keys:
            return keys
    fallback = os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY")
    return [fallback] if fallback else []


def _api_key() -> Optional[str]:
    keys = _api_keys()
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0]
    return random.choice(keys)


def _guess_mime(data: bytes, fallback: str = "image/jpeg") -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return fallback


def _build_prompt(spec: GenerationInput) -> str:
    parts = [spec.prompt.strip()]
    if spec.scene:
        parts.append(f"Scene / location: {spec.scene}.")
    if spec.outfit:
        parts.append(f"Outfit: {spec.outfit}.")
    parts.append(ASPECT_HINT.get(spec.aspect_ratio, ""))
    if spec.negative_prompt:
        parts.append(f"Avoid: {spec.negative_prompt}.")
    if spec.reference_images:
        parts.append(
            "Use every attached photograph as an identity reference. Preserve "
            "the exact identity of the person. Produce a photorealistic result "
            "with natural, unretouched skin and natural age."
        )
    return " ".join(part for part in parts if part)


def _response_parts(response: object) -> Iterable[object]:
    """Yield inline parts from all google-genai response shapes we support."""

    yield from getattr(response, "parts", None) or []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        yield from getattr(content, "parts", None) or []


def _trace(event: dict) -> None:
    print("gemini_image_trace " + json.dumps(event, default=str, sort_keys=True))


def _json_default(value: object) -> str:
    return str(value)


def _full_response_json(response: object) -> str:
    if response is None:
        return ""
    for attr in ("model_dump_json", "json"):
        method = getattr(response, attr, None)
        if callable(method):
            try:
                return method()
            except TypeError:
                try:
                    return method(by_alias=True, exclude_none=False)
                except Exception:
                    pass
            except Exception:
                pass
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(response, attr, None)
        if callable(method):
            try:
                return json.dumps(method(), default=_json_default, ensure_ascii=False)
            except Exception:
                pass
    return json.dumps(response, default=_json_default, ensure_ascii=False)


def _extract_error_json(body: str) -> dict:
    try:
        parsed = json.loads(body)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            return error
    return {}


def _redact_headers(headers: object) -> object:
    if headers is None:
        return None
    try:
        items = dict(headers).items()
    except Exception:
        return str(headers)

    redacted = {}
    sensitive_names = ("authorization", "api-key", "apikey", "x-goog-api-key", "key", "token", "secret")
    for key, value in items:
        key_text = str(key)
        if any(marker in key_text.lower() for marker in sensitive_names):
            redacted[key_text] = "[REDACTED]"
        else:
            redacted[key_text] = value
    return redacted


def _print_gemini_http_diagnostics(exc: BaseException | None = None, response: object | None = None) -> None:
    http_response = response
    for attr in ("response", "_response", "http_response", "raw_response"):
        candidate = getattr(exc, attr, None) if exc is not None else None
        if candidate is not None:
            http_response = candidate
            break

    status_code = None
    headers = None
    body = ""

    for attr in ("status_code", "status", "code"):
        value = getattr(http_response, attr, None) if http_response is not None else None
        if value is not None:
            status_code = value
            break
    if status_code is None and exc is not None:
        for attr in ("status_code", "status", "code"):
            value = getattr(exc, attr, None)
            if value is not None:
                status_code = value
                break

    headers = getattr(http_response, "headers", None) if http_response is not None else None
    if headers is None and exc is not None:
        headers = getattr(exc, "headers", None)
    headers = _redact_headers(headers)

    for attr in ("text", "content", "body", "_body", "data"):
        value = getattr(http_response, attr, None) if http_response is not None else None
        if value:
            body = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
            break

    if not body and exc is not None:
        for attr in ("details", "message", "body", "response_body"):
            value = getattr(exc, attr, None)
            if value:
                body = str(value)
                break
    if not body and exc is not None:
        body = str(exc)
    if not body and response is not None:
        body = _full_response_json(response)

    error_json = _extract_error_json(body)
    print(
        "gemini_exception_type "
        + json.dumps(type(exc).__name__ if exc is not None else None, default=_json_default, ensure_ascii=False)
    )
    print(
        "gemini_exception_repr "
        + json.dumps(repr(exc) if exc is not None else None, default=_json_default, ensure_ascii=False)
    )
    print("gemini_http_status_code " + json.dumps(status_code, default=_json_default, ensure_ascii=False))
    print("gemini_http_response_headers " + json.dumps(headers, default=_json_default, ensure_ascii=False))
    print("gemini_http_full_json_body " + body)
    print("gemini_http_error_message " + json.dumps(error_json.get("message"), default=_json_default, ensure_ascii=False))
    print("gemini_http_error_status " + json.dumps(error_json.get("status"), default=_json_default, ensure_ascii=False))
    print("gemini_http_error_code " + json.dumps(error_json.get("code"), default=_json_default, ensure_ascii=False))
    print("gemini_http_error_details " + json.dumps(error_json.get("details"), default=_json_default, ensure_ascii=False))


def _response_structure(response: object) -> dict:
    candidates = getattr(response, "candidates", None) or []
    return {
        "response_type": type(response).__name__,
        "parts_count": len(getattr(response, "parts", None) or []),
        "candidates_count": len(candidates),
        "candidate_part_counts": [
            len(getattr(getattr(candidate, "content", None), "parts", None) or [])
            for candidate in candidates
        ],
        "text_length": len(getattr(response, "text", None) or ""),
    }


def _decode_image_payload(payload: bytes) -> tuple[str, tuple[int, int]]:
    if len(payload) < MIN_VALID_IMAGE_BYTES:
        raise ValueError(f"image payload too small: {len(payload)} bytes")
    with Image.open(io.BytesIO(payload)) as image:
        image.load()
        width, height = image.size
        image_format = image.format or ""
    if width < MIN_VALID_DIMENSION or height < MIN_VALID_DIMENSION:
        raise ValueError(f"image dimensions too small: {width}x{height}")
    return image_format, (width, height)


def _extract_image(response: object) -> GeneratedImage:
    _trace({"stage": "raw_response_structure", **_response_structure(response)})

    images: list[tuple[str, GeneratedImage, tuple[int, int], str]] = []
    seen_payloads: set[bytes] = set()

    for index, part in enumerate(_response_parts(response)):
        label = f"part[{index}]"
        if getattr(part, "thought", False):
            _trace({"stage": "part_skipped", "part": label, "reason": "thought"})
            continue

        inline_data = getattr(part, "inline_data", None)
        if inline_data is None:
            _trace({"stage": "part_skipped", "part": label, "reason": "no_inline_data"})
            continue

        data = getattr(inline_data, "data", None)
        if not data:
            _trace({"stage": "part_skipped", "part": label, "reason": "empty_inline_data"})
            continue

        if isinstance(data, str):
            data = base64.b64decode(data)

        mime = getattr(inline_data, "mime_type", None) or "image/png"
        payload = bytes(data)
        if payload in seen_payloads:
            _trace({"stage": "part_skipped", "part": label, "reason": "duplicate_payload"})
            continue
        seen_payloads.add(payload)

        png_header_valid = payload.startswith(b"\x89PNG\r\n\x1a\n")
        event = {
            "stage": "decoded_part",
            "part": label,
            "mime": mime,
            "decoded_byte_length": len(payload),
            "png_header_valid": png_header_valid,
        }
        try:
            image_format, dimensions = _decode_image_payload(payload)
        except Exception as exc:
            _trace({**event, "valid": False, "validation_error": str(exc)})
            continue
        _trace({**event, "valid": True, "image_format": image_format, "dimensions": dimensions})
        images.append((label, GeneratedImage(data=payload, mime_type=mime), dimensions, image_format))

    if not images:
        text = getattr(response, "text", None)
        detail = f": {text}" if text else ""
        _print_gemini_http_diagnostics(response=response)
        raise RuntimeError(f"Gemini returned no valid image bytes{detail}")

    # Some Gemini responses expose more than one inline image part. Choose the
    # largest payload so a tiny preview/placeholder cannot win by response order.
    selected_label, selected, dimensions, image_format = max(images, key=lambda item: len(item[1].data))
    _trace(
        {
            "stage": "selected_image_part",
            "part": selected_label,
            "mime": selected.mime_type,
            "decoded_byte_length": len(selected.data),
            "png_header_valid": selected.data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image_format": image_format,
            "dimensions": dimensions,
        }
    )
    return selected


class GeminiImageProvider(ImageProvider):
    name = "gemini"
    priority = 10
    capabilities = ProviderCapabilities(
        generation=True, editing=True, identity_references=True, masks=True,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        maximum_reference_images=5,
        maximum_outputs=4,
        models=("gemini-3.1-flash-image",),
    )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(_api_key()) and genai is not None

    def _model(self) -> str:
        return os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")

    def _client(self) -> genai.Client:
        key = _api_key()
        if genai is None:
            raise ProviderError(self.name, "google-genai is not installed", kind=ErrorKind.UNAVAILABLE)
        if not key:
            raise ProviderError(self.name, "GEMINI_API_KEY is not configured", kind=ErrorKind.AUTH)
        return genai.Client(api_key=key)

    def _generation_config(self, aspect_ratio: str) -> types.GenerateContentConfig:
        kwargs = {
            "response_modalities": ["TEXT", "IMAGE"],
            "system_instruction": IDENTITY_PRESERVATION_SYSTEM,
        }
        if aspect_ratio in ASPECT_HINT:
            kwargs["image_config"] = types.ImageConfig(aspect_ratio=aspect_ratio)
        return types.GenerateContentConfig(**kwargs)

    def _generate_sync(self, spec: GenerationInput) -> GeneratedImage:
        contents: list[object] = [_build_prompt(spec)]

        for index, raw in enumerate(spec.reference_images):
            mime = (
                spec.reference_mimes[index]
                if index < len(spec.reference_mimes)
                else _guess_mime(raw)
            )
            contents.append(types.Part.from_bytes(data=raw, mime_type=mime))

        # Keep a strong reference to the client for the entire HTTP request.
        # A temporary client object may be finalized and closed too early.
        with self._client() as client:
            try:
                response = client.models.generate_content(
                    model=self._model(),
                    contents=contents,
                    config=self._generation_config(spec.aspect_ratio or "1:1"),
                )
            except Exception as exc:
                _print_gemini_http_diagnostics(exc=exc)
                raise
            return _extract_image(response)

    async def _one_call(self, spec: GenerationInput) -> GeneratedImage:
        return await asyncio.to_thread(self._generate_sync, spec)

    async def generate(self, spec: GenerationInput) -> List[GeneratedImage]:
        count = max(1, min(4, int(spec.count or 1)))
        tasks = [self._one_call(spec) for _ in range(count)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: List[GeneratedImage] = []
        errors: List[str] = []

        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                output.append(result)

        if not output:
            message = "; ".join(errors) or "All generations failed"
            lower = message.lower()
            if "resource_exhausted" in lower or "quota" in lower:
                kind, retryable = ErrorKind.QUOTA, True
            elif "429" in lower or "rate" in lower:
                kind, retryable = ErrorKind.RATE_LIMIT, True
            elif "timeout" in lower:
                kind, retryable = ErrorKind.TIMEOUT, True
            else:
                kind, retryable = ErrorKind.UNAVAILABLE, True
            raise ProviderError(self.name, message, kind=kind, retryable=retryable)

        return output

    def _edit_sync(
        self,
        source_bytes: bytes,
        source_mime: str,
        instruction: str,
        mask_bytes: Optional[bytes],
        mask_mime: Optional[str],
        identity_refs: Optional[List[bytes]],
    ) -> GeneratedImage:
        prompt_parts = [instruction.strip() or "Enhance this image."]

        contents: list[object] = [
            "SOURCE IMAGE:",
            types.Part.from_bytes(
                data=source_bytes,
                mime_type=source_mime or _guess_mime(source_bytes),
            ),
        ]

        if mask_bytes:
            contents.extend(
                [
                    "EDIT MASK:",
                    types.Part.from_bytes(
                        data=mask_bytes,
                        mime_type=mask_mime or _guess_mime(mask_bytes, "image/png"),
                    ),
                ]
            )
            prompt_parts.append(
                "The image labelled EDIT MASK is a mask. White or opaque pixels "
                "identify the region to edit. Keep all other source-image pixels "
                "unchanged and blend the edited region naturally."
            )

        if identity_refs:
            prompt_parts.append(
                "The remaining images are identity references. Preserve the same "
                "person exactly, including facial structure, hairline, grey hair, "
                "wrinkles, skin texture, natural age and body proportions."
            )
            for index, raw in enumerate(identity_refs, start=1):
                contents.extend(
                    [
                        f"IDENTITY REFERENCE {index}:",
                        types.Part.from_bytes(data=raw, mime_type=_guess_mime(raw)),
                    ]
                )

        contents.insert(0, " ".join(prompt_parts))

        # Keep the client alive until the request and response parsing finish.
        with self._client() as client:
            try:
                response = client.models.generate_content(
                    model=self._model(),
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"],
                        system_instruction=EDIT_SYSTEM,
                    ),
                )
            except Exception as exc:
                _print_gemini_http_diagnostics(exc=exc)
                raise
            return _extract_image(response)

    async def edit(
        self,
        source_bytes: bytes,
        source_mime: str,
        instruction: str,
        mask_bytes: Optional[bytes] = None,
        mask_mime: Optional[str] = "image/png",
        identity_refs: Optional[List[bytes]] = None,
    ) -> GeneratedImage:
        return await asyncio.to_thread(
            self._edit_sync,
            source_bytes,
            source_mime,
            instruction,
            mask_bytes,
            mask_mime,
            identity_refs,
        )
