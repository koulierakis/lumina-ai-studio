"""VoiceStudio self-hosted adapter for LUMINA Personal Voice."""
from __future__ import annotations

import os
from urllib.parse import urlparse, urljoin

import httpx


class OmniVoiceExternalProvider:
    name = "omnivoice"
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
        self._origin = (parsed.scheme, parsed.netloc)
        self.api_key = (os.environ.get("VOICESTUDIO_API_KEY") or "").strip()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.get(f"{self.base_url}/health", headers=self._headers())
                response.raise_for_status()
            return {"ok": True, "provider": self.name, "engine": "VoiceStudio"}
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    def _safe_url(self, value: str) -> str:
        absolute = urljoin(f"{self.base_url}/", value)
        parsed = urlparse(absolute)
        if (parsed.scheme, parsed.netloc) != self._origin:
            raise RuntimeError("VoiceStudio returned an unsafe audio address.")
        return absolute

    async def generate(self, text: str, voice: str, output_format: str, **options) -> tuple[bytes, str, dict]:
        clean_text = " ".join((text or "").split()).strip()
        reference_audio = options.get("reference_audio")
        if not clean_text:
            raise ValueError("Enter text to generate speech.")
        if len(clean_text) > 2000:
            raise ValueError("Personal Voice text is limited to 2000 characters per generation.")
        if voice != "personal-user":
            raise ValueError("Personal Voice requires the personal-user voice.")
        if output_format != "wav":
            raise ValueError("Personal Voice currently generates WAV audio.")
        if not isinstance(reference_audio, bytes) or not reference_audio:
            raise ValueError("Record or upload a clean voice sample.")

        filename = str(options.get("reference_filename") or "reference.wav")
        mime = str(options.get("reference_mime") or "audio/wav")
        form = {
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
            response = await client.post(f"{self.base_url}/generate", headers=self._headers(), data=form, files=files)
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            if content_type.startswith("audio/"):
                payload = response.content
            else:
                body = response.json()
                candidate = body.get("audio_url") or body.get("url") or body.get("output_url") or body.get("audio")
                if isinstance(candidate, dict):
                    candidate = candidate.get("url") or candidate.get("path")
                if not candidate:
                    raise RuntimeError(f"VoiceStudio returned no audio: {body}")
                audio = await client.get(self._safe_url(str(candidate)), headers=self._headers())
                audio.raise_for_status()
                payload = audio.content

        if len(payload) < 256 or len(payload) > self.MAX_OUTPUT_BYTES:
            raise RuntimeError("VoiceStudio returned an invalid audio file.")

        return payload, "audio/wav", {
            "provider": self.name,
            "engine": "VoiceStudio",
            "voice": voice,
            "language": "el-GR",
            "voice_cloning": True,
            "identity_preservation": True,
            "shared_runtime": False,
            "mock": False,
        }
