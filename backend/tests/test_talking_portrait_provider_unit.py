import asyncio
import io
import json
import tempfile

import pytest
from PIL import Image

import server
from talking_portrait_providers import auto_detect_talking_portrait_provider, get_talking_portrait_provider, talking_portrait_catalog
from talking_portrait_providers.base import GeneratedTalkingPortrait, TalkingPortraitCancelledError, TalkingPortraitInput, TalkingPortraitProviderError
from talking_portrait_providers.liveportrait_provider import LivePortraitProvider, _LocalLipSyncEngine, _raise_if_cancelled


class _FakeTalkingPortraitJobs:
    def __init__(self, job):
        self.job = dict(job)

    async def find_one(self, query, projection=None):
        if query.get("id") == self.job.get("id") and query.get("owner_email") == self.job.get("owner_email"):
            return dict(self.job)
        return None

    async def update_one(self, query, update):
        if query.get("id") != self.job.get("id"):
            return None
        for key, value in update.get("$set", {}).items():
            target = self.job
            parts = key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        return None


class _FakeMediaCollection:
    def __init__(self, portrait_id="portrait-media", audio_id="audio-media"):
        self.sources = {
            portrait_id: {"id": portrait_id, "owner_email": "owner@lumina.local", "filename": "portrait.png", "mime_type": "image/png"},
            audio_id: {"id": audio_id, "owner_email": "owner@lumina.local", "filename": "audio.wav", "mime_type": "audio/wav"},
        }
        self.inserted = []

    async def find_one(self, query, projection=None):
        item = self.sources.get(query.get("id"))
        if item and item.get("owner_email") == query.get("owner_email"):
            return dict(item)
        return None

    async def insert_one(self, payload):
        self.inserted.append(dict(payload))
        return None


class _FakeProvider:
    def __init__(self, result=None, exc=None, on_generate=None):
        self.result = result or GeneratedTalkingPortrait(b"video-bytes", "video/mp4", duration_seconds=1.0, metadata={"fake": True})
        self.exc = exc
        self.on_generate = on_generate

    def is_installed(self):
        return True

    async def generate(self, spec, progress=None):
        if progress:
            await progress(45, "fake provider running")
        if self.on_generate:
            self.on_generate()
        if self.exc:
            raise self.exc
        return self.result


class _FakeReadinessProvider:
    def __init__(self, diagnostics):
        self._diagnostics = diagnostics

    def diagnostics(self, quick=False):
        return dict(self._diagnostics)

    def generation_readiness(self, diagnostics=None):
        return LivePortraitProvider.generation_readiness(diagnostics or self.diagnostics(quick=True))


class _FakeUpload:
    def __init__(self, content_type, data=b"data", fail_on_read=False):
        self.content_type = content_type
        self._data = data
        self.fail_on_read = fail_on_read

    async def read(self):
        if self.fail_on_read:
            raise AssertionError("upload should not be read before readiness rejection")
        return self._data


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args):
        self.tasks.append((func, args))


def _tiny_png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _runner_job(status="queued"):
    return {
        "id": "job-1",
        "owner_email": "owner@lumina.local",
        "status": status,
        "progress": 0,
        "provider": "liveportrait",
        "portrait_media_id": "portrait-media",
        "audio_media_id": "audio-media",
        "title": "Runner job",
    }


def test_talking_portrait_catalog_registers_liveportrait_and_future_engines():
    catalog = {item["name"]: item for item in talking_portrait_catalog()}
    assert "liveportrait" in catalog
    assert {"musetalk", "echomimic", "hallo"}.issubset(catalog)
    assert catalog["liveportrait"]["capabilities"]["output_formats"] == ["video/mp4"]
    assert auto_detect_talking_portrait_provider() == "liveportrait"


def test_liveportrait_provider_can_be_inspected_without_installation():
    provider = get_talking_portrait_provider("liveportrait", require_installed=False)
    diagnostics = provider.diagnostics()
    assert diagnostics["install_root"]
    assert diagnostics["cpu_fallback"] is True


def test_liveportrait_generation_requires_installation(tmp_path):
    provider = get_talking_portrait_provider("liveportrait", require_installed=False)
    if provider.is_installed():
        return
    spec = TalkingPortraitInput(
        portrait_path=tmp_path / "portrait.png",
        portrait_mime="image/png",
        audio_path=tmp_path / "audio.wav",
        audio_mime="audio/wav",
        output_path=tmp_path / "out.mp4",
    )
    try:
        asyncio.run(provider.generate(spec))
    except TalkingPortraitProviderError as exc:
        assert "Install LivePortrait" in exc.safe_message


