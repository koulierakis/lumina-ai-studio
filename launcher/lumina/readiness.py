"""HTTP readiness probes for backend, frontend, and Ollama."""
from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

logger = logging.getLogger("lumina.launcher.readiness")


def port_in_use(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            return sock.connect_ex((host, int(port))) == 0
        except OSError:
            return False


def http_get_json(url: str, timeout: float = 3.0) -> tuple[int, Any]:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - local URLs only
        status = int(getattr(response, "status", 200) or 200)
        body = response.read().decode("utf-8", errors="replace")
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, body


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = int(getattr(response, "status", 200) or 200)
            return 200 <= status < 500
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def check_backend(host: str, port: int, timeout: float = 3.0) -> dict[str, Any]:
    url = f"http://{host}:{port}/api/health"
    try:
        status, payload = http_get_json(url, timeout=timeout)
        ok = status == 200 and isinstance(payload, dict) and payload.get("status") in {"ok", "ready", "degraded"}
        return {"ok": ok, "url": url, "status_code": status, "payload": payload if isinstance(payload, dict) else {}}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"ok": False, "url": url, "status_code": None, "error": str(exc), "payload": {}}


def _frontend_probe_hosts(host: str) -> list[str]:
    """Return safe loopback fallbacks for local frontend readiness checks."""
    candidates = [host]
    if host == "localhost":
        candidates.append("127.0.0.1")
    elif host == "127.0.0.1":
        candidates.append("localhost")
    elif host in {"0.0.0.0", "::", "[::]"}:
        candidates.extend(["127.0.0.1", "localhost"])
    return list(dict.fromkeys(candidates))


def check_frontend(host: str, port: int, timeout: float = 3.0) -> dict[str, Any]:
    attempted_urls: list[str] = []
    for probe_host in _frontend_probe_hosts(host):
        url = f"http://{probe_host}:{port}/"
        attempted_urls.append(url)
        if http_ok(url, timeout=timeout):
            return {"ok": True, "url": url, "attempted_urls": attempted_urls}
    primary_url = attempted_urls[0] if attempted_urls else f"http://{host}:{port}/"
    return {"ok": False, "url": primary_url, "attempted_urls": attempted_urls}


def check_ollama(host: str, port: int, model: str, timeout: float = 4.0) -> dict[str, Any]:
    tags_url = f"http://{host}:{port}/api/tags"
    try:
        status, payload = http_get_json(tags_url, timeout=timeout)
        models = []
        if isinstance(payload, dict):
            models = [m.get("name") for m in payload.get("models", []) if isinstance(m, dict)]
        installed = model in models or any(str(name).startswith(f"{model}") for name in models)
        # Also accept exact match without tag variants
        if not installed:
            installed = any(str(name).split(":")[0] == model.split(":")[0] and str(name) == model for name in models)
        return {
            "ok": status == 200,
            "online": status == 200,
            "model": model,
            "installed": installed,
            "models": models,
            "url": tags_url,
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "ok": False,
            "online": False,
            "model": model,
            "installed": False,
            "models": [],
            "url": tags_url,
            "error": str(exc),
        }


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    interval: float,
    label: str,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                logger.info("%s is ready.", label)
                return True
        except Exception as exc:  # noqa: BLE001 - probe errors are expected during boot
            logger.debug("%s probe error: %s", label, exc)
        time.sleep(interval)
    logger.error("%s readiness timed out after %.0fs.", label, timeout)
    return False
