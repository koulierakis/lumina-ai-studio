"""Local runtime / system status helpers for the LUMINA backend.

Reads launcher state from ``<repo>/.lumina-runtime`` without starting services.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("lumina.runtime_info")

APP_VERSION = os.environ.get("LUMINA_VERSION", "0.1.0")
_STARTED_AT = time.time()


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def runtime_dir() -> Path:
    return repo_root() / ".lumina-runtime"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def load_runtime_config() -> dict[str, Any]:
    defaults = {
        "dashboard_auto_open": True,
        "preferred_ollama_model": os.environ.get("CODE_MODEL", "qwen2.5-coder:7b"),
        "backend_host": "127.0.0.1",
        "backend_port": 8000,
        "frontend_host": "localhost",
        "frontend_port": 3000,
        "ollama_host": "127.0.0.1",
        "ollama_port": 11434,
        "startup_timeout_seconds": 180,
        "readiness_poll_interval_seconds": 1.5,
        "automatic_ollama_startup": True,
        "logging_level": "INFO",
        "open_browser_once": True,
    }
    path = runtime_dir() / "config.json"
    if not path.exists():
        return defaults
    data = _read_json(path)
    merged = {**defaults, **{k: v for k, v in data.items() if k in defaults}}
    return merged


def load_runtime_state() -> dict[str, Any]:
    return _read_json(runtime_dir() / "runtime_state.json")


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = int(getattr(response, "status", 200) or 200)
            return 200 <= status < 500
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _http_json(url: str, timeout: float = 3.0) -> tuple[bool, Any]:
    try:
        request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
            return True, json.loads(body)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False, {}


def detect_node_version() -> Optional[str]:
    path = shutil.which("node") or shutil.which("node.exe")
    if not path:
        return None
    try:
        completed = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        text = (completed.stdout or completed.stderr or "").strip()
        return text.lstrip("v") or None
    except (OSError, subprocess.SubprocessError):
        return None


def check_ollama(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_runtime_config()
    model = str(cfg.get("preferred_ollama_model") or "qwen2.5-coder:7b")
    host = cfg.get("ollama_host", "127.0.0.1")
    port = int(cfg.get("ollama_port", 11434))
    url = f"http://{host}:{port}/api/tags"
    ok, payload = _http_json(url)
    models = []
    if isinstance(payload, dict):
        models = [m.get("name") for m in payload.get("models", []) if isinstance(m, dict)]
    installed = model in models
    return {
        "online": ok,
        "model": model,
        "installed": installed,
        "models": [name for name in models if isinstance(name, str)][:30],
        "url": url,
    }


def check_frontend(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_runtime_config()
    host = cfg.get("frontend_host", "localhost")
    port = int(cfg.get("frontend_port", 3000))
    url = f"http://{host}:{port}/"
    return {"reachable": _http_ok(url), "url": url}


def port_listening(host: str, port: int) -> bool:
    target = "127.0.0.1" if host in {"0.0.0.0", "localhost"} else host
    try:
        with socket.create_connection((target, int(port)), timeout=0.4):
            return True
    except OSError:
        return False


def validate_runtime_settings(body: dict[str, Any]) -> dict[str, Any]:
    """Validate settings used by Settings UI / launcher config file."""
    current = load_runtime_config()
    allowed = set(current.keys())
    merged = {**current, **{k: v for k, v in body.items() if k in allowed}}

    def as_bool(value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false", "1", "0", "yes", "no"}:
            return value.lower() in {"true", "1", "yes"}
        raise ValueError(f"Invalid boolean for {name}")

    def as_int(value: Any, name: str, lo: int, hi: int) -> int:
        number = int(value)
        if number < lo or number > hi:
            raise ValueError(f"{name} out of range")
        return number

    level = str(merged.get("logging_level", "INFO")).upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("Invalid logging_level")

    model = str(merged.get("preferred_ollama_model") or "").strip()
    if not model or len(model) > 120:
        raise ValueError("Invalid preferred_ollama_model")

    return {
        "dashboard_auto_open": as_bool(merged["dashboard_auto_open"], "dashboard_auto_open"),
        "preferred_ollama_model": model,
        "backend_host": str(merged["backend_host"]).strip() or "127.0.0.1",
        "backend_port": as_int(merged["backend_port"], "backend_port", 1, 65535),
        "frontend_host": str(merged["frontend_host"]).strip() or "localhost",
        "frontend_port": as_int(merged["frontend_port"], "frontend_port", 1, 65535),
        "ollama_host": str(merged["ollama_host"]).strip() or "127.0.0.1",
        "ollama_port": as_int(merged["ollama_port"], "ollama_port", 1, 65535),
        "startup_timeout_seconds": as_int(merged["startup_timeout_seconds"], "startup_timeout_seconds", 30, 900),
        "readiness_poll_interval_seconds": float(merged.get("readiness_poll_interval_seconds", 1.5)),
        "automatic_ollama_startup": as_bool(merged["automatic_ollama_startup"], "automatic_ollama_startup"),
        "logging_level": level,
        "open_browser_once": as_bool(merged["open_browser_once"], "open_browser_once"),
    }


def save_runtime_settings(body: dict[str, Any]) -> dict[str, Any]:
    import os
    import tempfile

    validated = validate_runtime_settings(body)
    path = runtime_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".cfg_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(validated, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass
    return validated


def build_system_status(*, active_jobs: int = 0) -> dict[str, Any]:
    cfg = load_runtime_config()
    state = load_runtime_state()
    ollama = check_ollama(cfg)
    frontend = check_frontend(cfg)
    warnings: list[str] = []
    if isinstance(state.get("warnings"), list):
        warnings.extend(str(item) for item in state["warnings"])
    if not ollama.get("online"):
        warnings.append("Local AI (Ollama) is offline.")
    elif not ollama.get("installed"):
        warnings.append(f"Coding model '{ollama.get('model')}' is not installed in Ollama.")
    if not frontend.get("reachable"):
        warnings.append("Frontend did not respond on the configured port.")

    services = state.get("services") if isinstance(state.get("services"), dict) else {}
    safe_pids = {}
    for name in ("backend", "frontend", "ollama"):
        pid = (services.get(name) or {}).get("pid")
        if isinstance(pid, int) and pid > 0:
            safe_pids[name] = pid

    backend_ok = True  # this process is serving the request
    overall = backend_ok and bool(frontend.get("reachable")) and bool(ollama.get("online"))
    readiness = "ready" if overall and ollama.get("installed") else "degraded" if backend_ok else "down"

    return {
        "overall_readiness": readiness,
        "system_ready": readiness == "ready",
        "backend": {
            "status": "ok",
            "host": cfg.get("backend_host"),
            "port": cfg.get("backend_port"),
        },
        "frontend": {
            "status": "ok" if frontend.get("reachable") else "unreachable",
            "reachable": bool(frontend.get("reachable")),
            "url": frontend.get("url"),
            "host": cfg.get("frontend_host"),
            "port": cfg.get("frontend_port"),
        },
        "ollama": {
            "status": "ok" if ollama.get("online") else "offline",
            "online": bool(ollama.get("online")),
            "model": ollama.get("model"),
            "model_installed": bool(ollama.get("installed")),
            "models_sample": ollama.get("models") or [],
        },
        "coding_model": {
            "name": ollama.get("model"),
            "installed": bool(ollama.get("installed")),
        },
        "active_jobs": int(active_jobs),
        "python_version": platform.python_version(),
        "node_version": detect_node_version(),
        "uptime_seconds": max(0, int(time.time() - _STARTED_AT)),
        "application_version": APP_VERSION,
        "runtime_manager": {
            "state_present": bool(state),
            "started_at": state.get("started_at"),
            "owned_ollama": bool(state.get("owned_ollama")),
            "browser_opened": bool(state.get("browser_opened")),
            "process_ids": safe_pids,
        },
        "warnings": warnings,
        "platform": platform.system(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
