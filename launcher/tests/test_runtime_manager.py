"""Unit tests for LUMINA runtime manager (no live services required)."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

LAUNCHER_ROOT = Path(__file__).resolve().parents[1]
if str(LAUNCHER_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_ROOT))

from lumina import config as cfg_mod  # noqa: E402
from lumina import process_manager as pm  # noqa: E402
from lumina import readiness  # noqa: E402
from lumina import services as services_mod  # noqa: E402
from lumina import state as state_mod  # noqa: E402
from lumina.config import ConfigError, load_config, save_config, validate_config  # noqa: E402
from lumina.errors import AlreadyRunningError, LauncherError  # noqa: E402
from lumina.services import is_lumina_running, start_all  # noqa: E402


@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend" / "server.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "launcher").mkdir()
    (tmp_path / "launcher" / "lumina_launcher.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "find_repo_root", lambda start=None: tmp_path)
    monkeypatch.setattr(state_mod, "find_repo_root", lambda start=None: tmp_path)
    return tmp_path


def test_validate_config_defaults():
    data = validate_config({})
    assert data["backend_port"] == 8000
    assert data["preferred_ollama_model"] == "qwen2.5-coder:7b"


def test_invalid_config_falls_back(fake_repo: Path):
    path = fake_repo / ".lumina-runtime" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    loaded = load_config(fake_repo)
    assert loaded["frontend_port"] == 3000
    assert path.exists()


def test_reject_invalid_port():
    with pytest.raises(ConfigError):
        validate_config({"backend_port": 999999})


def test_save_and_load_config(fake_repo: Path):
    saved = save_config({"startup_timeout_seconds": 120, "logging_level": "DEBUG"}, fake_repo)
    assert saved["startup_timeout_seconds"] == 120
    assert load_config(fake_repo)["logging_level"] == "DEBUG"


def test_state_roundtrip_and_stale_cleanup(fake_repo: Path, monkeypatch: pytest.MonkeyPatch):
    state = state_mod.load_state(fake_repo)
    state["services"]["backend"] = {
        "pid": 999999,
        "pgid": None,
        "command": ["uvicorn", "server:app"],
        "started_at": 1,
    }
    state_mod.save_state(state, fake_repo)
    monkeypatch.setattr(pm, "pid_exists", lambda pid: False)
    cleaned = pm.cleanup_stale_pids(fake_repo)
    assert "backend" in cleaned
    assert state_mod.load_state(fake_repo)["services"]["backend"]["pid"] is None


def test_stop_refuses_unowned_pid(fake_repo: Path, monkeypatch: pytest.MonkeyPatch):
    state = state_mod.load_state(fake_repo)
    state["services"]["backend"] = {
        "pid": 12345,
        "pgid": None,
        "command": ["python"],
        "started_at": 1,
    }
    state_mod.save_state(state, fake_repo)
    monkeypatch.setattr(pm, "pid_exists", lambda pid: True)
    monkeypatch.setattr(pm, "owns_process", lambda *a, **k: False)
    result = pm.stop_owned_service("backend", fake_repo)
    assert result["skipped"] is True


def test_duplicate_start_protection(fake_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("lumina.services.is_lumina_running", lambda repo_root=None: True)
    with pytest.raises(AlreadyRunningError):
        start_all(fake_repo)


def test_readiness_helpers_handle_failures(monkeypatch: pytest.MonkeyPatch):
    def boom(*_a, **_k):
        raise OSError("offline")

    monkeypatch.setattr(readiness, "http_get_json", boom)
    monkeypatch.setattr(readiness, "http_ok", lambda *a, **k: False)
    assert readiness.check_backend("127.0.0.1", 8000)["ok"] is False
    assert readiness.check_frontend("localhost", 3000)["ok"] is False
    ollama = readiness.check_ollama("127.0.0.1", 11434, "qwen2.5-coder:7b")
    assert ollama["online"] is False


def test_frontend_readiness_falls_back_between_loopback_hosts(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def fake_http_ok(url: str, timeout: float = 3.0) -> bool:
        calls.append(url)
        return url == "http://localhost:3000/"

    monkeypatch.setattr(readiness, "http_ok", fake_http_ok)
    result = readiness.check_frontend("127.0.0.1", 3000)

    assert result["ok"] is True
    assert result["url"] == "http://localhost:3000/"
    assert calls == ["http://127.0.0.1:3000/", "http://localhost:3000/"]


def test_frontend_command_launches_craco_directly(fake_repo: Path, monkeypatch: pytest.MonkeyPatch):
    craco_cli = fake_repo / "frontend" / "node_modules" / "@craco" / "craco" / "dist" / "bin" / "craco.js"
    craco_cli.parent.mkdir(parents=True)
    craco_cli.write_text("// stub\n", encoding="utf-8")
    monkeypatch.setattr(services_mod, "detect_node", lambda: {"ok": True, "path": "/usr/bin/node", "detail": None})

    cmd = services_mod._frontend_command(fake_repo)

    assert cmd == ["/usr/bin/node", str(craco_cli), "start"]
    assert "npm" not in " ".join(cmd).lower()


def test_frontend_start_rejects_process_that_dies_after_ready(fake_repo: Path, monkeypatch: pytest.MonkeyPatch):
    class FakeProc:
        pid = 4242
        returncode = 1

        def poll(self):
            return 1

    cfg = validate_config({"frontend_host": "0.0.0.0", "remote_access": True})
    monkeypatch.setattr(services_mod, "check_frontend", lambda *_a, **_k: {"ok": False})
    monkeypatch.setattr(services_mod, "port_in_use", lambda *_a, **_k: False)
    monkeypatch.setattr(services_mod, "_frontend_command", lambda _root: ["node", "craco.js", "start"])
    monkeypatch.setattr(services_mod, "_open_log", lambda *_a, **_k: io.StringIO())
    monkeypatch.setattr(services_mod.subprocess, "Popen", lambda *_a, **_k: FakeProc())
    monkeypatch.setattr(services_mod, "record_service", lambda *_a, **_k: None)
    monkeypatch.setattr(services_mod, "wait_until", lambda *_a, **_k: True)

    with pytest.raises(LauncherError, match="exited immediately"):
        services_mod._start_frontend(fake_repo, cfg)
