from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from huggingface_hub import hf_hub_download

app = FastAPI(title="LUMINA OpenVoice V2 Worker")

_model = None
_model_lock = Lock()


def _check_api_key(authorization: str | None) -> None:
    expected = os.environ.get("OPENVOICE_WORKER_API_KEY", "").strip()
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _checkpoint_paths() -> tuple[str, str]:
    cache_dir = Path(os.environ.get("OPENVOICE_CACHE_DIR", "/tmp/openvoice-v2"))
    converter_dir = cache_dir / "converter"
    converter_dir.mkdir(parents=True, exist_ok=True)

    config_path = converter_dir / "config.json"
    checkpoint_path = converter_dir / "checkpoint.pth"

    if not config_path.exists():
        src = hf_hub_download(
            repo_id="myshell-ai/OpenVoiceV2",
            filename="converter/config.json",
        )
        shutil.copyfile(src, config_path)

    if not checkpoint_path.exists():
        src = hf_hub_download(
            repo_id="myshell-ai/OpenVoiceV2",
            filename="converter/checkpoint.pth",
        )
        shutil.copyfile(src, checkpoint_path)

    return str(config_path), str(checkpoint_path)


def _create_converter(config_path: str, device: str):
    """Create OpenVoice's converter without requiring wavmark.

    Current upstream OpenVoice accepts ``enable_watermark`` in
    ``ToneColorConverter.__init__`` but forwards the same keyword to
    ``OpenVoiceBaseClass.__init__``, which does not accept it.  Prefer the
    public constructor, then fall back to initializing the base class directly
    when that known upstream incompatibility is encountered.
    """
    from openvoice.api import OpenVoiceBaseClass, ToneColorConverter

    try:
        return ToneColorConverter(
            config_path,
            device=device,
            enable_watermark=False,
        )
    except TypeError as exc:
        if "enable_watermark" not in str(exc):
            raise

        converter = ToneColorConverter.__new__(ToneColorConverter)
        OpenVoiceBaseClass.__init__(converter, config_path, device=device)
        converter.watermark_model = None
        converter.version = getattr(converter.hps, "_version_", "v1")
        return converter


def _get_converter():
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        import torch

        config_path, checkpoint_path = _checkpoint_paths()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        converter = _create_converter(config_path, device)
        converter.load_ckpt(checkpoint_path)
        _model = converter
        return _model


def _suffix_for_mime(mime: str | None, fallback: str) -> str:
    value = (mime or "").lower()
    if "mpeg" in value or "mp3" in value:
        return ".mp3"
    if "wav" in value:
        return ".wav"
    if "aac" in value:
        return ".aac"
    if "mp4" in value or "m4a" in value:
        return ".m4a"
    return fallback


@app.get("/")
def root() -> dict:
    return {"service": "lumina-openvoice-v2", "status": "ok"}


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "engine": "openvoice-v2",
        "model_loaded": _model is not None,
    }


@app.post("/convert")
async def convert(
    source_audio: UploadFile = File(...),
    reference_audio: UploadFile = File(...),
    output_format: str = Form("wav"),
    engine: str = Form("openvoice-v2"),
    authorization: str | None = Header(default=None),
) -> Response:
    _check_api_key(authorization)

    if engine != "openvoice-v2":
        raise HTTPException(status_code=400, detail="Unsupported engine")
    if output_format.lower() != "wav":
        raise HTTPException(status_code=400, detail="Only WAV output is supported")

    source_data = await source_audio.read()
    reference_data = await reference_audio.read()
    if not source_data:
        raise HTTPException(status_code=400, detail="source_audio is empty")
    if not reference_data:
        raise HTTPException(status_code=400, detail="reference_audio is empty")

    converter = _get_converter()
    workdir = Path(tempfile.mkdtemp(prefix="lumina-openvoice-"))
    try:
        source_path = workdir / f"source{_suffix_for_mime(source_audio.content_type, '.mp3')}"
        reference_path = workdir / f"reference{_suffix_for_mime(reference_audio.content_type, '.wav')}"
        output_path = workdir / "converted.wav"

        source_path.write_bytes(source_data)
        reference_path.write_bytes(reference_data)

        # OpenVoice can extract speaker embeddings directly from audio files.
        # This deliberately avoids se_extractor/VAD dependencies so the worker
        # stays small and suitable for a dedicated CPU service.
        source_se = converter.extract_se([str(source_path)])
        target_se = converter.extract_se([str(reference_path)])
        converter.convert(
            audio_src_path=str(source_path),
            src_se=source_se,
            tgt_se=target_se,
            output_path=str(output_path),
            message="@LUMINA",
        )

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("OpenVoice produced no output audio")
        return Response(content=output_path.read_bytes(), media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"OpenVoice conversion failed: {exc}") from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
