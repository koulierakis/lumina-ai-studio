"""External OmniVoice adapter using its public Gradio HTTP API."""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import httpx


class OmniVoiceExternalProvider:
    name = "omnivoice"
    DEFAULT_BASE_URL = "https://k2-fsa-omnivoice.hf.space"
    MAX_OUTPUT_BYTES = 50 * 1024 * 1024

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

    def __init__(self, base_url: str | None = None, transport=None):
        self.base_url = (base_url or os.environ.get("OMNIVOICE_BASE_URL") or self.DEFAULT_BASE_URL).rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OMNIVOICE_BASE_URL must be a valid HTTP address.")
        self._origin = (parsed.scheme, parsed.netloc)
        self._transport = transport

    async def health(self) -> dict:
        try:
            async with self._client(30) as client:
                response = await client.get("/gradio_api/info")
                response.raise_for_status()
            return {"ok": True, "provider": self.name, "shared_runtime": True}
        except Exception as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(timeout), follow_redirects=False, trust_env=False, transport=self._transport)

    @staticmethod
    def _complete_payload(sse: str):
        event = None
        for line in sse.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "complete":
                return json.loads(line.split(":", 1)[1].strip())
            elif line.startswith("data:") and event == "error":
                raise RuntimeError("The external voice engine could not complete the request.")
        raise RuntimeError("The external voice engine returned an incomplete response.")

    def _safe_output_url(self, value: str) -> str:
        parsed = urlparse(value)
        if (parsed.scheme, parsed.netloc) != self._origin:
            raise RuntimeError("The external voice engine returned an unsafe output address.")
        return value

    async def generate(self, text: str, voice: str, output_format: str, **options) -> tuple[bytes, str, dict]:
        clean_text = " ".join((text or "").split()).strip()
        reference_audio = options.get("reference_audio")
        if not clean_text:
            raise ValueError("Enter text to generate speech.")
        if len(clean_text) > 2000:
            raise ValueError("Personal Voice text is limited to 2000 characters per generation.")
        if voice != "personal-user":
            raise ValueError("OmniVoice requires the personal voice option.")
        if output_format != "wav":
            raise ValueError("OmniVoice currently generates WAV audio.")
        if not isinstance(reference_audio, bytes) or not reference_audio:
            raise ValueError("Record or upload a 3–10 second voice sample.")

        filename = str(options.get("reference_filename") or "reference.wav")
        mime = str(options.get("reference_mime") or "audio/wav")
        async with self._client(300) as client:
            upload = await client.post("/gradio_api/upload", files={"files": (filename, reference_audio, mime)})
            upload.raise_for_status()
            paths = upload.json()
            if not isinstance(paths, list) or not paths or not isinstance(paths[0], str):
                raise RuntimeError("The external voice engine rejected the sample.")

            reference = {"path": paths[0], "meta": {"_type": "gradio.FileData"}}
            # OmniVoice _gen_core contract (v0.1.4):
            # text, language, ref_audio, instruct, num_step, guidance_scale,
            # denoise, speed, duration, preprocess_prompt, postprocess_output,
            # mode, ref_text.  Keep these positions exact: the public Space
            # changed this contract and the previous adapter sent a shifted
            # 12-value payload, causing every clone request to fail.
            request = {
                "data": [
                    clean_text,
                    "Greek",
                    reference,
                    None,
                    32,
                    2.0,
                    True,
                    1.0,
                    None,
                    True,
                    True,
                    "clone",
                    options.get("reference_text") or None,
                ]
            }
            queued = await client.post("/gradio_api/call/_clone_fn", json=request)
            queued.raise_for_status()
            event_id = queued.json().get("event_id")
            if not event_id:
                raise RuntimeError("The external voice engine did not start the request.")

            completed = await client.get(f"/gradio_api/call/_clone_fn/{event_id}")
            completed.raise_for_status()
            payload = self._complete_payload(completed.text)
            output = payload[0] if isinstance(payload, list) and payload else None
            output_url = output.get("url") if isinstance(output, dict) else None
            if not output_url:
                raise RuntimeError("The external voice engine returned no audio.")

            audio = await client.get(self._safe_output_url(output_url))
            audio.raise_for_status()
            data = audio.content
            if len(data) < 256 or len(data) > self.MAX_OUTPUT_BYTES:
                raise RuntimeError("The external voice engine returned an invalid audio file.")

        return data, "audio/wav", {
            "provider": self.name,
            "voice": voice,
            "language": "el-GR",
            "voice_cloning": True,
            "identity_preservation": True,
            "shared_runtime": True,
            "mock": False,
        }
