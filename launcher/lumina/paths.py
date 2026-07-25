"""Filesystem path helpers for the LUMINA runtime manager."""
from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward until backend/ and frontend/ are found."""
    current = (start or Path(__file__).resolve()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / "backend").is_dir() and (candidate / "frontend").is_dir():
            return candidate
    # launcher/lumina -> launcher -> repo
    fallback = Path(__file__).resolve().parents[2]
    if (fallback / "backend").is_dir() and (fallback / "frontend").is_dir():
        return fallback
    raise FileNotFoundError("Could not locate the LUMINA repository root (backend/ and frontend/).")


def runtime_dir(repo_root: Path | None = None) -> Path:
    root = repo_root or find_repo_root()
    path = root / ".lumina-runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir(repo_root: Path | None = None) -> Path:
    path = runtime_dir(repo_root) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(repo_root: Path | None = None) -> Path:
    return runtime_dir(repo_root) / "runtime_state.json"


def config_path(repo_root: Path | None = None) -> Path:
    return runtime_dir(repo_root) / "config.json"


def lock_path(repo_root: Path | None = None) -> Path:
    return runtime_dir(repo_root) / "lumina.lock"
