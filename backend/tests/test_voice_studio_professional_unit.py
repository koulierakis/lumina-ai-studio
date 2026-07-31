from models import PersonalVoiceModel, VoiceExportRequest, VoiceJob, VoiceProject, VoiceRecordingSession


def test_personal_voice_model_contains_required_profiles():
    model = PersonalVoiceModel(owner_email="owner@example.com")
    payload = model.model_dump()
    assert payload["profile"]["voice_identity"] == {}
    for key in ("speaking_profile", "singing_profile", "accent_profile", "pronunciation_profile", "breathing_profile", "vocal_range"):
        assert key in payload["profile"]


def test_voice_job_supports_professional_export_and_identity_fields():
    job = VoiceJob(owner_email="owner@example.com", mode="singing-conversion", style="cinematic", output_format="flac", sample_rate=48000, bit_depth=24, loudness_lufs=-18, personal_model_id="pvm")
    assert job.mode == "singing-conversion"
    assert job.personal_model_id == "pvm"
    assert job.output_format == "flac"
    assert job.sample_rate == 48000


def test_voice_project_versions_enable_non_destructive_restore():
    project = VoiceProject(owner_email="owner@example.com", state={"timeline": [], "non_destructive": True})
    assert project.state["non_destructive"] is True
    assert project.versions == []


def test_recording_session_tracks_studio_capture_metadata():
    recording = VoiceRecordingSession(owner_email="owner@example.com", microphone_label="USB Studio Mic", quality_preset="broadcast", waveform=[0.1, 0.5, 0.2], monitoring_enabled=True)
    assert recording.microphone_label == "USB Studio Mic"
    assert recording.monitoring_enabled is True
    assert len(recording.waveform) == 3


def test_voice_export_request_supports_required_formats_and_mastering():
    export = VoiceExportRequest(format="aac", sample_rate=48000, bit_depth=24, bitrate="256k", loudness_lufs=-14, metadata={"artist": "Lumina"})
    assert export.format == "aac"
    assert export.metadata["artist"] == "Lumina"
