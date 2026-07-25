"""Safe process ownership tracking for LUMINA-owned processes only."""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .errors import ShutdownError
from .state import load_state, save_state

logger = logging.getLogger("lumina.launcher.process")

# Markers used to validate ownership (command line must contain these)
SERVICE_MARKERS = {
    "backend": ("uvicorn", "server:app"),
    "frontend": ("node",),  # refined with frontend path / react-scripts / craco
    "ollama": ("ollama", "serve"),
}


def pid_exists(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_command_line(pid: int) -> str:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\").CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return (completed.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def process_command_line(pid: int) -> str:
    if sys.platform == "win32":
        return _windows_command_line(pid)
    try:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            return cmdline_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
    except OSError:
        pass
    return ""


def owns_process(service: str, pid: Optional[int], *, repo_root: Path | None = None) -> bool:
    """Return True only when the PID looks like a LUMINA-owned service process."""
    if not pid_exists(pid):
        return False
    assert pid is not None
    cmdline = process_command_line(int(pid)).lower()
    if not cmdline:
        # If we cannot inspect, refuse to claim ownership (safer shutdown).
        logger.warning("Could not inspect command line for pid %s (%s).", pid, service)
        return False
    markers = SERVICE_MARKERS.get(service, ())
    if service == "backend":
        return "uvicorn" in cmdline and "server:app" in cmdline
    if service == "frontend":
        root_hint = ""
        if repo_root:
            root_hint = str(repo_root / "frontend").lower().replace("/", "\\")
        has_node = "node" in cmdline
        has_frontend = (
            "react-scripts" in cmdline
            or "craco" in cmdline
            or "frontend" in cmdline
            or (root_hint and root_hint in cmdline.replace("/", "\\"))
        )
        return has_node and has_frontend
    if service == "ollama":
        return "ollama" in cmdline and "serve" in cmdline
    return all(marker in cmdline for marker in markers)


def terminate_pid(pid: int, *, force: bool = False, timeout: float = 8.0) -> bool:
    """Terminate a single PID. Returns True if the process is gone."""
    if not pid_exists(pid):
        return True
    if sys.platform == "win32":
        # Soft: taskkill without /F; hard: /F. Never use /IM — only /PID.
        cmd = ["taskkill", "/PID", str(int(pid))]
        if force:
            cmd.append("/F")
        # Also request tree so npm/node children exit with the parent when forced.
        if force:
            cmd.append("/T")
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("taskkill failed for pid %s: %s", pid, exc)
    else:
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.kill(int(pid), sig)
        except ProcessLookupError:
            return True
        except OSError as exc:
            logger.warning("kill failed for pid %s: %s", pid, exc)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_exists(pid):
            return True
        time.sleep(0.2)
    return not pid_exists(pid)


def stop_owned_service(service: str, repo_root: Path | None = None) -> dict[str, Any]:
    """Stop a service only if state PID is owned by LUMINA."""
    state = load_state(repo_root)
    info = state.get("services", {}).get(service) or {}
    pid = info.get("pid")
    result = {"service": service, "pid": pid, "stopped": False, "stale": False, "skipped": False}
    if not pid:
        result["skipped"] = True
        return result
    if not pid_exists(pid):
        result["stale"] = True
        state["services"][service] = {"pid": None, "pgid": None, "command": None, "started_at": None}
        save_state(state, repo_root)
        return result
    if not owns_process(service, pid, repo_root=repo_root):
        logger.error(
            "Refusing to stop pid %s for %s — process does not look LUMINA-owned.",
            pid,
            service,
        )
        result["skipped"] = True
        # Clear stale claim so we do not keep an unsafe pointer
        state["services"][service] = {"pid": None, "pgid": None, "command": None, "started_at": None}
        save_state(state, repo_root)
        return result

    ok = terminate_pid(int(pid), force=False)
    if not ok:
        logger.warning("Graceful stop timed out for %s pid %s; forcing.", service, pid)
        ok = terminate_pid(int(pid), force=True)
    if not ok:
        raise ShutdownError(f"Could not stop LUMINA {service} process (pid {pid}).")
    state["services"][service] = {"pid": None, "pgid": None, "command": None, "started_at": None}
    save_state(state, repo_root)
    result["stopped"] = True
    return result


def cleanup_stale_pids(repo_root: Path | None = None) -> list[str]:
    """Clear state entries whose PIDs are dead or not owned."""
    state = load_state(repo_root)
    cleaned: list[str] = []
    for name, info in list(state.get("services", {}).items()):
        pid = info.get("pid")
        if not pid:
            continue
        if not pid_exists(pid) or not owns_process(name, pid, repo_root=repo_root):
            state["services"][name] = {"pid": None, "pgid": None, "command": None, "started_at": None}
            cleaned.append(name)
            logger.info("Cleared stale PID for %s (%s).", name, pid)
    if cleaned:
        save_state(state, repo_root)
    return cleaned


def record_service(
    service: str,
    pid: int,
    command: list[str],
    *,
    repo_root: Path | None = None,
) -> None:
    state = load_state(repo_root)
    state["services"][service] = {
        "pid": int(pid),
        "pgid": None,
        "command": command,
        "started_at": time.time(),
    }
    save_state(state, repo_root)
