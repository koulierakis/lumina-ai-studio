"""Dependency detection helpers (Python, Node, npm, Ollama, model)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


def _run(cmd: list[str], timeout: float = 8.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, (completed.stdout or "").strip(), (completed.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def which(name: str) -> Optional[str]:
    return shutil.which(name)


def detect_python() -> dict[str, Any]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    supported = sys.version_info >= (3, 11)
    return {
        "ok": supported,
        "path": sys.executable,
        "version": version,
        "detail": None if supported else "Python 3.11+ is required.",
    }


def detect_node() -> dict[str, Any]:
    path = which("node")
    if not path:
        return {"ok": False, "path": None, "version": None, "detail": "Node.js was not found on PATH."}
    code, out, err = _run([path, "--version"])
    version = out or err
    return {
        "ok": code == 0 and bool(version),
        "path": path,
        "version": version.lstrip("v") if version else None,
        "detail": None if code == 0 else "Node.js is installed but did not report a version.",
    }


def detect_npm() -> dict[str, Any]:
    path = which("npm") or which("npm.cmd")
    if not path:
        return {"ok": False, "path": None, "version": None, "detail": "npm was not found on PATH."}
    code, out, err = _run([path, "--version"])
    version = out or err
    return {
        "ok": code == 0 and bool(version),
        "path": path,
        "version": version,
        "detail": None if code == 0 else "npm is installed but did not report a version.",
    }


def detect_ollama() -> dict[str, Any]:
    path = which("ollama") or which("ollama.exe")
    if not path:
        return {"ok": False, "path": None, "version": None, "detail": "Ollama was not found on PATH."}
    code, out, err = _run([path, "--version"])
    version = out or err
    return {
        "ok": True,
        "path": path,
        "version": version or "unknown",
        "detail": None,
    }


def detect_project_paths(repo_root: Path) -> dict[str, Any]:
    checks = {
        "repo_root": repo_root.is_dir(),
        "backend": (repo_root / "backend" / "server.py").is_file(),
        "frontend": (repo_root / "frontend" / "package.json").is_file(),
        "launcher": (repo_root / "launcher" / "lumina_launcher.py").is_file(),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {"ok": not missing, "checks": checks, "missing": missing}