def test_talking_portrait_input_cancellation_callback_is_backward_compatible(tmp_path):
    legacy = TalkingPortraitInput(
        portrait_path=tmp_path / "portrait.png",
        portrait_mime="image/png",
        audio_path=tmp_path / "audio.wav",
        audio_mime="audio/wav",
        output_path=tmp_path / "out.mp4",
    )
    cancellable = TalkingPortraitInput(
        portrait_path=tmp_path / "portrait.png",
        portrait_mime="image/png",
        audio_path=tmp_path / "audio.wav",
        audio_mime="audio/wav",
        output_path=tmp_path / "out.mp4",
        should_cancel=lambda: True,
    )
    assert legacy.should_cancel is None
    assert cancellable.should_cancel() is True


def test_cancellation_checkpoint_raises_controlled_error():
    with pytest.raises(TalkingPortraitCancelledError):
        _raise_if_cancelled(lambda: True, "liveportrait")


def test_cancellation_checkpoint_terminates_active_process(monkeypatch):
    terminated = []
    monkeypatch.setattr("talking_portrait_providers.liveportrait_provider._terminate_process_tree", lambda pid: terminated.append(pid))
    with pytest.raises(TalkingPortraitCancelledError):
        _raise_if_cancelled(lambda: True, "liveportrait", pid=1234)
    assert terminated == [1234]


def test_wav2lip_longform_cancellation_between_chunks(monkeypatch, tmp_path):
    calls = {"count": 0}
    portrait = tmp_path / "portrait.png"
    audio = tmp_path / "audio.wav"
    output = tmp_path / "out.mp4"
    portrait.write_bytes(b"portrait")
    audio.write_bytes(b"audio")
    monkeypatch.setattr(_LocalLipSyncEngine, "available_engine", classmethod(lambda cls: "wav2lip"))
    monkeypatch.setattr(_LocalLipSyncEngine, "_file_sha256", classmethod(lambda cls, path: path.stem))
    monkeypatch.setattr(_LocalLipSyncEngine, "_extract_audio_chunk", classmethod(lambda cls, *args, **kwargs: None))
    monkeypatch.setattr(_LocalLipSyncEngine, "_trim_video_chunk", classmethod(lambda cls, *args, **kwargs: None))
    monkeypatch.setattr(_LocalLipSyncEngine, "_probe_duration", classmethod(lambda cls, *args, **kwargs: 1.0))

    async def fake_run(cls, *args, **kwargs):
        calls["count"] += 1
        return {"engine": "wav2lip"}

    monkeypatch.setattr(_LocalLipSyncEngine, "run", classmethod(fake_run))

    def should_cancel():
        return calls["count"] >= 1

    with pytest.raises(TalkingPortraitCancelledError):
        asyncio.run(_LocalLipSyncEngine.run_wav2lip_longform(portrait, audio, output, ffmpeg="ffmpeg", audio_duration=2.0, should_cancel=should_cancel))
    assert calls["count"] == 1


def test_non_cancelled_checkpoint_allows_normal_flow(monkeypatch, tmp_path):
    portrait = tmp_path / "portrait.png"
    audio = tmp_path / "audio.wav"
    output = tmp_path / "out.mp4"
    portrait.write_bytes(b"portrait")
    audio.write_bytes(b"audio")
    output.write_bytes(b"0" * (65 * 1024))
    monkeypatch.setattr(LivePortraitProvider, "is_installed", lambda self: True)
    monkeypatch.setattr(LivePortraitProvider, "_find_ffmpeg", classmethod(lambda cls: "ffmpeg"))
    monkeypatch.setattr(LivePortraitProvider, "diagnostics", classmethod(lambda cls, quick=False: {"checkpoints_ready": True, "checkpoint_inventory": [], "gpu": False, "compute_mode": "cpu"}))
    monkeypatch.setattr(LivePortraitProvider, "_media_duration_seconds", classmethod(lambda cls, path, ffmpeg: 1.0))
    monkeypatch.setattr(LivePortraitProvider, "_validate_final_output", classmethod(lambda cls, *args, **kwargs: None))
    monkeypatch.setattr(_LocalLipSyncEngine, "available_engine", classmethod(lambda cls: "wav2lip"))

    async def fake_longform(cls, *args, **kwargs):
        assert kwargs["should_cancel"]() is False
        return {"engine": "wav2lip"}

    monkeypatch.setattr(_LocalLipSyncEngine, "run_wav2lip_longform", classmethod(fake_longform))
    spec = TalkingPortraitInput(portrait_path=portrait, portrait_mime="image/png", audio_path=audio, audio_mime="audio/wav", output_path=output, should_cancel=lambda: False)
    result = asyncio.run(LivePortraitProvider().generate(spec))
    assert result.mime_type == "video/mp4"
    assert result.metadata["lip_sync_engine"] == "wav2lip"


