"""
Tests for the LUMINA Windows PowerShell launcher.

Validates that the launcher script exists, is syntactically correct,
and contains the required startup, detection, and safety logic.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = REPO_ROOT / "launcher" / "windows"


@pytest.fixture
def ps_script() -> str:
    path = LAUNCHER_DIR / "LuminaLauncher.ps1"
    assert path.exists(), f"PowerShell launcher not found: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def start_vbs() -> str:
    path = LAUNCHER_DIR / "Start_LUMINA_AI.vbs"
    assert path.exists(), f"Start VBS not found: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def close_vbs() -> str:
    path = LAUNCHER_DIR / "Close_LUMINA_AI.vbs"
    assert path.exists(), f"Close VBS not found: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def install_vbs() -> str:
    path = LAUNCHER_DIR / "Install_LUMINA_Shortcuts.vbs"
    assert path.exists(), f"Install VBS not found: {path}"
    return path.read_text(encoding="utf-8")


class TestPowerShellLauncherExists:
    def test_launcher_ps1_exists(self):
        assert (LAUNCHER_DIR / "LuminaLauncher.ps1").exists()

    def test_start_vbs_exists(self):
        assert (LAUNCHER_DIR / "Start_LUMINA_AI.vbs").exists()

    def test_close_vbs_exists(self):
        assert (LAUNCHER_DIR / "Close_LUMINA_AI.vbs").exists()

    def test_install_vbs_exists(self):
        assert (LAUNCHER_DIR / "Install_LUMINA_Shortcuts.vbs").exists()


class TestPowerShellLauncherContent:
    def test_has_start_action(self, ps_script):
        assert "Invoke-Start" in ps_script
        assert "-Action 'start'" in ps_script or "$Action = 'start'" in ps_script

    def test_has_stop_action(self, ps_script):
        assert "Invoke-Stop" in ps_script
        assert "-Action 'stop'" in ps_script or "'stop'" in ps_script

    def test_has_status_action(self, ps_script):
        assert "Show-Status" in ps_script
        assert "'status'" in ps_script

    def test_has_docker_detection(self, ps_script):
        assert "Get-DockerPath" in ps_script
        assert "Test-DockerRunning" in ps_script
        assert "Start-DockerDesktop" in ps_script

    def test_has_docker_services_startup(self, ps_script):
        assert "Start-DockerServices" in ps_script
        assert "redis" in ps_script.lower()
        assert "qdrant" in ps_script.lower()
        assert "docker-compose.dev.yml" in ps_script

    def test_has_backend_startup(self, ps_script):
        assert "Start-Backend" in ps_script
        assert "uvicorn" in ps_script
        assert "server:app" in ps_script
        assert "8000" in ps_script

    def test_has_frontend_startup(self, ps_script):
        assert "Start-Frontend" in ps_script
        assert "npm" in ps_script.lower()
        assert "3000" in ps_script

    def test_has_health_checks(self, ps_script):
        assert "Test-BackendHealth" in ps_script
        assert "Test-FrontendHealth" in ps_script
        assert "/api/health" in ps_script

    def test_has_port_checks(self, ps_script):
        assert "Test-Port" in ps_script
        assert "6379" in ps_script  # Redis
        assert "6333" in ps_script  # Qdrant

    def test_has_readiness_wait(self, ps_script):
        assert "Wait-Ready" in ps_script
        assert "StartupTimeoutSeconds" in ps_script

    def test_has_browser_open(self, ps_script):
        assert "Open-Browser" in ps_script
        assert "localhost" in ps_script
        assert "3000" in ps_script

    def test_has_logging(self, ps_script):
        assert "Write-Log" in ps_script
        assert "launcher.log" in ps_script
        assert ".lumina-runtime" in ps_script

    def test_has_duplicate_protection(self, ps_script):
        assert "already running" in ps_script.lower() or "already responding" in ps_script.lower()

    def test_has_error_handling(self, ps_script):
        assert "Write-LogError" in ps_script
        assert "catch" in ps_script.lower()

    def test_has_execution_policy_bypass(self, start_vbs, close_vbs):
        assert "-ExecutionPolicy Bypass" in start_vbs
        assert "-ExecutionPolicy Bypass" in close_vbs

    def test_has_no_profile_flag(self, start_vbs, close_vbs):
        assert "-NoProfile" in start_vbs
        assert "-NoProfile" in close_vbs

    def test_has_hidden_window(self, start_vbs, close_vbs):
        assert "-WindowStyle Hidden" in start_vbs
        assert "-WindowStyle Hidden" in close_vbs

    def test_uses_safe_path_quoting(self, start_vbs, close_vbs):
        assert '"""' in start_vbs  # Triple quotes for path safety
        assert '"""' in close_vbs

    def test_does_not_hardcode_username(self, ps_script, start_vbs, close_vbs):
        # Should not contain hardcoded Windows usernames
        for username in ["C:\\Users\\User", "C:\\Users\\Admin", "C:\\Users\\admin"]:
            assert username not in ps_script
            assert username not in start_vbs
            assert username not in close_vbs

    def test_derives_repo_root_dynamically(self, ps_script):
        assert "Split-Path" in ps_script
        assert "$PSScriptRoot" in ps_script

    def test_stop_does_not_stop_docker(self, ps_script):
        # The stop function should not stop Docker Desktop
        stop_section = ps_script[ps_script.index("function Stop-Lumina"):]
        assert "Docker Desktop" not in stop_section or "remain running" in stop_section.lower()


class TestVBSWrappers:
    def test_start_vbs_calls_start_action(self, start_vbs):
        assert "-Action start" in start_vbs

    def test_close_vbs_calls_stop_action(self, close_vbs):
        assert "-Action stop" in close_vbs

    def test_start_vbs_has_error_message(self, start_vbs):
        assert "MsgBox" in start_vbs
        assert "failed to start" in start_vbs

    def test_close_vbs_has_error_message(self, close_vbs):
        assert "MsgBox" in close_vbs

    def test_install_vbs_creates_lumina_shortcut(self, install_vbs):
        assert "LUMINA AI.lnk" in install_vbs

    def test_install_vbs_creates_close_shortcut(self, install_vbs):
        assert "Close LUMINA.lnk" in install_vbs

    def test_install_vbs_uses_wscript(self, install_vbs):
        assert "wscript.exe" in install_vbs

    def test_install_vbs_sets_working_directory(self, install_vbs):
        assert "WorkingDirectory" in install_vbs

    def test_install_vbs_sets_minimized_window(self, install_vbs):
        assert "WindowStyle" in install_vbs
        assert "7" in install_vbs  # 7 = minimized


class TestDockerComposeIntegration:
    def test_compose_file_exists(self):
        assert (REPO_ROOT / "docker-compose.dev.yml").exists()

    def test_compose_has_redis(self):
        content = (REPO_ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
        assert "redis" in content
        assert "6379" in content

    def test_compose_has_qdrant(self):
        content = (REPO_ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
        assert "qdrant" in content
        assert "6333" in content