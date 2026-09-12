"""Cloud adapter for OpenVoice V2 tone-color conversion.

The heavy OpenVoice runtime is intentionally kept outside the Render web service.
Set OPENVOICE_V2_ENDPOINT to an HTTPS endpoint that accepts multipart fields
``source_audio`` and ``reference_audio`` and returns either raw audio bytes or
JSON containing ``audio_base64`` plus an optional ``mime_type``.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

import httpx


class ToneConversionError(RuntimeError):
    """Safe, classified failure from the OpenVoice conversion stage."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToneConversionResult:
    audio: bytes
    mime_type: str
    metadata: dict


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class OpenVoiceV2ToneConverter:
    name = "openvoice-v2"

    def __init__(
        self,
        endpoint: str = "",
        api_key: str = "",
        timeout_seconds: float = 90.0,
        required: bool = False,
    ) -> None:
        self.endpoint = endpoint.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 300.0))
        self.required = bool(required)

    @classmethod
    def from_env(cls) -> "OpenVoiceV2ToneConverter":
        raw_timeout = os.environ.get("OPENVOICE_V2_TIMEOUT_SECONDS", "90")
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = 90.0
        return cls(
            endpoint=os.environ.get("OPENVOICE_V2_ENDPOINT", ""),
            api_key=os.environ.get("OPENVOICE_V2_API_KEY", ""),
            timeout_seconds=timeout,
            required=_truthy(os.environ.get("OPENVOICE_V2_REQUIRED", "0")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    async def convert(
        self,
        source_audio: bytes,
        source_mime: str,
        reference_audio: bytes,
        reference_mime: str,
        output_format: str = "wav",
    ) -> ToneConversionResult:
        if not self.configured:
            raise ToneConversionError("not_configured", "OpenVoice V2 endpoint is not configured.")
        if not source_audio:
            raise ToneConversionError("empty_source", "Base speech audio is empty.")
        if not reference_audio:
            raise ToneConversionError("empty_reference", "Reference voice sample is empty.")

        headers = {"Accept": "audio/*, application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        files = {
            "source_audio": ("source.mp3", source_audio, source_mime or "audio/mpeg"),
            "reference_audio": ("reference.wav", reference_audio, reference_mime or "audio/wav"),
        }
        form = {
            "output_format": str(output_format or "wav"),
            "engine": "openvoice-v2",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
                response = await client.post(self.endpoint, headers=headers, files=files, data=form)
        except httpx.TimeoutException as exc:
            raise ToneConversionError("timeout", "OpenVoice V2 conversion timed out.") from exc
        except httpx.HTTPError as exc:
            raise ToneConversionError("unavailable", "OpenVoice V2 service is unavailable.") from exc

        if response.status_code >= 400:
            raise ToneConversionError(
                f"http_{response.status_code}",
                f"OpenVoice V2 service returned HTTP {response.status_code}.",
            )

        content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if content_type.startswith("audio/"):
            if not response.content:
                raise ToneConversionError("empty_output", "OpenVoice V2 returned empty audio.")
            return ToneConversionResult(
                audio=response.content,
                mime_type=content_type,
                metadata={"tone_converter": self.name, "transport": "raw-audio"},
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToneConversionError("invalid_response", "OpenVoice V2 returned an unsupported response.") from exc

        encoded = payload.get("audio_base64")
        if not encoded and isinstance(payload.get("audio"), dict):
            encoded = payload["audio"].get("base64")
        if not isinstance(encoded, str) or not encoded.strip():
            raise ToneConversionError("invalid_response", "OpenVoice V2 response did not contain audio_base64.")
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ToneConversionError("invalid_base64", "OpenVoice V2 returned invalid audio data.") from exc
        if not audio:
            raise ToneConversionError("empty_output", "OpenVoice V2 returned empty audio.")

        mime_type = str(payload.get("mime_type") or "audio/wav").split(";", 1)[0].strip().lower()
        if not mime_type.startswith("audio/"):
            raise ToneConversionError("invalid_mime", "OpenVoice V2 returned a non-audio MIME type.")
        return ToneConversionResult(
            audio=audio,
            mime_type=mime_type,
            metadata={"tone_converter": self.name, "transport": "json-base64"},
        )
