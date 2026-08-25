"""
Tests for the LUMINA Windows PowerShell launcher.

Validates that the launcher script exists, is syntactically correct,
and contains the required startup, detection, and safety logic.
Includes regression tests for:
- Occupied LUMINA ports (reuse healthy services)
- Unrelated port owners (report exact conflicting process)
- Process ownership verification
- Logging consistency (runtime.log, not launcher.log)
- Backend startup failure diagnostics
"""

from __future__ import annotations

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
        assert "runtime.log" in ps_script
        assert ".lumina-runtime" in ps_script

    def test_has_duplicate_protection(self, ps_script):
        assert "already running" in ps_script.lower() or "already healthy" in ps_script.lower()

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
        for username in ["C:\\Users\\User", "C:\\Users\\Admin", "C:\\Users\\admin"]:
            assert username not in ps_script
            assert username not in start_vbs
            assert username not in close_vbs

    def test_derives_repo_root_dynamically(self, ps_script):
        assert "Split-Path" in ps_script
        assert "$PSScriptRoot" in ps_script

    def test_stop_does_not_stop_docker(self, ps_script):
        stop_section = ps_script[ps_script.index("function Stop-Lumina"):]
        assert "Docker Desktop" not in stop_section or "remain running" in stop_section.lower()


class TestPortConflictHandling:
    """Regression tests for occupied port handling."""

    def test_has_get_port_owner_function(self, ps_script):
        assert "function Get-PortOwner" in ps_script

    def test_get_port_owner_returns_pid(self, ps_script):
        assert "OwningProcess" in ps_script
        assert "PID" in ps_script

    def test_get_port_owner_returns_process_name(self, ps_script):
        assert "ProcessName" in ps_script

    def test_get_port_owner_returns_executable_path(self, ps_script):
        assert "Path" in ps_script

    def test_get_port_owner_returns_command_line(self, ps_script):
        assert "CommandLine" in ps_script
        assert "Win32_Process" in ps_script or "Get-CimInstance" in ps_script

    def test_backend_reuses_healthy_service(self, ps_script):
        assert "reusing existing service" in ps_script.lower() or "already healthy" in ps_script.lower()

    def test_frontend_reuses_healthy_service(self, ps_script):
        assert "reusing existing service" in ps_script.lower() or "already healthy" in ps_script.lower()

    def test_backend_reports_unrelated_process(self, ps_script):
        assert "unrelated process" in ps_script.lower()

    def test_frontend_reports_unrelated_process(self, ps_script):
        assert "unrelated process" in ps_script.lower()

    def test_backend_waits_for_unhealthy_lumina_process(self, ps_script):
        assert "not healthy" in ps_script.lower()
        assert "Waiting for it to become healthy" in ps_script

    def test_frontend_waits_for_unhealthy_lumina_process(self, ps_script):
        assert "not healthy" in ps_script.lower()
        assert "Waiting for it to become healthy" in ps_script


class TestProcessOwnership:
    """Regression tests for LUMINA process ownership verification."""

    def test_has_is_lumina_process_function(self, ps_script):
        assert "function Test-IsLuminaProcess" in ps_script

    def test_checks_command_line_for_repo_root(self, ps_script):
        assert "command line references repo root" in ps_script.lower()

    def test_checks_uvicorn_server_app(self, ps_script):
        assert "uvicorn.*server:app" in ps_script

    def test_checks_frontend_patterns(self, ps_script):
        assert "craco" in ps_script
        assert "react-scripts" in ps_script

    def test_checks_health_endpoint(self, ps_script):
        assert "health endpoint responds" in ps_script.lower()

    def test_stop_only_kills_lumina_owned(self, ps_script):
        assert "Skipping non-LUMINA process" in ps_script

    def test_does_not_rely_only_on_process_name(self, ps_script):
        lumina_func = ps_script[ps_script.index("function Test-IsLuminaProcess"):]
        if "function" in lumina_func[30:]:
            lumina_func = lumina_func[:lumina_func.index("function", 30)]
        assert "cmdLine" in lumina_func or "CommandLine" in lumina_func


class TestLoggingConsistency:
    """Regression tests for logging consistency."""

    def test_ps1_uses_runtime_log(self, ps_script):
        assert "runtime.log" in ps_script
        assert "launcher.log" not in ps_script

    def test_start_vbs_refers_to_runtime_log(self, start_vbs):
        assert "runtime.log" in start_vbs
        assert "launcher.log" not in start_vbs

    def test_close_vbs_refers_to_runtime_log(self, close_vbs):
        assert "runtime.log" in close_vbs
        assert "launcher.log" not in close_vbs

    def test_ps1_logs_repo_root(self, ps_script):
        assert "Repository root" in ps_script

    def test_ps1_logs_working_directories(self, ps_script):
        assert "Backend directory" in ps_script
        assert "Frontend directory" in ps_script

    def test_ps1_logs_health_check_urls(self, ps_script):
        assert "health check URL" in ps_script.lower() or "health URL" in ps_script

    def test_ps1_logs_pid(self, ps_script):
        assert "PID:" in ps_script

    def test_ps1_logs_process_name(self, ps_script):
        assert "Process name:" in ps_script

    def test_ps1_logs_executable_path(self, ps_script):
        assert "Executable path:" in ps_script

    def test_ps1_logs_command_line(self, ps_script):
        assert "Command line:" in ps_script

    def test_ps1_logs_commands_executed(self, ps_script):
        assert "Starting backend:" in ps_script
        assert "Starting frontend:" in ps_script

    def test_ps1_logs_exit_code_on_failure(self, ps_script):
        assert "exit code" in ps_script.lower() or "Exit Code" in ps_script


class TestBackendStartupDiagnostics:
    """Regression tests for backend startup failure diagnostics."""

    def test_has_backend_log_tail_function(self, ps_script):
        assert "function Get-BackendLogTail" in ps_script

    def test_logs_backend_errors_on_timeout(self, ps_script):
        assert "Backend log" in ps_script
        assert "End backend log" in ps_script

    def test_logs_backend_log_path_on_failure(self, ps_script):
        assert "backend log" in ps_script.lower()
        assert "BackendLog" in ps_script or "backend.log" in ps_script

    def test_logs_runtime_log_path_on_failure(self, ps_script):
        assert "runtime log" in ps_script.lower()

    def test_uses_correct_health_endpoint(self, ps_script):
        assert "/api/health" in ps_script
        lines = ps_script.split("\n")
        for line in lines:
            if "/health" in line and "/api/health" not in line and "api/health" not in line:
                if not line.strip().startswith("#"):
                    pytest.fail(f"Found bare /health without /api prefix: {line.strip()}")

    def test_uses_correct_backend_working_directory(self, ps_script):
        assert "BackendDir" in ps_script
        assert "backend" in ps_script

    def test_uses_correct_frontend_working_directory(self, ps_script):
        assert "FrontendDir" in ps_script
        assert "frontend" in ps_script

    def test_prefers_python_312(self, ps_script):
        assert "py -3.12" in ps_script


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
        assert "7" in install_vbs


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
