from __future__ import annotations

import asyncio
import io
from pathlib import Path

import openvoice_service
from starlette.datastructures import Headers, UploadFile


def test_checkpoint_cache_is_initialized_with_downloaded_files(monkeypatch, tmp_path: Path):
    sources = []
    for name in ("config.json", "checkpoint.pth"):
        source = tmp_path / name
        source.write_bytes(name.encode())
        sources.append(source)

    monkeypatch.setenv("OPENVOICE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(openvoice_service, "hf_hub_download", lambda **_: str(sources.pop(0)))

    config_path, checkpoint_path = openvoice_service._checkpoint_paths()

    assert Path(config_path).read_bytes() == b"config.json"
    assert Path(checkpoint_path).read_bytes() == b"checkpoint.pth"


def test_convert_restricts_request_workdir_and_returns_audio(monkeypatch):
    workdirs = []

    class FakeConverter:
        def extract_se(self, paths):
            return paths[0]

        def convert(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(b"converted")

    monkeypatch.setattr(openvoice_service, "_get_converter", lambda: FakeConverter())
    original_mkdtemp = openvoice_service.tempfile.mkdtemp

    def capture_mkdtemp(**kwargs):
        path = original_mkdtemp(**kwargs)
        workdirs.append(Path(path))
        return path

    monkeypatch.setattr(openvoice_service.tempfile, "mkdtemp", capture_mkdtemp)
    source = UploadFile(io.BytesIO(b"source"), filename="source.mp3", headers=Headers({"content-type": "audio/mpeg"}))
    reference = UploadFile(io.BytesIO(b"reference"), filename="reference.wav", headers=Headers({"content-type": "audio/wav"}))

    response = asyncio.run(openvoice_service.convert(source, reference, output_format="wav", engine="openvoice-v2"))

    assert response.body == b"converted"
    assert workdirs
