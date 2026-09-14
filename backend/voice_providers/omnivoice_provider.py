"""Personal Voice provider backed by ResembleAI Chatterbox Multilingual.

The historical ``omnivoice`` provider key is retained so existing LUMINA jobs
and UI contracts do not need a migration.  Synthesis is performed by the
official ResembleAI Chatterbox Multilingual ZeroGPU Space: text + the user's
saved reference sample -> cloned Greek speech.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx


class OmniVoiceExternalProvider:
    name = "omnivoice"
    MAX_OUTPUT_BYTES = 50 * 1024 * 1024
    DEFAULT_SPACE_ID = "ResembleAI/Chatterbox-Multilingual-TTS"
    DEFAULT_SPACE_URL = "https://resembleai-chatterbox-multilingual-tts.hf.space"
    DEFAULT_API_NAME = "/generate_tts_audio"

    capabilities = {
        "modes": ["voice-clone"],
        "formats": ["wav"],
        "credential_ready": True,
        "voice_cloning": True,
        "identity_preservation": True,
        "singing_voice_conversion": False,
        "languages": ["el-GR"],
        "shared_runtime": True,
    }

    def __init__(self):
        self.space_id = (os.environ.get("CHATTERBOX_SPACE_ID") or self.DEFAULT_SPACE_ID).strip()
        self.space_url = (os.environ.get("CHATTERBOX_SPACE_URL") or self.DEFAULT_SPACE_URL).rstrip("/")
        self.api_name = (os.environ.get("CHATTERBOX_API_NAME") or self.DEFAULT_API_NAME).strip()
        self.hf_token = (os.environ.get("HF_TOKEN") or "").strip()
        parsed = urlparse(self.space_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("CHATTERBOX_SPACE_URL must be a valid HTTP address.")

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
                response = await client.get(self.space_url)
                response.raise_for_status()
            return {
                "ok": True,
                "provider": self.name,
                "engine": "chatterbox-multilingual",
                "space_id": self.space_id,
            }
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    @staticmethod
    def _suffix_for_mime(mime: str) -> str:
        value = (mime or "").lower().split(";", 1)[0]
        return {
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/flac": ".flac",
            "audio/ogg": ".ogg",
            "audio/webm": ".webm",
            "audio/mp4": ".m4a",
            "audio/x-m4a": ".m4a",
            "audio/aac": ".aac",
        }.get(value, ".wav")

    def _generate_sync(self, text: str, reference_audio: bytes, reference_mime: str) -> bytes:
        try:
            from gradio_client import Client, handle_file
        except Exception as exc:
            raise RuntimeError("The Chatterbox client is not installed.") from exc

        suffix = self._suffix_for_mime(reference_mime)
        with tempfile.TemporaryDirectory(prefix="lumina-chatterbox-") as workdir:
            reference_path = Path(workdir) / f"reference{suffix}"
            reference_path.write_bytes(reference_audio)

            kwargs = {}
            if self.hf_token:
                kwargs["token"] = self.hf_token
            client = Client(self.space_id, **kwargs)
            result = client.predict(
                text,
                "el",
                handle_file(str(reference_path)),
                0.5,
                0.8,
                0,
                0.5,
                api_name=self.api_name,
            )

            output_path = None
            if isinstance(result, str):
                output_path = result
            elif isinstance(result, (list, tuple)) and result:
                first = result[0]
                if isinstance(first, str):
                    output_path = first
                elif isinstance(first, dict):
                    output_path = first.get("path") or first.get("name")
            elif isinstance(result, dict):
                output_path = result.get("path") or result.get("name")

            if not output_path:
                raise RuntimeError("Chatterbox returned no audio file.")
            try:
                payload = Path(str(output_path)).read_bytes()
            except OSError as exc:
                raise RuntimeError("Chatterbox output could not be read.") from exc

        return payload

    async def generate(self, text: str, voice: str, output_format: str, **options) -> tuple[bytes, str, dict]:
        clean_text = " ".join((text or "").split()).strip()
        reference_audio = options.get("reference_audio")
        if not clean_text:
            raise ValueError("Enter text to generate speech.")
        # The official public demo currently accepts 300 characters per call.
        if len(clean_text) > 300:
            raise ValueError("Personal Voice currently supports up to 300 characters per generation.")
        if voice != "personal-user":
            raise ValueError("Personal Voice requires the personal-user voice.")
        if output_format != "wav":
            raise ValueError("Personal Voice currently generates WAV audio.")
        if not isinstance(reference_audio, bytes) or not reference_audio:
            raise ValueError("Record or upload a clean voice sample.")

        reference_mime = str(options.get("reference_mime") or "audio/wav")
        try:
            payload = await asyncio.to_thread(
                self._generate_sync,
                clean_text,
                reference_audio,
                reference_mime,
            )
        except Exception as exc:
            raise RuntimeError(f"Chatterbox Personal Voice could not complete the request: {exc}") from exc

        if len(payload) < 1000 or len(payload) > self.MAX_OUTPUT_BYTES:
            raise RuntimeError("Chatterbox returned an invalid audio file.")
        if payload[:4] != b"RIFF":
            raise RuntimeError("Chatterbox returned an unsupported audio format.")

        return payload, "audio/wav", {
            "provider": self.name,
            "engine": "chatterbox-multilingual",
            "runtime": "huggingface-zerogpu",
            "space_id": self.space_id,
            "voice": voice,
            "language": "el-GR",
            "voice_cloning": True,
            "identity_preservation": True,
            "shared_runtime": True,
            "mock": False,
        }