def test_generation_readiness_requires_inference_and_lip_sync():
    ready = LivePortraitProvider.generation_readiness({"inference_ready": True, "lip_sync_engine": "wav2lip"})
    missing_lip_sync = LivePortraitProvider.generation_readiness({"inference_ready": True, "lip_sync_engine": None})
    missing_inference = LivePortraitProvider.generation_readiness({"inference_ready": False, "lip_sync_engine": "wav2lip"})

    assert ready["operational"] is True
    assert ready["lip_sync_engine"] == "wav2lip"
    assert missing_lip_sync["operational"] is False
    assert "lip-sync engine is required" in missing_lip_sync["reason"]
    assert missing_inference["operational"] is False
    assert "inference environment is not ready" in missing_inference["reason"]


def test_provider_listing_uses_generation_readiness(monkeypatch):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": None}
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server, "available_talking_portrait_providers", lambda: [])
    monkeypatch.setattr(server, "talking_portrait_catalog", lambda: [])
    response = asyncio.run(server.list_talking_portrait_providers("owner@lumina.local"))

    assert response["active"] is None
    assert response["operational"] is False
    assert "lip-sync engine is required" in response["readiness_reason"]


def test_diagnostics_reports_operational_when_inference_and_lip_sync_ready(monkeypatch):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": "wav2lip"}
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    response = asyncio.run(server.talking_portrait_diagnostics("owner@lumina.local"))

    assert response["provider_operational"] is True
    assert response["operational"] is True
    assert response["readiness"]["operational"] is True
    assert response["readiness"]["lip_sync_engine"] == "wav2lip"


def test_diagnostics_reports_not_operational_without_lip_sync(monkeypatch):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": None}
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    response = asyncio.run(server.talking_portrait_diagnostics("owner@lumina.local"))

    assert response["provider_operational"] is False
    assert response["operational"] is False
    assert response["readiness"]["operational"] is False
    assert "MuseTalk or Wav2Lip" in response["readiness_reason"]


def test_diagnostics_reports_not_operational_without_inference(monkeypatch):
    diagnostics = {"inference_ready": False, "installed": True, "healthy": False, "lip_sync_engine": "wav2lip"}
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    response = asyncio.run(server.talking_portrait_diagnostics("owner@lumina.local"))

    assert response["provider_operational"] is False
    assert response["operational"] is False
    assert response["readiness"]["operational"] is False
    assert "inference environment is not ready" in response["readiness_reason"]


@pytest.mark.parametrize("diagnostics", [
    {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": "wav2lip"},
    {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": None},
    {"inference_ready": False, "installed": True, "healthy": False, "lip_sync_engine": "wav2lip"},
])
def test_diagnostics_and_provider_listing_readiness_are_consistent(monkeypatch, diagnostics):
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server, "available_talking_portrait_providers", lambda: [])
    monkeypatch.setattr(server, "talking_portrait_catalog", lambda: [])

    diagnostics_response = asyncio.run(server.talking_portrait_diagnostics("owner@lumina.local"))
    providers_response = asyncio.run(server.list_talking_portrait_providers("owner@lumina.local"))

    assert diagnostics_response["provider_operational"] == providers_response["operational"]
    assert diagnostics_response["readiness"]["operational"] == providers_response["readiness"]["operational"]
    assert diagnostics_response["readiness"]["lip_sync_engine"] == providers_response["readiness"]["lip_sync_engine"]
    assert diagnostics_response["readiness_reason"] == providers_response["readiness_reason"]


def test_generate_rejects_missing_lip_sync_before_media_or_job_creation(monkeypatch):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": None}
    media = _FakeMediaCollection()
    jobs = _FakeTalkingPortraitJobs(_runner_job())
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server, "media_coll", media)
    monkeypatch.setattr(server, "talking_portrait_jobs_coll", jobs)
    monkeypatch.setattr(server, "save_bytes", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("save_bytes should not be called")))

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(server.create_talking_portrait_job(_FakeBackgroundTasks(), photo=_FakeUpload("image/png", fail_on_read=True), audio=_FakeUpload("audio/wav", fail_on_read=True), provider=None, title="Talking portrait", tags="", owner="owner@lumina.local"))

    assert exc_info.value.status_code == 409
    assert "lip-sync engine is required" in exc_info.value.detail["message"]
    assert media.inserted == []
    assert jobs.job["status"] == "queued"


