from __future__ import annotations

import json
import os
import uuid
import urllib.error
import urllib.parse
import urllib.request


class ElevenLabsVoiceProvider:
    name = "elevenlabs"
    capabilities = {
        "modes": ["text-to-speech", "voice-clone"],
        "formats": ["mp3"],
        "languages": ["el-GR", "en"],
        "credential_ready": True,
        "voice_cloning": True,
        "style_control": True,
        "mock": False,
    }

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())

    @staticmethod
    def _api_key() -> str:
        key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured")
        return key

    @staticmethod
    def _style_settings(style: str) -> dict:
        """Translate a short style label or free-form Greek/English direction into voice settings.

        ElevenLabs TTS accepts numeric voice settings rather than a generic free-form
        style prompt for multilingual_v2. LUMINA keeps the user's natural-language
        direction and maps it locally, so style control does not require another paid
        model call.
        """
        style_text = (style or "calm").strip().lower()
        presets = {
            "calm": {"stability": 0.72, "similarity_boost": 0.88, "style": 0.12, "speed": 0.94},
            "corporate": {"stability": 0.78, "similarity_boost": 0.90, "style": 0.10, "speed": 0.98},
            "documentary": {"stability": 0.68, "similarity_boost": 0.90, "style": 0.22, "speed": 0.93},
            "podcast": {"stability": 0.62, "similarity_boost": 0.88, "style": 0.20, "speed": 1.00},
            "emotional": {"stability": 0.42, "similarity_boost": 0.86, "style": 0.42, "speed": 0.96},
            "energetic": {"stability": 0.40, "similarity_boost": 0.84, "style": 0.48, "speed": 1.08},
            "motivational": {"stability": 0.46, "similarity_boost": 0.86, "style": 0.42, "speed": 1.04},
            "commercial": {"stability": 0.54, "similarity_boost": 0.86, "style": 0.36, "speed": 1.03},
            "luxury": {"stability": 0.74, "similarity_boost": 0.91, "style": 0.18, "speed": 0.91},
            "cinematic": {"stability": 0.60, "similarity_boost": 0.90, "style": 0.30, "speed": 0.90},
            "radio": {"stability": 0.70, "similarity_boost": 0.88, "style": 0.22, "speed": 1.00},
            "audiobook": {"stability": 0.76, "similarity_boost": 0.90, "style": 0.14, "speed": 0.94},
        }
        if style_text in presets:
            settings = dict(presets[style_text])
        else:
            settings = dict(presets["calm"])
            keyword_presets = (
                (("επαγγελμα", "corporate", "business", "παρουσίαση", "σοβαρ"), "corporate"),
                (("ντοκιμαντέρ", "documentary", "αφηγη"), "documentary"),
                (("podcast", "συζήτηση", "συνομιλ"), "podcast"),
                (("συναισθη", "emotional", "συγκινη"), "emotional"),
                (("ενεργ", "energetic", "δυναμικ", "ένταση", "ενθουσια"), "energetic"),
                (("κίνητρο", "motivational", "εμπνευσ"), "motivational"),
                (("διαφήμι", "commercial", "promo"), "commercial"),
                (("πολυτελ", "luxury", "premium"), "luxury"),
                (("κινηματογραφ", "cinematic", "trailer"), "cinematic"),
                (("ραδιόφων", "radio", "broadcast"), "radio"),
                (("audiobook", "βιβλί", "ανάγνωση"), "audiobook"),
                (("ήρεμ", "calm", "χαλαρ", "gentle", "soft"), "calm"),
            )
            for words, preset_name in keyword_presets:
                if any(word in style_text for word in words):
                    settings = dict(presets[preset_name])
                    break
            if any(word in style_text for word in ("αργά", "αργο", "slow", "πιο αργ")):
                settings["speed"] = max(0.75, settings["speed"] - 0.12)
            if any(word in style_text for word in ("γρήγορα", "γρηγορ", "fast", "πιο γρήγ")):
                settings["speed"] = min(1.20, settings["speed"] + 0.12)
            if any(word in style_text for word in ("σταθερ", "controlled", "συγκρατη")):
                settings["stability"] = min(0.90, settings["stability"] + 0.10)
            if any(word in style_text for word in ("εκφρασ", "expressive", "θεατρ", "δραματικ")):
                settings["stability"] = max(0.30, settings["stability"] - 0.12)
                settings["style"] = min(0.55, settings["style"] + 0.18)
        settings["use_speaker_boost"] = True
        return settings

    async def generate(self, text: str, voice: str, output_format: str, **options):
        if output_format != "mp3":
            raise ValueError("ElevenLabs personal voice currently outputs MP3 in LUMINA.")
        voice_id = (voice or "").strip()
        if not voice_id or voice_id in {"personal-user", "lumina", "Kore"}:
            raise ValueError("A cloned ElevenLabs voice ID is required.")

        model = str(options.get("model") or "eleven_multilingual_v2")
        style = str(options.get("style") or "calm")
        payload = {
            "text": text,
            "model_id": model,
            "voice_settings": self._style_settings(style),
        }
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(voice_id)}?output_format=mp3_44100_128"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "xi-api-key": self._api_key(),
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(os.environ.get("ELEVENLABS_TIMEOUT_SECONDS", "180"))) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ElevenLabs TTS failed ({exc.code}): {detail[:500]}") from exc
        if not data:
            raise RuntimeError("ElevenLabs returned no audio data.")
        return data, "audio/mpeg", {
            "provider": "elevenlabs",
            "model": model,
            "voice_id": voice_id,
            "style_prompt": style,
            "voice_settings": payload["voice_settings"],
            "mock": False,
        }

    async def clone_voice(self, name: str, audio_files: list[tuple[str, str, bytes]], description: str = "") -> dict:
        if not audio_files:
            raise ValueError("At least one voice recording is required.")
        boundary = f"----LuminaVoice{uuid.uuid4().hex}"
        body = bytearray()

        def field(field_name: str, value: str) -> None:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode())
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        field("name", name)
        if description:
            field("description", description)
        field("remove_background_noise", "false")
        for filename, mime, data in audio_files:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode())
            body.extend(f"Content-Type: {mime or 'application/octet-stream'}\r\n\r\n".encode())
            body.extend(data)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        request = urllib.request.Request(
            "https://api.elevenlabs.io/v1/voices/add",
            data=bytes(body),
            headers={
                "xi-api-key": self._api_key(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(os.environ.get("ELEVENLABS_TIMEOUT_SECONDS", "180"))) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ElevenLabs voice cloning failed ({exc.code}): {detail[:500]}") from exc
        voice_id = str(result.get("voice_id") or "").strip()
        if not voice_id:
            raise RuntimeError("ElevenLabs did not return a voice ID.")
        return {
            "voice_id": voice_id,
            "requires_verification": bool(result.get("requires_verification", False)),
            "provider": "elevenlabs",
        }
