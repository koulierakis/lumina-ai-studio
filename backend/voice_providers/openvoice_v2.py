"""Personal Voice adapter for LUMINA Voice Studio.

The historical OpenVoice V2 class name is retained for compatibility with
existing persisted jobs and API contracts. When CHATTERBOX_SPACE_ID is set,
Personal Voice now prefers direct Chatterbox Multilingual synthesis:

    original text + reference voice -> generated personal voice

This matches the Hugging Face flow that produces the best speaker identity.
If the original text bridge is unavailable, the older Chatterbox VC path is
kept as a compatibility fallback.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from .voice_text_bridge import take_source_text


class ToneConversionError(RuntimeError):
    """Safe, classified failure from the personal-voice stage."""

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


def _suffix_for_mime(mime: str, default: str = ".wav") -> str:
    mime = (mime or "").lower().split(";", 1)[0]
    return {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/aac": ".aac",
    }.get(mime, default)


_LOCAL_MODEL = None
_LOCAL_MODEL_LOCK = asyncio.Lock()


class OpenVoiceV2ToneConverter:
    """Compatibility adapter for LUMINA Personal Voice."""

    name = "openvoice-v2"

    def __init__(
        self,
        endpoint: str = "",
        api_key: str = "",
        timeout_seconds: float = 90.0,
        required: bool = False,
        local_enabled: bool = False,
        chatterbox_space_id: str = "",
        chatterbox_hf_token: str = "",
        chatterbox_api_name: str = "/convert",
        chatterbox_direct_api_name: str = "/generate_greek_voice",
    ) -> None:
        self.endpoint = endpoint.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 300.0))
        self.required = bool(required)
        self.local_enabled = bool(local_enabled)
        self.chatterbox_space_id = chatterbox_space_id.strip()
        self.chatterbox_hf_token = chatterbox_hf_token.strip()
        self.chatterbox_api_name = (chatterbox_api_name or "/convert").strip() or "/convert"
        self.chatterbox_direct_api_name = (
            chatterbox_direct_api_name or "/generate_greek_voice"
        ).strip() or "/generate_greek_voice"

    @classmethod
    def from_env(cls) -> "OpenVoiceV2ToneConverter":
        raw_timeout = os.environ.get(
            "CHATTERBOX_TIMEOUT_SECONDS",
            os.environ.get("OPENVOICE_V2_TIMEOUT_SECONDS", "180"),
        )
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = 180.0
        return cls(
            endpoint=os.environ.get("OPENVOICE_V2_ENDPOINT", ""),
            api_key=os.environ.get("OPENVOICE_V2_API_KEY", ""),
            timeout_seconds=timeout,
            required=_truthy(os.environ.get("OPENVOICE_V2_REQUIRED", "0")),
            local_enabled=_truthy(os.environ.get("OPENVOICE_V2_LOCAL", "0")),
            chatterbox_space_id=os.environ.get("CHATTERBOX_SPACE_ID", ""),
            chatterbox_hf_token=os.environ.get("HF_TOKEN", ""),
            chatterbox_api_name=os.environ.get("CHATTERBOX_API_NAME", "/convert"),
            chatterbox_direct_api_name=os.environ.get(
                "CHATTERBOX_DIRECT_API_NAME", "/generate_greek_voice"
            ),
        )

    @property
    def configured(self) -> bool:
        return bool(self.chatterbox_space_id or self.endpoint) or self.local_enabled

    async def convert(
        self,
        source_audio: bytes,
        source_mime: str,
        reference_audio: bytes,
        reference_mime: str,
        output_format: str = "wav",
    ) -> ToneConversionResult:
        if not self.configured:
            raise ToneConversionError(
                "not_configured",
                "Personal Voice conversion is not configured.",
            )
        if not source_audio:
            raise ToneConversionError("empty_source", "Base speech audio is empty.")
        if not reference_audio:
            raise ToneConversionError("empty_reference", "Reference voice sample is empty.")

        # Preferred zero-monthly-cost cloud path. Recover the exact text that
        # produced the temporary Edge audio and send that text directly to
        # Chatterbox Multilingual together with the reference voice.
        if self.chatterbox_space_id:
            source_text = take_source_text(source_audio)
            try:
                if source_text:
                    return await asyncio.to_thread(
                        self._synthesize_chatterbox_space_sync,
                        source_text,
                        reference_audio,
                        reference_mime,
                    )
                return await asyncio.to_thread(
                    self._convert_chatterbox_space_sync,
                    source_audio,
                    source_mime,
                    reference_audio,
                    reference_mime,
                )
            except ToneConversionError:
                raise
            except Exception as exc:
                raise ToneConversionError(
                    "chatterbox_unavailable",
                    f"Chatterbox Space personal voice failed: {exc}",
                ) from exc

        if self.local_enabled and not self.endpoint:
            try:
                return await asyncio.to_thread(
                    self._convert_local_sync,
                    source_audio,
                    source_mime,
                    reference_audio,
                    reference_mime,
                )
            except ToneConversionError:
                raise
            except Exception as exc:
                raise ToneConversionError(
                    "local_runtime_error",
                    f"Local OpenVoice V2 failed: {exc}",
                ) from exc

        return await self._convert_remote(
            source_audio,
            source_mime,
            reference_audio,
            reference_mime,
            output_format,
        )

    def _client(self):
        try:
            from gradio_client import Client
        except Exception as exc:
            raise ToneConversionError(
                "chatterbox_client_missing",
                "gradio_client is required for the Chatterbox Space backend.",
            ) from exc
        kwargs = {}
        if self.chatterbox_hf_token:
            kwargs["token"] = self.chatterbox_hf_token
        return Client(self.chatterbox_space_id, **kwargs)

    @staticmethod
    def _result_path(result) -> str | None:
        if isinstance(result, str):
            return result
        if isinstance(result, (list, tuple)) and result:
            first = result[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                return first.get("path") or first.get("name")
        if isinstance(result, dict):
            return result.get("path") or result.get("name")
        return None

    @staticmethod
    def _read_result_audio(result) -> bytes:
        output_path = OpenVoiceV2ToneConverter._result_path(result)
        if not output_path:
            raise ToneConversionError(
                "chatterbox_invalid_response",
                "Chatterbox Space did not return an audio file.",
            )
        try:
            data = Path(str(output_path)).read_bytes()
        except OSError as exc:
            raise ToneConversionError(
                "chatterbox_output_missing",
                "Chatterbox output file could not be read.",
            ) from exc
        if not data:
            raise ToneConversionError(
                "chatterbox_empty_output",
                "Chatterbox returned empty audio.",
            )
        return data

    def _synthesize_chatterbox_space_sync(
        self,
        text: str,
        reference_audio: bytes,
        reference_mime: str,
    ) -> ToneConversionResult:
        """Direct multilingual TTS: text + reference speaker -> WAV."""
        try:
            from gradio_client import handle_file
        except Exception as exc:
            raise ToneConversionError(
                "chatterbox_client_missing",
                "gradio_client is required for the Chatterbox Space backend.",
            ) from exc

        reference_suffix = _suffix_for_mime(reference_mime, ".wav")
        with tempfile.TemporaryDirectory(prefix="lumina_chatterbox_direct_") as work:
            reference_path = Path(work) / f"reference{reference_suffix}"
            reference_path.write_bytes(reference_audio)
            try:
                client = self._client()
                result = client.predict(
                    text,
                    handle_file(str(reference_path)),
                    api_name=self.chatterbox_direct_api_name,
                )
            except Exception as exc:
                raise ToneConversionError(
                    "chatterbox_request_failed",
                    "The free Chatterbox Space could not complete direct Personal Voice synthesis.",
                ) from exc
            data = self._read_result_audio(result)

        return ToneConversionResult(
            audio=data,
            mime_type="audio/wav",
            metadata={
                "tone_converter": "chatterbox-multilingual",
                "engine": "chatterbox-multilingual",
                "personal_voice_mode": "direct-text-reference",
                "language": "el",
                "transport": "gradio-client",
                "runtime": "huggingface-space",
                "space_id": self.chatterbox_space_id,
                "api_name": self.chatterbox_direct_api_name,
                "zero_monthly_cost": True,
            },
        )

    def _convert_chatterbox_space_sync(
        self,
        source_audio: bytes,
        source_mime: str,
        reference_audio: bytes,
        reference_mime: str,
    ) -> ToneConversionResult:
        """Compatibility fallback using Chatterbox voice conversion."""
        try:
            from gradio_client import handle_file
        except Exception as exc:
            raise ToneConversionError(
                "chatterbox_client_missing",
                "gradio_client is required for the Chatterbox Space backend.",
            ) from exc

        source_suffix = _suffix_for_mime(source_mime, ".wav")
        reference_suffix = _suffix_for_mime(reference_mime, ".wav")
        with tempfile.TemporaryDirectory(prefix="lumina_chatterbox_") as work:
            source_path = Path(work) / f"source{source_suffix}"
            reference_path = Path(work) / f"reference{reference_suffix}"
            source_path.write_bytes(source_audio)
            reference_path.write_bytes(reference_audio)
            try:
                client = self._client()
                result = client.predict(
                    handle_file(str(source_path)),
                    handle_file(str(reference_path)),
                    api_name=self.chatterbox_api_name,
                )
            except Exception as exc:
                raise ToneConversionError(
                    "chatterbox_request_failed",
                    "The free Chatterbox Space could not complete voice conversion.",
                ) from exc
            data = self._read_result_audio(result)

        return ToneConversionResult(
            audio=data,
            mime_type="audio/wav",
            metadata={
                "tone_converter": "chatterbox-vc",
                "engine": "chatterbox-vc",
                "personal_voice_mode": "voice-conversion-fallback",
                "transport": "gradio-client",
                "runtime": "huggingface-space",
                "space_id": self.chatterbox_space_id,
                "zero_monthly_cost": True,
            },
        )

    async def _convert_remote(
        self,
        source_audio: bytes,
        source_mime: str,
        reference_audio: bytes,
        reference_mime: str,
        output_format: str,
    ) -> ToneConversionResult:
        headers = {"Accept": "audio/*, application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        files = {
            "source_audio": ("source.mp3", source_audio, source_mime or "audio/mpeg"),
            "reference_audio": ("reference.wav", reference_audio, reference_mime or "audio/wav"),
        }
        form = {"output_format": str(output_format or "wav"), "engine": "openvoice-v2"}

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
                metadata={"tone_converter": self.name, "transport": "raw-audio", "runtime": "remote"},
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
            metadata={"tone_converter": self.name, "transport": "json-base64", "runtime": "remote"},
        )

    @staticmethod
    def _ensure_openvoice_source() -> Path:
        root = Path(os.environ.get("OPENVOICE_V2_CACHE_DIR", "/tmp/lumina-openvoice-v2"))
        source_root = root / "source"
        package_dir = source_root / "openvoice"
        if package_dir.is_dir():
            if str(source_root) not in sys.path:
                sys.path.insert(0, str(source_root))
            return source_root

        root.mkdir(parents=True, exist_ok=True)
        archive_url = "https://github.com/myshell-ai/OpenVoice/archive/refs/heads/main.zip"
        try:
            response = httpx.get(archive_url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()
        except Exception as exc:
            raise ToneConversionError("source_download_failed", "Could not download OpenVoice source.") from exc

        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            zf.extractall(root)
        extracted = root / "OpenVoice-main"
        if not (extracted / "openvoice").is_dir():
            raise ToneConversionError("source_invalid", "OpenVoice source archive is invalid.")
        if source_root.exists():
            import shutil
            shutil.rmtree(source_root, ignore_errors=True)
        extracted.rename(source_root)
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
        return source_root

    @staticmethod
    def _checkpoint_paths() -> tuple[str, str]:
        try:
            from huggingface_hub import hf_hub_download
            config_path = hf_hub_download(
                repo_id="myshell-ai/OpenVoiceV2",
                filename="converter/config.json",
            )
            checkpoint_path = hf_hub_download(
                repo_id="myshell-ai/OpenVoiceV2",
                filename="converter/checkpoint.pth",
            )
            return config_path, checkpoint_path
        except Exception as exc:
            raise ToneConversionError("checkpoint_download_failed", "Could not download OpenVoice V2 checkpoints.") from exc

    @classmethod
    def _local_model(cls):
        global _LOCAL_MODEL
        if _LOCAL_MODEL is not None:
            return _LOCAL_MODEL

        cls._ensure_openvoice_source()
        try:
            import torch
            from openvoice import utils
            from openvoice.mel_processing import spectrogram_torch
            from openvoice.models import SynthesizerTrn
        except Exception as exc:
            raise ToneConversionError("local_import_failed", "OpenVoice local runtime dependencies are unavailable.") from exc

        config_path, checkpoint_path = cls._checkpoint_paths()
        hps = utils.get_hparams_from_file(config_path)
        device = "cpu"
        model = SynthesizerTrn(
            len(getattr(hps, "symbols", [])),
            hps.data.filter_length // 2 + 1,
            n_speakers=hps.data.n_speakers,
            **hps.model,
        ).to(device)
        model.eval()
        checkpoint = torch.load(checkpoint_path, map_location=torch.device(device), weights_only=False)
        model.load_state_dict(checkpoint["model"], strict=False)
        _LOCAL_MODEL = (model, hps, device, spectrogram_torch)
        return _LOCAL_MODEL

    @classmethod
    def _convert_local_sync(
        cls,
        source_audio: bytes,
        source_mime: str,
        reference_audio: bytes,
        reference_mime: str,
    ) -> ToneConversionResult:
        try:
            import librosa
            import numpy as np
            import soundfile as sf
            import torch
        except Exception as exc:
            raise ToneConversionError("local_import_failed", "Audio runtime dependencies are unavailable.") from exc

        model, hps, device, spectrogram_torch = cls._local_model()

        def extract_se(path: str):
            audio_ref, _ = librosa.load(path, sr=hps.data.sampling_rate, mono=True)
            y = torch.FloatTensor(audio_ref).to(device).unsqueeze(0)
            spec = spectrogram_torch(
                y,
                hps.data.filter_length,
                hps.data.sampling_rate,
                hps.data.hop_length,
                hps.data.win_length,
                center=False,
            ).to(device)
            with torch.no_grad():
                return model.ref_enc(spec.transpose(1, 2)).unsqueeze(-1).detach()

        source_suffix = ".mp3" if "mpeg" in (source_mime or "") else ".wav"
        reference_suffix = ".m4a" if "m4a" in (reference_mime or "") or "mp4" in (reference_mime or "") else ".wav"
        with tempfile.TemporaryDirectory(prefix="lumina_openvoice_") as work:
            source_path = Path(work) / f"source{source_suffix}"
            reference_path = Path(work) / f"reference{reference_suffix}"
            output_path = Path(work) / "converted.wav"
            source_path.write_bytes(source_audio)
            reference_path.write_bytes(reference_audio)

            src_se = extract_se(str(source_path))
            tgt_se = extract_se(str(reference_path))

            audio, _ = librosa.load(str(source_path), sr=hps.data.sampling_rate, mono=True)
            y = torch.tensor(audio, dtype=torch.float32, device=device).unsqueeze(0)
            spec = spectrogram_torch(
                y,
                hps.data.filter_length,
                hps.data.sampling_rate,
                hps.data.hop_length,
                hps.data.win_length,
                center=False,
            ).to(device)
            spec_lengths = torch.LongTensor([spec.size(-1)]).to(device)
            with torch.no_grad():
                converted = model.voice_conversion(
                    spec,
                    spec_lengths,
                    sid_src=src_se,
                    sid_tgt=tgt_se,
                    tau=0.3,
                )[0][0, 0].detach().cpu().float().numpy()
            sf.write(str(output_path), np.asarray(converted, dtype=np.float32), hps.data.sampling_rate)
            data = output_path.read_bytes()

        if not data:
            raise ToneConversionError("empty_output", "Local OpenVoice V2 returned empty audio.")
        return ToneConversionResult(
            audio=data,
            mime_type="audio/wav",
            metadata={
                "tone_converter": cls.name,
                "transport": "in-process",
                "runtime": "local-cpu",
                "engine": "openvoice-v2",
            },
        )