def test_generate_rejects_corrupt_image_before_storage(monkeypatch):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": "wav2lip"}
    media = _FakeMediaCollection()
    jobs = _FakeTalkingPortraitJobs(_runner_job())
    background = _FakeBackgroundTasks()
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server, "media_coll", media)
    monkeypatch.setattr(server, "talking_portrait_jobs_coll", jobs)
    monkeypatch.setattr(server, "save_bytes", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("save_bytes should not be called")))

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(server.create_talking_portrait_job(background, photo=_FakeUpload("image/png", b"not an image"), audio=_FakeUpload("audio/wav", b"audio"), provider=None, title="Talking portrait", tags="", owner="owner@lumina.local"))

    assert exc_info.value.status_code == 400
    assert "Reference photo" in exc_info.value.detail
    assert media.inserted == []
    assert jobs.job["status"] == "queued"
    assert background.tasks == []


def test_generate_accepts_valid_small_image_before_audio_validation(monkeypatch):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": "wav2lip"}
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server, "_validate_talking_portrait_audio_upload", lambda audio_bytes, audio_mime: (_ for _ in ()).throw(server.HTTPException(400, "Audio file could not be probed or decoded as valid audio.")))

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(server.create_talking_portrait_job(_FakeBackgroundTasks(), photo=_FakeUpload("image/png", _tiny_png_bytes()), audio=_FakeUpload("audio/wav", b"invalid audio"), provider=None, title="Talking portrait", tags="", owner="owner@lumina.local"))

    assert exc_info.value.status_code == 400
    assert "Audio file" in exc_info.value.detail


@pytest.mark.parametrize("probe_payload", [
    {"streams": [], "format": {"duration": "1.0"}},
    {"streams": [{"codec_type": "video"}], "format": {"duration": "1.0"}},
])
def test_generate_rejects_audio_without_audio_stream_before_storage(monkeypatch, probe_payload):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": "wav2lip"}
    media = _FakeMediaCollection()
    jobs = _FakeTalkingPortraitJobs(_runner_job())
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server.LivePortraitProvider, "_find_ffmpeg", classmethod(lambda cls: "C:/ffmpeg/bin/ffmpeg.exe"))
    monkeypatch.setattr(server.Path, "exists", lambda self: True)
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": json.dumps(probe_payload), "stderr": ""})())
    monkeypatch.setattr(server, "media_coll", media)
    monkeypatch.setattr(server, "talking_portrait_jobs_coll", jobs)

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(server.create_talking_portrait_job(_FakeBackgroundTasks(), photo=_FakeUpload("image/png", _tiny_png_bytes()), audio=_FakeUpload("audio/wav", b"audio"), provider=None, title="Talking portrait", tags="", owner="owner@lumina.local"))

    assert exc_info.value.status_code == 400
    assert "audio stream" in exc_info.value.detail
    assert media.inserted == []
    assert jobs.job["status"] == "queued"


@pytest.mark.parametrize("duration", ["0", "-1", "nan", ""])
def test_generate_rejects_invalid_audio_duration_before_storage(monkeypatch, duration):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": "wav2lip"}
    media = _FakeMediaCollection()
    jobs = _FakeTalkingPortraitJobs(_runner_job())
    probe_payload = {"streams": [{"codec_type": "audio"}], "format": {"duration": duration}}
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server.LivePortraitProvider, "_find_ffmpeg", classmethod(lambda cls: "C:/ffmpeg/bin/ffmpeg.exe"))
    monkeypatch.setattr(server.Path, "exists", lambda self: True)
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": json.dumps(probe_payload), "stderr": ""})())
    monkeypatch.setattr(server, "media_coll", media)
    monkeypatch.setattr(server, "talking_portrait_jobs_coll", jobs)

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(server.create_talking_portrait_job(_FakeBackgroundTasks(), photo=_FakeUpload("image/png", _tiny_png_bytes()), audio=_FakeUpload("audio/wav", b"audio"), provider=None, title="Talking portrait", tags="", owner="owner@lumina.local"))

    assert exc_info.value.status_code == 400
    assert "positive finite duration" in exc_info.value.detail or "duration could not be validated" in exc_info.value.detail
    assert media.inserted == []
    assert jobs.job["status"] == "queued"


