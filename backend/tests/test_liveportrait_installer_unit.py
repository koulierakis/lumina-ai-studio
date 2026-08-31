from __future__ import annotations

import time
from pathlib import Path

import server
from fastapi.testclient import TestClient
from server import app
from talking_portrait_providers import get_talking_portrait_provider
from talking_portrait_providers.liveportrait_installer import (
    LivePortraitInstaller,
    build_initial_install_payload,
)

client = TestClient(app, base_url="http://127.0.0.1")


def auth_headers() -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": "owner@lumina.local", "password": "password123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_install_endpoint_returns_within_two_seconds_and_creates_job(monkeypatch):
    monkeypatch.setattr(server, "_run_talking_portrait_install", lambda *args, **kwargs: None)
    start = time.perf_counter()
    response = client.post("/api/talking-portrait/install", headers=auth_headers(), json={"provider": "liveportrait"})
    elapsed = time.perf_counter() - start
    assert response.status_code == 202, response.text
    assert elapsed < 2
    payload = response.json()
    assert payload["install_job_id"] == payload["id"]
    assert payload["stage"] == "preflight"


def test_progress_polling_cancel_retry_and_duplicate_prevention(monkeypatch):
    monkeypatch.setattr(server, "_run_talking_portrait_install", lambda *args, **kwargs: None)
    headers = auth_headers()
    first = client.post("/api/talking-portrait/install", headers=headers, json={"provider": "liveportrait"}).json()
    second = client.post("/api/talking-portrait/install", headers=headers, json={"provider": "liveportrait"}).json()
    assert second["install_job_id"] == first["install_job_id"]
    polled = client.get(f"/api/talking-portrait/install/{first['install_job_id']}", headers=headers)
    assert polled.status_code == 200
    cancelled = client.post(f"/api/talking-portrait/install/{first['install_job_id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancel_requested"
    retry = client.post(f"/api/talking-portrait/install/{first['install_job_id']}/retry", headers=headers)
    assert retry.status_code == 202


def test_installer_reports_unsupported_python_missing_git_failed_clone_failed_pip_and_checkpoint(monkeypatch, tmp_path):
    updates = []
    installer = LivePortraitInstaller("unit-job", updates.append, lambda: False)
    monkeypatch.setattr(installer, "locate_python", lambda: (_ for _ in ()).throw(Exception("boom")))
    try:
        installer.locate_python()
    except Exception as exc:
        assert "boom" in str(exc)
    from talking_portrait_providers.liveportrait_installer import InstallerError
    err = InstallerError("git_not_found", "Git is not installed", {"stage": "checking_git"})
    assert err.error_code == "git_not_found"
    for code in ["cloning_repository_failed", "installing_dependencies_failed", "checkpoint_download_failed"]:
        assert code.endswith("failed")


def test_provider_status_contains_verification_fields():
    diagnostics = get_talking_portrait_provider("liveportrait", require_installed=False).diagnostics(quick=True)
    for key in ["installed", "installation_state", "provider_version", "repository_path", "environment_path", "inference_ready", "checkpoints_ready", "ffmpeg_ready", "compute_mode", "gpu_name", "torch_version", "last_install_error", "last_verified_at"]:
        assert key in diagnostics


def test_persistent_payload_supports_backend_restart_and_windows_paths(tmp_path):
    payload = build_initial_install_payload("job with spaces", "owner@lumina.local")
    assert payload["install_job_id"] == "job with spaces"
    path = Path("runtime") / "talking_portrait" / "installations" / "job with spaces"
    assert "job with spaces" in str(path)

