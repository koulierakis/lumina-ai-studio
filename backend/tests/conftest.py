from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


_SERVER_PROCESS: subprocess.Popen | None = None

os.environ.setdefault("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("REACT_APP_BACKEND_URL", "http://127.0.0.1:8000")
os.environ.setdefault("OWNER_EMAIL", "owner@lumina.local")
os.environ.setdefault("OWNER_PASSWORD", "password123")
os.environ.setdefault("LUMINA_TEST_OWNER_PASSWORD", "password123")
os.environ.setdefault("JWT_SECRET", "test-secret-for-local-validation-only-32b")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("LUMINA_TEST_PROVIDER", "1")
os.environ.setdefault("MONGO_URL", "mongomock://localhost")
os.environ.setdefault("DB_NAME", "lumina_test")


def _port_open(host: str = "127.0.0.1", port: int = 8000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def pytest_sessionstart(session: pytest.Session) -> None:
    global _SERVER_PROCESS
    if _port_open():
        return
    backend_dir = Path(__file__).resolve().parents[1]
    repo_root = backend_dir.parent
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(backend_dir))
    env.setdefault("REACT_APP_BACKEND_URL", "http://127.0.0.1:8000")
    env.setdefault("OWNER_EMAIL", "owner@lumina.local")
    env.setdefault("OWNER_PASSWORD", "password123")
    env.setdefault("LUMINA_TEST_OWNER_PASSWORD", "password123")
    env.setdefault("JWT_SECRET", "test-secret-for-local-validation-only-32b")
    env.setdefault("GEMINI_API_KEY", "test-key")
    env.setdefault("LUMINA_TEST_PROVIDER", "1")
    env.setdefault("MONGO_URL", "mongomock://localhost")
    env.setdefault("DB_NAME", "lumina_test")
    env["PATH"] = str(repo_root / "tools" / "ffmpeg") + os.pathsep + env.get("PATH", "")
    _SERVER_PROCESS = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(backend_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if _port_open():
            return
        if _SERVER_PROCESS.poll() is not None:
            output = _SERVER_PROCESS.stdout.read() if _SERVER_PROCESS.stdout else ""
            raise RuntimeError(
                "Backend test server exited before opening 127.0.0.1:8000.\n"
                f"Server output:\n{output[-12000:]}"
            )
        time.sleep(0.2)
    _SERVER_PROCESS.terminate()
    try:
        _SERVER_PROCESS.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _SERVER_PROCESS.kill()
        _SERVER_PROCESS.wait(timeout=5)
    output = _SERVER_PROCESS.stdout.read() if _SERVER_PROCESS.stdout else ""
    raise RuntimeError(
        "Backend test server did not start on 127.0.0.1:8000 within 30 seconds.\n"
        f"Server output:\n{output[-12000:]}"
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    global _SERVER_PROCESS
    if _SERVER_PROCESS and _SERVER_PROCESS.poll() is None:
        _SERVER_PROCESS.terminate()
        try:
            _SERVER_PROCESS.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _SERVER_PROCESS.kill()
            _SERVER_PROCESS.wait(timeout=5)
    _SERVER_PROCESS = None
