"""Unit tests for health + system status + runtime settings."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import runtime_info
import server


@pytest.mark.anyio
async def test_health_includes_structured_fields(monkeypatch):
    async def fake_statuses():
        return []

    async def fake_summary():
        return {"ok": True}

    monkeypatch.setattr(server.provider_manager, "statuses", fake_statuses)
    monkeypatch.setattr(server.provider_manager, "health_summary", fake_summary)
    monkeypatch.setattr(server, "available_providers", lambda: ["mock"])
    payload = await server.health()
    assert payload["status"] == "ok"
    assert payload["backend"] == "ok"
    assert "timestamp" in payload
    assert "version" in payload


def test_runtime_config_invalid_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime_info, "repo_root", lambda: tmp_path)
    cfg_path = tmp_path / ".lumina-runtime" / "config.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("{bad", encoding="utf-8")
    cfg = runtime_info.load_runtime_config()
    assert cfg["backend_port"] == 8000


def test_validate_and_save_runtime_settings(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime_info, "repo_root", lambda: tmp_path)
    saved = runtime_info.save_runtime_settings(
        {
            "dashboard_auto_open": False,
            "preferred_ollama_model": "qwen2.5-coder:7b",
            "backend_port": 8000,
            "frontend_port": 3000,
            "startup_timeout_seconds": 90,
            "automatic_ollama_startup": True,
            "logging_level": "WARNING",
        }
    )
    assert saved["dashboard_auto_open"] is False
    assert saved["logging_level"] == "WARNING"
    loaded = json.loads((tmp_path / ".lumina-runtime" / "config.json").read_text(encoding="utf-8"))
    assert loaded["startup_timeout_seconds"] == 90


def test_build_system_status_shape(monkeypatch):
    monkeypatch.setattr(
        runtime_info,
        "check_ollama",
        lambda cfg=None: {"online": True, "model": "qwen2.5-coder:7b", "installed": True, "models": ["qwen2.5-coder:7b"]},
    )
    monkeypatch.setattr(
        runtime_info,
        "check_frontend",
        lambda cfg=None: {"reachable": True, "url": "http://localhost:3000/"},
    )
    monkeypatch.setattr(runtime_info, "load_runtime_state", lambda: {"warnings": [], "services": {}})
    monkeypatch.setattr(runtime_info, "detect_node_version", lambda: "20.0.0")
    status = runtime_info.build_system_status(active_jobs=2)
    assert status["system_ready"] is True
    assert status["active_jobs"] == 2
    assert status["backend"]["status"] == "ok"
    assert status["coding_model"]["installed"] is True
    assert "warnings" in status


def test_build_system_status_ready_without_ollama(monkeypatch):
    monkeypatch.setattr(
        runtime_info,
        "check_ollama",
        lambda cfg=None: {"online": False, "model": "qwen2.5-coder:7b", "installed": False, "models": []},
    )
    monkeypatch.setattr(
        runtime_info,
        "check_frontend",
        lambda cfg=None: {"reachable": True, "url": "http://localhost:3000/"},
    )
    monkeypatch.setattr(runtime_info, "load_runtime_state", lambda: {"warnings": [], "services": {}})
    monkeypatch.setattr(runtime_info, "detect_node_version", lambda: "20.0.0")

    status = runtime_info.build_system_status(active_jobs=0)

    assert status["system_ready"] is True
    assert status["overall_readiness"] == "ready"
    assert status["ollama"]["status"] == "offline"
    assert "Local AI (Ollama) is offline." in status["warnings"]
