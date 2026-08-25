"""Local runtime / system status helpers for the LUMINA backend.

Reads launcher state from ``<repo>/.lumina-runtime`` without starting services.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from local_tools import resolve_executable, run_version

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
        "preferred_ollama_model": os.environ.get("CODE_MODEL", "qwen2.5-coder:1.5b"),
        "code_builder_num_ctx": int(os.environ.get("CODE_BUILDER_NUM_CTX", "4096")),
        "code_builder_num_predict": int(os.environ.get("CODE_BUILDER_NUM_PREDICT", "2048")),
        "backend_host": os.environ.get("LUMINA_BACKEND_HOST", "127.0.0.1"),
        "backend_port": int(os.environ.get("LUMINA_BACKEND_PORT", "8000")),
        "frontend_host": os.environ.get("LUMINA_FRONTEND_HOST", "localhost"),
        "frontend_port": int(os.environ.get("LUMINA_FRONTEND_PORT", "3000")),
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


def _run_version(executable: str, *args: str, timeout: float = 5.0) -> dict[str, Any]:
    return run_version(executable, *args, timeout=timeout)


def _powershell_json(script: str, timeout: float = 8.0) -> Any:
    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if not powershell:
        return None
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        return json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None


def detect_npm_version() -> Optional[str]:
    result = _run_version("npm", "--version")
    return result.get("version") if result.get("available") else None


def detect_git() -> dict[str, Any]:
    return _run_version("git", "--version")


def detect_ffmpeg() -> dict[str, Any]:
    ffmpeg = _run_version("ffmpeg", "-version")
    ffprobe = _run_version("ffprobe", "-version")
    return {**ffmpeg, "ffprobe_available": bool(ffprobe.get("available")), "ffprobe_path": ffprobe.get("path"), "ffprobe_version": ffprobe.get("version")}


def detect_tesseract() -> dict[str, Any]:
    candidates = [
        os.environ.get("TESSERACT_CMD"),
        str(repo_root() / "tools" / "tesseract" / "tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            try:
                completed = subprocess.run([candidate, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False)
                first = (completed.stdout or completed.stderr or "").strip().splitlines()
                return {"available": completed.returncode == 0, "path": candidate, "version": first[0] if first else None}
            except (OSError, subprocess.SubprocessError):
                pass
    result = _run_version("tesseract", "--version")
    return {"available": bool(result.get("available")), "path": result.get("path"), "version": result.get("version")}


def detect_gpu() -> dict[str, Any]:
    devices = []
    if platform.system().lower() == "windows":
        payload = _powershell_json(
            "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterCompatibility,AdapterRAM,DriverVersion | ConvertTo-Json -Depth 3"
        )
        rows = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
        for row in rows:
            ram = row.get("AdapterRAM") if isinstance(row, dict) else None
            devices.append({
                "vendor": row.get("AdapterCompatibility") or _infer_gpu_vendor(row.get("Name", "")),
                "model": row.get("Name"),
                "vram_bytes": int(ram) if isinstance(ram, int) and ram > 0 else None,
                "driver_version": row.get("DriverVersion"),
            })
    cuda = _run_version("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader")
    if cuda.get("available") and cuda.get("version"):
        parts = [x.strip() for x in str(cuda["version"]).split(",")]
        if parts and not devices:
            devices.append({"vendor": "NVIDIA", "model": parts[0], "vram_bytes": _parse_mebibytes(parts[1]) if len(parts) > 1 else None, "driver_version": None})
    return {"available": bool(devices), "devices": devices, "cuda_available": bool(cuda.get("available")), "directml_available": platform.system().lower() == "windows" and bool(devices)}


def _infer_gpu_vendor(name: str) -> str | None:
    lowered = str(name).lower()
    if "nvidia" in lowered: return "NVIDIA"
    if "amd" in lowered or "radeon" in lowered: return "AMD"
    if "intel" in lowered: return "Intel"
    return None


def _parse_mebibytes(text: str) -> int | None:
    match = re.search(r"(\d+)", str(text))
    return int(match.group(1)) * 1024 * 1024 if match else None


def detect_audio_devices() -> dict[str, Any]:
    if platform.system().lower() != "windows":
        return {"microphones": [], "outputs": [], "available": False, "reason": "Audio device enumeration is implemented for Windows."}
    payload = _powershell_json(
        "Get-CimInstance Win32_SoundDevice | Select-Object Name,Manufacturer,Status | ConvertTo-Json -Depth 3"
    )
    rows = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
    devices = [{"name": row.get("Name"), "manufacturer": row.get("Manufacturer"), "status": row.get("Status")} for row in rows if isinstance(row, dict)]
    return {"available": bool(devices), "microphones": devices, "outputs": devices, "note": "Windows WMI exposes sound endpoints without reliably separating input/output roles."}


def detect_memory() -> dict[str, Any]:
    if platform.system().lower() == "windows":
        payload = _powershell_json("Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory | ConvertTo-Json")
        if isinstance(payload, dict) and payload.get("TotalPhysicalMemory"):
            return {"total_bytes": int(payload["TotalPhysicalMemory"]), "available": True}
    return {"total_bytes": None, "available": False}


def detect_local_model_directories() -> list[dict[str, Any]]:
    candidates = [repo_root() / ".lumina" / "runtime" / "models", Path.home() / ".ollama" / "models"]
    rows = []
    for path in candidates:
        rows.append({"path": str(path), "exists": path.exists(), "file_count": sum(1 for p in path.rglob("*") if p.is_file()) if path.exists() else 0})
    return rows


def detect_ports(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_runtime_config()
    required = [
        {"name": "backend", "host": cfg.get("backend_host", "127.0.0.1"), "port": int(cfg.get("backend_port", 8000))},
        {"name": "frontend", "host": cfg.get("frontend_host", "localhost"), "port": int(cfg.get("frontend_port", 3000))},
        {"name": "ollama", "host": cfg.get("ollama_host", "127.0.0.1"), "port": int(cfg.get("ollama_port", 11434))},
    ]
    for item in required:
        item["listening"] = port_listening(item["host"], item["port"])
    return {"required": required}


def detect_local_environment(active_jobs: int = 0) -> dict[str, Any]:
    cfg = load_runtime_config()
    disk = shutil.disk_usage(repo_root())
    python_info = {"version": platform.python_version(), "executable": sys.executable}
    node = _run_version("node", "--version")
    npm = _run_version("npm", "--version")
    ffmpeg = detect_ffmpeg()
    tesseract = detect_tesseract()
    gpu = detect_gpu()
    return {
        "operating_system": {"system": platform.system(), "release": platform.release(), "version": platform.version(), "machine": platform.machine()},
        "python": python_info,
        "node": {"available": bool(node.get("available")), "version": str(node.get("version") or "").lstrip("v") or None, "path": node.get("path")},
        "npm": {"available": bool(npm.get("available")), "version": npm.get("version"), "path": npm.get("path")},
        "git": detect_git(),
        "ffmpeg": ffmpeg,
        "ocr": {"tesseract": tesseract, "ready": bool(tesseract.get("available"))},
        "gpu": gpu,
        "cpu": {"model": platform.processor() or platform.machine(), "cores": os.cpu_count() or 1},
        "ram": detect_memory(),
        "disk": {"path": str(repo_root()), "free_bytes": disk.free, "used_bytes": disk.used, "total_bytes": disk.total},
        "audio": detect_audio_devices(),
        "local_model_directories": detect_local_model_directories(),
        "ports": detect_ports(cfg),
        "running_lumina_services": build_system_status(active_jobs=active_jobs).get("runtime_manager", {}),
        "capabilities": {
            "cuda": "ready" if gpu.get("cuda_available") else "unsupported_or_not_installed",
            "directml": "ready" if gpu.get("directml_available") else "unsupported",
            "ffmpeg_media_processing": "ready" if ffmpeg.get("available") and ffmpeg.get("ffprobe_available") else "requires_installation",
            "ocr": "ready" if tesseract.get("available") else "requires_installation",
        },
        "detected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def build_installation_center(active_jobs: int = 0) -> dict[str, Any]:
    env = detect_local_environment(active_jobs=active_jobs)
    packages = [
        {"id": "ffmpeg", "name": "FFmpeg + FFprobe", "required_for": ["Video Studio export/probe", "Voice Studio processing"], "status": "installed" if env["ffmpeg"].get("available") and env["ffmpeg"].get("ffprobe_available") else "missing", "safe_action": "Install with winget/choco or download from ffmpeg.org; external download requires owner approval.", "external_download": True, "restart_required": False},
        {"id": "tesseract", "name": "Tesseract OCR", "required_for": ["Document Studio scanned image OCR"], "status": "installed" if env.get("ocr", {}).get("ready") else "missing", "path": env.get("ocr", {}).get("tesseract", {}).get("path"), "version": env.get("ocr", {}).get("tesseract", {}).get("version"), "safe_action": "Install Tesseract OCR for Windows and pytesseract in the backend Python environment.", "external_download": True, "restart_required": True},
        {"id": "python-packages", "name": "Backend Python packages", "required_for": ["API", "Document Studio", "Photo Studio"], "status": "installed", "safe_action": "Run pip install -r backend/requirements.txt only after reviewing the file.", "external_download": True, "restart_required": True},
        {"id": "node-dependencies", "name": "Frontend Node dependencies", "required_for": ["Frontend", "Production build"], "status": "installed" if (repo_root() / "frontend" / "node_modules").exists() else "missing", "safe_action": "Run npm ci from frontend after reviewing package-lock.json.", "external_download": True, "restart_required": False},
        {"id": "ollama", "name": "Ollama local model runtime", "required_for": ["Code Builder AI planning"], "status": "installed" if check_ollama().get("online") else "optional_missing", "safe_action": "Install/start Ollama and pull the configured coding model; large model downloads require approval.", "external_download": True, "restart_required": False},
    ]
    return {"environment": env, "dependencies": packages, "disk_requirements": {"recommended_free_bytes": 10 * 1024**3, "free_bytes": env["disk"]["free_bytes"]}, "approval_required_for": ["administrator privileges", "external downloads", "large model downloads", "system-level changes", "irreversible operations"]}


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
        "code_builder_num_ctx": as_int(merged["code_builder_num_ctx"], "code_builder_num_ctx", 1, 131_072),
        "code_builder_num_predict": as_int(merged["code_builder_num_predict"], "code_builder_num_predict", 1, 32_768),
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
    overall = backend_ok and bool(frontend.get("reachable"))
    readiness = "ready" if overall else "degraded" if backend_ok else "down"

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
