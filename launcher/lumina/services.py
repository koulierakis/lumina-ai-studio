"""Start and stop LUMINA-owned local services."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Optional

from .config import load_config
from .detect import detect_npm, detect_node, detect_ollama, detect_python
from .errors import (
    AlreadyRunningError,
    DependencyMissingError,
    LauncherError,
    PortInUseError,
    StartupTimeoutError,
)
from .paths import find_repo_root, lock_path, logs_dir
from .process_manager import (
    cleanup_stale_pids,
    owns_process,
    pid_exists,
    record_service,
    stop_owned_service,
)
from .readiness import check_backend, check_frontend, check_ollama, port_in_use, wait_until
from .state import clear_state, load_state, save_state

logger = logging.getLogger("lumina.launcher.services")


def _creation_flags() -> int:
    if sys.platform == "win32":
        # Hide console windows for child processes when launched via VBS/GUI path.
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return 0


def _open_log(name: str, repo_root: Path) -> Any:
    path = logs_dir(repo_root) / f"{name}.log"
    return open(path, "a", encoding="utf-8")  # noqa: SIM115 - kept open for subprocess lifetime


def _acquire_lock(repo_root: Path) -> None:
    path = lock_path(repo_root)
    if path.exists():
        try:
            existing = int(path.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            existing = 0
        if existing and pid_exists(existing):
            raise AlreadyRunningError(
                f"LUMINA runtime lock is held by process {existing}. "
                "Use 'status' or 'stop' if you need to recover."
            )
        logger.warning("Removing stale lock file (pid %s).", existing)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    path.write_text(str(os.getpid()), encoding="utf-8")


def _release_lock(repo_root: Path) -> None:
    path = lock_path(repo_root)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.warning("Could not remove lock file %s", path)


def is_lumina_running(repo_root: Path | None = None) -> bool:
    root = repo_root or find_repo_root()
    cleanup_stale_pids(root)
    state = load_state(root)
    cfg = load_config(root)
    backend_pid = (state.get("services") or {}).get("backend", {}).get("pid")
    frontend_pid = (state.get("services") or {}).get("frontend", {}).get("pid")
    backend_ready = check_backend(cfg["backend_host"], cfg["backend_port"]).get("ok")
    frontend_ready = check_frontend(cfg["frontend_host"], cfg["frontend_port"]).get("ok")
    owned_backend = owns_process("backend", backend_pid, repo_root=root) if backend_pid else False
    owned_frontend = owns_process("frontend", frontend_pid, repo_root=root) if frontend_pid else False
    return bool((owned_backend and backend_ready) or (owned_frontend and frontend_ready) or (backend_ready and frontend_ready and (owned_backend or owned_frontend)))


def _ensure_dependencies(cfg: dict[str, Any]) -> None:
    py = detect_python()
    if not py["ok"]:
        raise DependencyMissingError(py["detail"] or "Python 3.11+ is required.")
    node = detect_node()
    if not node["ok"]:
        raise DependencyMissingError(node["detail"] or "Node.js is required.")
    npm = detect_npm()
    if not npm["ok"]:
        raise DependencyMissingError(npm["detail"] or "npm is required.")
    ollama = detect_ollama()
    if not ollama["ok"] and cfg.get("automatic_ollama_startup"):
        raise DependencyMissingError(
            "Ollama is not installed or not on PATH. Install Ollama or disable automatic Ollama startup."
        )


def _start_ollama_if_needed(repo_root: Path, cfg: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    status = check_ollama(cfg["ollama_host"], cfg["ollama_port"], cfg["preferred_ollama_model"])
    if status.get("online"):
        if not status.get("installed"):
            warnings.append(
                f"Ollama is online but model '{cfg['preferred_ollama_model']}' is not installed. "
                f"Run: ollama pull {cfg['preferred_ollama_model']}"
            )
        return warnings

    if not cfg.get("automatic_ollama_startup"):
        warnings.append("Ollama is not running and automatic startup is disabled.")
        return warnings

    ollama = detect_ollama()
    if not ollama["ok"]:
        warnings.append("Ollama is not installed; Local AI features will be unavailable.")
        return warnings

    if port_in_use(cfg["ollama_host"], cfg["ollama_port"]):
        warnings.append("Ollama port is occupied but the API did not respond yet.")
        return warnings

    log_handle = _open_log("ollama", repo_root)
    cmd = [ollama["path"], "serve"]
    logger.info("Starting Ollama: %s", " ".join(cmd))
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(repo_root),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=_creation_flags(),
        shell=False,
    )
    record_service("ollama", proc.pid, cmd, repo_root=repo_root)
    state = load_state(repo_root)
    state["owned_ollama"] = True
    save_state(state, repo_root)

    ready = wait_until(
        lambda: bool(check_ollama(cfg["ollama_host"], cfg["ollama_port"], cfg["preferred_ollama_model"]).get("online")),
        timeout=min(60, cfg["startup_timeout_seconds"]),
        interval=cfg["readiness_poll_interval_seconds"],
        label="Ollama",
    )
    if not ready:
        warnings.append("Ollama was started but did not become ready in time.")
        return warnings

    status = check_ollama(cfg["ollama_host"], cfg["ollama_port"], cfg["preferred_ollama_model"])
    if not status.get("installed"):
        warnings.append(
            f"Ollama is online but model '{cfg['preferred_ollama_model']}' is not installed. "
            f"Run: ollama pull {cfg['preferred_ollama_model']}"
        )
    return warnings


def _start_backend(repo_root: Path, cfg: dict[str, Any]) -> None:
    host, port = cfg["backend_host"], int(cfg["backend_port"])
    if check_backend(host, port).get("ok"):
        state = load_state(repo_root)
        pid = (state.get("services") or {}).get("backend", {}).get("pid")
        if owns_process("backend", pid, repo_root=repo_root):
            logger.info("Backend already running under LUMINA (pid %s).", pid)
            return
        raise PortInUseError("backend", port)

    if port_in_use(host if host != "0.0.0.0" else "127.0.0.1", port):
        raise PortInUseError("backend", port)

    python = sys.executable
    backend_dir = repo_root / "backend"
    cmd = [
        python,
        "-m",
        "uvicorn",
        "server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    log_handle = _open_log("backend", repo_root)
    logger.info("Starting backend: %s", " ".join(cmd))
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(backend_dir),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=_creation_flags(),
        shell=False,
    )
    record_service("backend", proc.pid, cmd, repo_root=repo_root)
    ready = wait_until(
        lambda: bool(check_backend(host, port).get("ok")),
        timeout=cfg["startup_timeout_seconds"],
        interval=cfg["readiness_poll_interval_seconds"],
        label="Backend",
    )
    if not ready:
        raise StartupTimeoutError("Backend")


def _start_frontend(repo_root: Path, cfg: dict[str, Any]) -> None:
    host, port = cfg["frontend_host"], int(cfg["frontend_port"])
    if check_frontend(host, port).get("ok"):
        state = load_state(repo_root)
        pid = (state.get("services") or {}).get("frontend", {}).get("pid")
        if owns_process("frontend", pid, repo_root=repo_root):
            logger.info("Frontend already running under LUMINA (pid %s).", pid)
            return
        raise PortInUseError("frontend", port)

    check_host = "127.0.0.1" if host in {"localhost", "0.0.0.0"} else host
    if port_in_use(check_host, port):
        raise PortInUseError("frontend", port)

    npm = detect_npm()
    if not npm["ok"]:
        raise DependencyMissingError(npm["detail"] or "npm is required.")

    frontend_dir = repo_root / "frontend"
    # Prefer npm.cmd on Windows for reliable spawn without shell=True
    npm_path = npm["path"]
    cmd = [npm_path, "start"]
    log_handle = _open_log("frontend", repo_root)
    logger.info("Starting frontend: %s", " ".join(cmd))
    env = os.environ.copy()
    env["BROWSER"] = "none"
    env["PORT"] = str(port)
    env.setdefault(
        "REACT_APP_BACKEND_URL",
        f"http://{cfg['backend_host']}:{cfg['backend_port']}",
    )
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(frontend_dir),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=_creation_flags(),
        shell=False,
    )
    record_service("frontend", proc.pid, cmd, repo_root=repo_root)
    ready = wait_until(
        lambda: bool(check_frontend(host, port).get("ok")),
        timeout=cfg["startup_timeout_seconds"],
        interval=cfg["readiness_poll_interval_seconds"],
        label="Frontend",
    )
    if not ready:
        raise StartupTimeoutError("Frontend")


def _open_dashboard(repo_root: Path, cfg: dict[str, Any]) -> None:
    if not cfg.get("dashboard_auto_open"):
        return
    state = load_state(repo_root)
    if cfg.get("open_browser_once") and state.get("browser_opened"):
        logger.info("Dashboard already opened for this runtime session.")
        return
    url = f"http://{cfg['frontend_host']}:{cfg['frontend_port']}/"
    logger.info("Opening dashboard: %s", url)
    try:
        webbrowser.open(url)
        state["browser_opened"] = True
        save_state(state, repo_root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not open browser: %s", exc)
        state.setdefault("warnings", []).append(f"Browser open failed: {exc}")
        save_state(state, repo_root)


def start_all(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    cfg = load_config(root)
    cleanup_stale_pids(root)

    if is_lumina_running(root):
        raise AlreadyRunningError()

    # Also guard against foreign processes already serving our ports
    if check_backend(cfg["backend_host"], cfg["backend_port"]).get("ok") and check_frontend(
        cfg["frontend_host"], cfg["frontend_port"]
    ).get("ok"):
        raise AlreadyRunningError(
            "Backend and frontend are already responding. "
            "If they were started outside LUMINA, stop them manually or use a different port."
        )

    _ensure_dependencies(cfg)
    _acquire_lock(root)

    state = load_state(root)
    state["started_at"] = time.time()
    state["browser_opened"] = False
    state["warnings"] = []
    save_state(state, root)

    try:
        warnings = _start_ollama_if_needed(root, cfg)
        _start_backend(root, cfg)
        _start_frontend(root, cfg)
        state = load_state(root)
        state["warnings"] = warnings
        save_state(state, root)
        _open_dashboard(root, cfg)
        return {
            "ok": True,
            "warnings": warnings,
            "backend": check_backend(cfg["backend_host"], cfg["backend_port"]),
            "frontend": check_frontend(cfg["frontend_host"], cfg["frontend_port"]),
            "ollama": check_ollama(cfg["ollama_host"], cfg["ollama_port"], cfg["preferred_ollama_model"]),
        }
    except Exception:
        logger.exception("Startup failed; attempting cleanup of LUMINA-owned processes.")
        try:
            stop_all(root, release_lock=False)
        except Exception:
            logger.exception("Cleanup after failed start also failed.")
        _release_lock(root)
        raise


def stop_all(repo_root: Path | None = None, *, release_lock: bool = True) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    cleanup_stale_pids(root)
    state = load_state(root)
    results = {
        "frontend": stop_owned_service("frontend", root),
        "backend": stop_owned_service("backend", root),
    }
    # Only stop Ollama if we started it
    if state.get("owned_ollama"):
        results["ollama"] = stop_owned_service("ollama", root)
    else:
        results["ollama"] = {"service": "ollama", "skipped": True, "reason": "not owned by LUMINA"}

    clear_state(root)
    if release_lock:
        _release_lock(root)
    return {"ok": True, "results": results}


def status_report(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    cfg = load_config(root)
    cleanup_stale_pids(root)
    state = load_state(root)
    backend = check_backend(cfg["backend_host"], cfg["backend_port"])
    frontend = check_frontend(cfg["frontend_host"], cfg["frontend_port"])
    ollama = check_ollama(cfg["ollama_host"], cfg["ollama_port"], cfg["preferred_ollama_model"])
    services = state.get("services") or {}
    return {
        "repo_root": str(root),
        "running": is_lumina_running(root),
        "backend": {
            **backend,
            "pid": (services.get("backend") or {}).get("pid"),
            "owned": owns_process("backend", (services.get("backend") or {}).get("pid"), repo_root=root),
        },
        "frontend": {
            **frontend,
            "pid": (services.get("frontend") or {}).get("pid"),
            "owned": owns_process("frontend", (services.get("frontend") or {}).get("pid"), repo_root=root),
        },
        "ollama": {
            **ollama,
            "pid": (services.get("ollama") or {}).get("pid"),
            "owned": bool(state.get("owned_ollama"))
            and owns_process("ollama", (services.get("ollama") or {}).get("pid"), repo_root=root),
        },
        "warnings": state.get("warnings") or [],
        "started_at": state.get("started_at"),
        "config": {
            "backend_port": cfg["backend_port"],
            "frontend_port": cfg["frontend_port"],
            "preferred_ollama_model": cfg["preferred_ollama_model"],
        },
    }