def test_generate_rejects_unprobeable_audio_and_cleans_temp_dir(monkeypatch, tmp_path):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": "wav2lip"}
    original_temporary_directory = tempfile.TemporaryDirectory
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server.LivePortraitProvider, "_find_ffmpeg", classmethod(lambda cls: "C:/ffmpeg/bin/ffmpeg.exe"))
    monkeypatch.setattr(server.Path, "exists", lambda self: True)
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 1, "stdout": "", "stderr": "bad audio"})())
    monkeypatch.setattr(server.tempfile, "TemporaryDirectory", lambda prefix: original_temporary_directory(prefix=prefix, dir=tmp_path))

    with pytest.raises(server.HTTPException) as exc_info:
        asyncio.run(server.create_talking_portrait_job(_FakeBackgroundTasks(), photo=_FakeUpload("image/png", _tiny_png_bytes()), audio=_FakeUpload("audio/wav", b"bad audio"), provider=None, title="Talking portrait", tags="", owner="owner@lumina.local"))

    assert exc_info.value.status_code == 400
    assert "Audio file" in exc_info.value.detail
    assert not any(tmp_path.iterdir())


def test_generate_ready_provider_continues_existing_queue_flow(monkeypatch):
    diagnostics = {"inference_ready": True, "installed": True, "healthy": True, "lip_sync_engine": "wav2lip"}
    media = _FakeMediaCollection()
    inserted_jobs = []
    background = _FakeBackgroundTasks()

    class Jobs:
        async def insert_one(self, payload):
            inserted_jobs.append(dict(payload))

    saved = []
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeReadinessProvider(diagnostics))
    monkeypatch.setattr(server, "media_coll", media)
    monkeypatch.setattr(server, "talking_portrait_jobs_coll", Jobs())
    monkeypatch.setattr(server, "_validate_talking_portrait_audio_upload", lambda audio_bytes, audio_mime: None)
    monkeypatch.setattr(server, "save_bytes", lambda data, mime, kind: (saved.append((data, mime, kind)) or (f"{kind}-{len(saved)}.bin", None, len(data))))

    job = asyncio.run(server.create_talking_portrait_job(background, photo=_FakeUpload("image/png", _tiny_png_bytes()), audio=_FakeUpload("audio/wav", b"audio"), identity_lock=True, natural_blinking=True, head_motion=0.35, expression_intensity=0.55, fps=25, resolution="512", seed=None, title="Talking portrait", tags="", provider=None, owner="owner@lumina.local"))

    assert job.status == "queued"
    assert len(saved) == 2
    assert len(media.inserted) == 2
    assert len(inserted_jobs) == 1
    assert len(background.tasks) == 1


def test_runner_cancelled_after_provider_output_does_not_store_result(monkeypatch):
    jobs = _FakeTalkingPortraitJobs(_runner_job())
    media = _FakeMediaCollection()

    def cancel_after_output(data, mime_type, kind):
        jobs.job.update({"status": "cancelled", "cancelled_at": "now"})
        return "generated.mp4", None, len(data)

    monkeypatch.setattr(server, "talking_portrait_jobs_coll", jobs)
    monkeypatch.setattr(server, "media_coll", media)
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeProvider())
    monkeypatch.setattr(server, "read_bytes", lambda filename, kind: b"source-bytes")
    monkeypatch.setattr(server, "save_bytes", cancel_after_output)

    asyncio.run(server._run_talking_portrait_job("job-1", "owner@lumina.local"))

    assert media.inserted == []
    assert jobs.job["status"] == "cancelled"
    assert jobs.job.get("output_media_id") is None
    assert jobs.job.get("error") is None
    assert jobs.job.get("metadata", {}).get("provider_output") is None


def test_runner_provider_exception_marks_failed_without_result(monkeypatch):
    jobs = _FakeTalkingPortraitJobs(_runner_job())
    media = _FakeMediaCollection()
    provider_error = TalkingPortraitProviderError("liveportrait", "provider exploded", "Provider failed safely.", stage="fake_stage")

    monkeypatch.setattr(server, "talking_portrait_jobs_coll", jobs)
    monkeypatch.setattr(server, "media_coll", media)
    monkeypatch.setattr(server, "get_talking_portrait_provider", lambda *args, **kwargs: _FakeProvider(exc=provider_error))
    monkeypatch.setattr(server, "read_bytes", lambda filename, kind: b"source-bytes")
    monkeypatch.setattr(server, "save_bytes", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("save_bytes should not be called")))

    asyncio.run(server._run_talking_portrait_job("job-1", "owner@lumina.local"))

    assert media.inserted == []
    assert jobs.job["status"] == "failed"
    assert jobs.job["error"] == "Provider failed safely."
    assert jobs.job.get("cancelled_at") is None
    assert jobs.job.get("output_media_id") is None
    assert jobs.job["metadata"]["error_details"]["stage"] == "fake_stage"
