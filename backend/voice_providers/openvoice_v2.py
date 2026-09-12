"""OpenVoice V2 tone-color conversion adapter.

Supports two modes:
1) Remote HTTP endpoint via OPENVOICE_V2_ENDPOINT.
2) Local CPU runtime inside the Render service via OPENVOICE_V2_LOCAL=1.

Local mode downloads the official OpenVoice source archive and official V2
converter checkpoints on first use, then performs tone conversion in-process.
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


_LOCAL_MODEL = None
_LOCAL_MODEL_LOCK = asyncio.Lock()


class OpenVoiceV2ToneConverter:
    name = "openvoice-v2"

    def __init__(
        self,
        endpoint: str = "",
        api_key: str = "",
        timeout_seconds: float = 90.0,
        required: bool = False,
        local_enabled: bool = False,
    ) -> None:
        self.endpoint = endpoint.strip()
        self.api_key = api_key.strip()
        self.timeout_seconds = max(5.0, min(float(timeout_seconds), 300.0))
        self.required = bool(required)
        self.local_enabled = bool(local_enabled)

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
            local_enabled=_truthy(os.environ.get("OPENVOICE_V2_LOCAL", "0")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.endpoint) or self.local_enabled

    async def convert(
        self,
        source_audio: bytes,
        source_mime: str,
        reference_audio: bytes,
        reference_mime: str,
        output_format: str = "wav",
    ) -> ToneConversionResult:
        if not self.configured:
            raise ToneConversionError("not_configured", "OpenVoice V2 is not configured.")
        if not source_audio:
            raise ToneConversionError("empty_source", "Base speech audio is empty.")
        if not reference_audio:
            raise ToneConversionError("empty_reference", "Reference voice sample is empty.")

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
                raise ToneConversionError("local_runtime_error", f"Local OpenVoice V2 failed: {exc}") from exc

        return await self._convert_remote(
            source_audio,
            source_mime,
            reference_audio,
            reference_mime,
            output_format,
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
