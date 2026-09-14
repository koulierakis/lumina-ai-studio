"""Personal Voice adapter with a self-hosted VoiceStudio path and a lightweight fallback."""
from __future__ import annotations

import os
from urllib.parse import urljoin, urlparse

import httpx

from .edge_provider import EdgeVoiceProvider


class OmniVoiceExternalProvider:
    """Keep the historical provider name while using infrastructure we control.

    VoiceStudio is available as the full-quality path. On small Render instances
    it is intentionally disabled and LUMINA uses Greek Edge TTS followed by the
    dedicated OpenVoice V2 timbre converter. This avoids the unreliable public
    Hugging Face OmniVoice Space and keeps Personal Voice usable on free hosting.
    """

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
        self.voicestudio_url = (os.environ.get("VOICESTUDIO_BASE_URL") or "https://lumina-voicestudio.onrender.com").rstrip("/")
        parsed = urlparse(self.voicestudio_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("VOICESTUDIO_BASE_URL must be a valid HTTP address.")
        self._vs_origin = (parsed.scheme, parsed.netloc)
        self.voicestudio_key = (os.environ.get("VOICESTUDIO_API_KEY") or "").strip()
        self.voicestudio_enabled = (os.environ.get("VOICESTUDIO_ENABLED") or "0").strip().lower() in {"1", "true", "yes", "on"}

        self.openvoice_url = (os.environ.get("OPENVOICE_WORKER_BASE_URL") or "https://lumina-openvoice-v2.onrender.com").rstrip("/")
        ov = urlparse(self.openvoice_url)
        if ov.scheme not in {"http", "https"} or not ov.netloc:
            raise ValueError("OPENVOICE_WORKER_BASE_URL must be a valid HTTP address.")
        self.openvoice_key = (os.environ.get("OPENVOICE_WORKER_API_KEY") or "").strip()

    def _vs_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.voicestudio_key}"} if self.voicestudio_key else {}

    def _ov_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.openvoice_key}"} if self.openvoice_key else {}

    async def health(self) -> dict:
        target = self.voicestudio_url if self.voicestudio_enabled else self.openvoice_url
        path = "/health"
        headers = self._vs_headers() if self.voicestudio_enabled else self._ov_headers()
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.get(f"{target}{path}", headers=headers)
                response.raise_for_status()
            return {
                "ok": True,
                "provider": self.name,
                "engine": "VoiceStudio" if self.voicestudio_enabled else "Edge TTS + OpenVoice V2",
            }
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    def _safe_vs_url(self, value: str) -> str:
        absolute = urljoin(f"{self.voicestudio_url}/", value)
        parsed = urlparse(absolute)
        if (parsed.scheme, parsed.netloc) != self._vs_origin:
            raise RuntimeError("VoiceStudio returned an unsafe audio address.")
        return absolute

    async def _generate_voicestudio(self, clean_text: str, reference_audio: bytes, filename: str, mime: str, **options):
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
            response = await client.post(
                f"{self.voicestudio_url}/generate",
                headers=self._vs_headers(), data=form, files=files,
            )
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
                audio = await client.get(self._safe_vs_url(str(candidate)), headers=self._vs_headers())
                audio.raise_for_status()
                payload = audio.content
        return payload, "VoiceStudio"

    async def _generate_openvoice(self, clean_text: str, reference_audio: bytes, filename: str, mime: str, **options):
        # Create fluent Greek speech locally in LUMINA's backend, then transfer
        # the user's saved timbre with our dedicated OpenVoice V2 worker.
        source_provider = EdgeVoiceProvider()
        source_audio, source_mime, _ = await source_provider.generate(
            clean_text, "lumina-male", "mp3", style=options.get("style")
        )
        files = {
            "source_audio": ("source.mp3", source_audio, source_mime),
            "reference_audio": (filename, reference_audio, mime),
        }
        form = {"output_format": "wav", "engine": "openvoice-v2"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(900), follow_redirects=True, trust_env=False) as client:
            response = await client.post(
                f"{self.openvoice_url}/convert",
                headers=self._ov_headers(), data=form, files=files,
            )
            response.raise_for_status()
            payload = response.content
        return payload, "Edge TTS + OpenVoice V2"

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

        if self.voicestudio_enabled:
            try:
                payload, engine = await self._generate_voicestudio(clean_text, reference_audio, filename, mime, **options)
            except Exception:
                payload, engine = await self._generate_openvoice(clean_text, reference_audio, filename, mime, **options)
        else:
            payload, engine = await self._generate_openvoice(clean_text, reference_audio, filename, mime, **options)

        if len(payload) < 256 or len(payload) > self.MAX_OUTPUT_BYTES:
            raise RuntimeError("The Personal Voice engine returned an invalid audio file.")

        return payload, "audio/wav", {
            "provider": self.name,
            "engine": engine,
            "voice": voice,
            "language": "el-GR",
            "voice_cloning": True,
            "identity_preservation": True,
            "shared_runtime": False,
            "mock": False,
        }
