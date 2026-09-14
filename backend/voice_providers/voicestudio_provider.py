"""VoiceStudio self-hosted provider for LUMINA Personal Voice."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx


class VoiceStudioProvider:
    name = "voicestudio"
    MAX_OUTPUT_BYTES = 50 * 1024 * 1024

    capabilities = {
        "modes": ["voice-clone"],
        "formats": ["wav"],
        "credential_ready": True,
        "voice_cloning": True,
        "identity_preservation": True,
        "singing_voice_conversion": False,
        "languages": ["el-GR"],
        "shared_runtime": False,
    }

    def __init__(self):
        self.base_url = (os.environ.get("VOICESTUDIO_BASE_URL") or "https://lumina-voicestudio.onrender.com").rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("VOICESTUDIO_BASE_URL must be a valid HTTP address.")
        self.api_key = (os.environ.get("VOICESTUDIO_API_KEY") or "").strip()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        return {"Authorization": f"Bearer {self.api_key}"}

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.get(f"{self.base_url}/health", headers=self._headers())
                response.raise_for_status()
            return {"ok": True, "provider": self.name, "engine": "VoiceStudio"}
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    async def generate(self, text: str, voice: str, output_format: str, **options) -> tuple[bytes, str, dict]:
        clean_text = " ".join((text or "").split()).strip()
        reference_audio = options.get("reference_audio")
        if not clean_text:
            raise ValueError("Enter text to generate speech.")
        if len(clean_text) > 2000:
            raise ValueError("Personal Voice text is limited to 2000 characters per generation.")
        if voice != "personal-user":
            raise ValueError("VoiceStudio requires the personal voice option.")
        if output_format != "wav":
            raise ValueError("VoiceStudio Personal Voice currently generates WAV audio.")
        if not isinstance(reference_audio, bytes) or not reference_audio:
            raise ValueError("Record or upload a clean voice sample.")

        filename = str(options.get("reference_filename") or "reference.wav")
        mime = str(options.get("reference_mime") or "audio/wav")
        data = {
            "text": clean_text,
            "language": "Greek",
            "ref_text": str(options.get("reference_text") or ""),
            "num_step": "32",
            "guidance_scale": "2.0",
            "speed": "1.0",
            "denoise": "true",
            "postprocess_output": "true",
        }
        files = {"ref_audio": (filename, reference_audio, mime)}

        async with httpx.AsyncClient(timeout=httpx.Timeout(900), follow_redirects=True, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/generate",
                headers=self._headers(),
                data=data,
                files=files,
            )
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            if content_type.startswith("audio/"):
                payload = response.content
            else:
                body = response.json()
                candidate = body.get("audio_url") or body.get("url") or body.get("output_url")
                if not candidate:
                    raise RuntimeError(f"VoiceStudio returned no audio: {body}")
                audio = await client.get(candidate, headers=self._headers())
                audio.raise_for_status()
                payload = audio.content

        if len(payload) < 256 or len(payload) > self.MAX_OUTPUT_BYTES:
            raise RuntimeError("VoiceStudio returned an invalid audio file.")

        return payload, "audio/wav", {
            "provider": self.name,
            "voice": voice,
            "language": "el-GR",
            "voice_cloning": True,
            "identity_preservation": True,
            "engine": "VoiceStudio",
            "mock": False,
        }
