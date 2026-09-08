"""Hugging Face Gradio Whisper Large-V3 provider for LUMINA Voice Studio."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from gradio_client import Client, handle_file

from .base import BaseSTTProvider


DEFAULT_WHISPER_SPACE = "hf-audio/whisper-large-v3"
DEFAULT_WHISPER_API_NAME = "/predict"


class WhisperHFProvider(BaseSTTProvider):
    name = "whisper-hf"
    capabilities = {
        "timestamps": False,
        "languages": ["auto", "el", "en"],
        "credential_ready": True,
        "model": "openai/whisper-large-v3",
        "space": DEFAULT_WHISPER_SPACE,
    }

    @staticmethod
    def _guess_suffix(data: bytes) -> str:
        if data.startswith(b"RIFF"):
            return ".wav"
        if data.startswith(b"OggS"):
            return ".ogg"
        if data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
            return ".mp3"
        if data.startswith(b"\x1aE\xdf\xa3"):
            return ".webm"
        return ".audio"

    async def transcribe(self, data: bytes, language: str = "auto") -> dict:
        if not data:
            raise ValueError("Audio input is empty.")

        space = os.environ.get("HF_WHISPER_SPACE", DEFAULT_WHISPER_SPACE).strip()
        api_name = os.environ.get("HF_WHISPER_API_NAME", DEFAULT_WHISPER_API_NAME).strip()
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        timeout = float(os.environ.get("HF_STT_TIMEOUT_SECONDS", "900"))

        temp_path = None
        try:
            suffix = self._guess_suffix(data)
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as audio_file:
                audio_file.write(data)
                audio_file.flush()
                temp_path = audio_file.name

            def run_prediction():
                client_kwargs = {"verbose": False}
                if token:
                    client_kwargs["hf_token"] = token
                client = Client(space, **client_kwargs)
                return client.predict(
                    handle_file(temp_path),
                    "transcribe",
                    api_name=api_name,
                )

            result = await asyncio.wait_for(asyncio.to_thread(run_prediction), timeout=timeout)
            if isinstance(result, (tuple, list)):
                result = result[0] if result else ""
            if isinstance(result, dict):
                text = result.get("text") or result.get("transcription") or result.get("value") or ""
            else:
                text = str(result or "")

            text = text.strip()
            if not text:
                raise ValueError("Whisper returned an empty transcription.")

            return {
                "text": text,
                "timestamps": [],
                "language": language or "auto",
                "provider": self.name,
                "model": "openai/whisper-large-v3",
                "space": space,
            }
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass
