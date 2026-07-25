"""Atomic runtime state persistence."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import find_repo_root, state_path

logger = logging.getLogger("lumina.launcher.state")

EMPTY_STATE: dict[str, Any] = {
    "version": 1,
    "started_at": None,
    "updated_at": None,
    "browser_opened": False,
    "owned_ollama": False,
    "services": {
        "backend": {"pid": None, "pgid": None, "command": None, "started_at": None},
        "frontend": {"pid": None, "pgid": None, "command": None, "started_at": None},
        "ollama": {"pid": None, "pgid": None, "command": None, "started_at": None},
    },
    "warnings": [],
}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".state_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
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


def load_state(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    path = state_path(root)
    if not path.exists():
        return deepcopy(EMPTY_STATE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("state is not an object")
        state = deepcopy(EMPTY_STATE)
        state.update({k: v for k, v in raw.items() if k in EMPTY_STATE or k in {"version", "started_at", "updated_at", "browser_opened", "owned_ollama", "services", "warnings"}})
        services = deepcopy(EMPTY_STATE["services"])
        raw_services = raw.get("services") if isinstance(raw.get("services"), dict) else {}
        for name in services:
            item = raw_services.get(name) if isinstance(raw_services.get(name), dict) else {}
            services[name] = {**services[name], **{k: item.get(k) for k in services[name]}}
        state["services"] = services
        return state
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Corrupt runtime state (%s); resetting.", exc)
        return deepcopy(EMPTY_STATE)


def save_state(state: dict[str, Any], repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    payload = deepcopy(state)
    payload["updated_at"] = time.time()
    _atomic_write(state_path(root), payload)
    return payload


def clear_state(repo_root: Path | None = None) -> None:
    root = repo_root or find_repo_root()
    save_state(deepcopy(EMPTY_STATE), root)
