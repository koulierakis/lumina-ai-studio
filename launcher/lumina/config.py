"""Validated local runtime configuration for LUMINA."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import config_path, find_repo_root

logger = logging.getLogger("lumina.launcher.config")

DEFAULTS: dict[str, Any] = {
    "dashboard_auto_open": True,
    "preferred_ollama_model": "qwen2.5-coder:7b",
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
    "remote_access": False,
}

ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class ConfigError(ValueError):
    """Raised when a runtime setting is invalid."""


def _coerce_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"Invalid boolean for '{name}'.")


def _coerce_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid integer for '{name}'.") from exc
    if number < minimum or number > maximum:
        raise ConfigError(f"'{name}' must be between {minimum} and {maximum}.")
    return number


def _coerce_host(value: Any, name: str) -> str:
    host = str(value or "").strip()
    if not host or any(ch.isspace() for ch in host) or "/" in host or "\\" in host:
        raise ConfigError(f"Invalid host for '{name}'.")
    return host


def _coerce_model(value: Any) -> str:
    model = str(value or "").strip()
    if not model or len(model) > 120 or any(ch in model for ch in "\n\r\t"):
        raise ConfigError("Invalid preferred_ollama_model.")
    return model


def validate_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize a config mapping. Missing keys use defaults."""
    data = deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return data

    merged = {**data, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    result = {
        "dashboard_auto_open": _coerce_bool(merged["dashboard_auto_open"], "dashboard_auto_open"),
        "preferred_ollama_model": _coerce_model(merged["preferred_ollama_model"]),
        "backend_host": _coerce_host(merged["backend_host"], "backend_host"),
        "backend_port": _coerce_int(merged["backend_port"], "backend_port", 1, 65535),
        "frontend_host": _coerce_host(merged["frontend_host"], "frontend_host"),
        "frontend_port": _coerce_int(merged["frontend_port"], "frontend_port", 1, 65535),
        "ollama_host": _coerce_host(merged["ollama_host"], "ollama_host"),
        "ollama_port": _coerce_int(merged["ollama_port"], "ollama_port", 1, 65535),
        "startup_timeout_seconds": _coerce_int(
            merged["startup_timeout_seconds"], "startup_timeout_seconds", 30, 900
        ),
        "readiness_poll_interval_seconds": float(merged["readiness_poll_interval_seconds"]),
        "automatic_ollama_startup": _coerce_bool(
            merged["automatic_ollama_startup"], "automatic_ollama_startup"
        ),
        "logging_level": str(merged["logging_level"]).upper(),
        "open_browser_once": _coerce_bool(merged["open_browser_once"], "open_browser_once"),
        "remote_access": _coerce_bool(merged["remote_access"], "remote_access"),
    }
    if result["remote_access"]:
        # Bind the web app to all local interfaces. Internet exposure is still
        # intentionally NOT configured here; use a private VPN such as Tailscale.
        result["backend_host"] = "0.0.0.0"
        result["frontend_host"] = "0.0.0.0"
    if result["logging_level"] not in ALLOWED_LOG_LEVELS:
        raise ConfigError("logging_level must be DEBUG, INFO, WARNING, or ERROR.")
    interval = result["readiness_poll_interval_seconds"]
    if not isinstance(interval, (int, float)) or interval < 0.2 or interval > 30:
        raise ConfigError("readiness_poll_interval_seconds must be between 0.2 and 30.")
    result["readiness_poll_interval_seconds"] = float(interval)
    return result


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".cfg_", suffix=".tmp", dir=str(path.parent))
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


def load_config(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    path = config_path(root)
    if not path.exists():
        cfg = deepcopy(DEFAULTS)
        atomic_write_json(path, cfg)
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return validate_config(raw)
    except (OSError, json.JSONDecodeError, ConfigError) as exc:
        logger.warning("Invalid runtime config at %s (%s); using defaults.", path, exc)
        cfg = deepcopy(DEFAULTS)
        try:
            atomic_write_json(path, cfg)
        except OSError:
            logger.exception("Could not rewrite invalid config file.")
        return cfg


def save_config(updates: dict[str, Any], repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    current = load_config(root)
    merged = {**current, **{k: v for k, v in updates.items() if k in DEFAULTS}}
    validated = validate_config(merged)
    atomic_write_json(config_path(root), validated)
    return validated
