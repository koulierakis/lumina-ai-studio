"""Environment doctor checks for LUMINA."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_config
from .detect import detect_node, detect_npm, detect_ollama, detect_project_paths, detect_python
from .paths import find_repo_root, runtime_dir
from .readiness import check_ollama, port_in_use


def run_doctor(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or find_repo_root()
    cfg = load_config(root)
    checks: list[dict[str, Any]] = []

    py = detect_python()
    checks.append({"name": "python", "ok": py["ok"], "detail": py.get("version") or py.get("detail")})

    node = detect_node()
    checks.append({"name": "node", "ok": node["ok"], "detail": node.get("version") or node.get("detail")})

    npm = detect_npm()
    checks.append({"name": "npm", "ok": npm["ok"], "detail": npm.get("version") or npm.get("detail")})

    ollama = detect_ollama()
    checks.append({"name": "ollama_binary", "ok": ollama["ok"], "detail": ollama.get("version") or ollama.get("detail")})

    ollama_api = check_ollama(cfg["ollama_host"], cfg["ollama_port"], cfg["preferred_ollama_model"])
    checks.append(
        {
            "name": "ollama_api",
            "ok": bool(ollama_api.get("online")),
            "detail": "online" if ollama_api.get("online") else ollama_api.get("error") or "offline",
        }
    )
    checks.append(
        {
            "name": "coding_model",
            "ok": bool(ollama_api.get("installed")),
            "detail": cfg["preferred_ollama_model"]
            if ollama_api.get("installed")
            else f"Missing model {cfg['preferred_ollama_model']}",
        }
    )

    paths = detect_project_paths(root)
    checks.append(
        {
            "name": "project_paths",
            "ok": paths["ok"],
            "detail": "ok" if paths["ok"] else f"Missing: {', '.join(paths['missing'])}",
        }
    )

    rt = runtime_dir(root)
    checks.append({"name": "runtime_dir", "ok": rt.is_dir(), "detail": str(rt)})

    backend_busy = port_in_use(
        "127.0.0.1" if cfg["backend_host"] in {"0.0.0.0", "localhost"} else cfg["backend_host"],
        cfg["backend_port"],
    )
    frontend_busy = port_in_use(
        "127.0.0.1" if cfg["frontend_host"] in {"0.0.0.0", "localhost"} else cfg["frontend_host"],
        cfg["frontend_port"],
    )
    checks.append(
        {
            "name": "backend_port",
            "ok": True,
            "detail": f"{cfg['backend_port']} {'in use' if backend_busy else 'free'}",
        }
    )
    checks.append(
        {
            "name": "frontend_port",
            "ok": True,
            "detail": f"{cfg['frontend_port']} {'in use' if frontend_busy else 'free'}",
        }
    )

    required = {"python", "node", "npm", "project_paths", "runtime_dir"}
    failed = [c["name"] for c in checks if c["name"] in required and not c["ok"]]
    return {
        "ok": not failed,
        "repo_root": str(root),
        "checks": checks,
        "failed": failed,
        "config": {
            "backend_port": cfg["backend_port"],
            "frontend_port": cfg["frontend_port"],
            "preferred_ollama_model": cfg["preferred_ollama_model"],
            "startup_timeout_seconds": cfg["startup_timeout_seconds"],
        },
    }
