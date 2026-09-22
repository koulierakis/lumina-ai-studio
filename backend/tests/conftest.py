from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

_SERVER_PROCESS: subprocess.Popen | None = None
_SKIP_SERVER_ENV = "LUMINA_SKIP_TEST_SERVER"

# Test password hash for "password123" (bcrypt, 12 rounds)
TEST_PASSWORD_HASH = "$2b$12$4kw2zFS0aLqjSbcG3kfFhO6.pVDazXgGKPYcFwd3NZJcsko52O0U2"

os.environ.setdefault("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("REACT_APP_BACKEND_URL", "http://127.0.0.1:8000")
os.environ.setdefault("OWNER_EMAIL", "owner@lumina.local")
os.environ.setdefault("OWNER_PASSWORD", "password123")
os.environ.setdefault("OWNER_PASSWORD_HASH", TEST_PASSWORD_HASH)
os.environ.setdefault("LUMINA_TEST_OWNER_PASSWORD", "password123")
os.environ.setdefault("JWT_SECRET", "test-secret-for-local-validation-only-32b")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("LUMINA_TEST_PROVIDER", "1")
os.environ.setdefault("LUMINA_LOCAL_PASSWORDLESS", "0")
os.environ.setdefault("MONGO_URL", "mongomock://localhost")
os.environ.setdefault("DB_NAME", "lumina_test")
# Hermetic document-AI defaults: isolate unit tests from any developer .env
# (e.g. a local GROQ_API_KEY / LUMINA_DOCUMENT_AI_PROVIDER=groq). load_dotenv
# uses override=False, so these values win when modules are imported later.
os.environ["LUMINA_DOCUMENT_AI_PROVIDER"] = "ollama"
os.environ["GROQ_DOCUMENT_MODEL"] = "openai/gpt-oss-120b"
os.environ["GROQ_API_KEY"] = ""
os.environ["SAMBANOVA_API_KEY"] = ""
os.environ["SAMBANOVA_BASE_URL"] = ""
os.environ["SAMBANOVA_MODEL"] = ""


def _skip_test_server() -> bool:
    return os.getenv(_SKIP_SERVER_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _port_open(host: str = "127.0.0.1", port: int = 8000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def pytest_sessionstart(session: pytest.Session) -> None:
    global _SERVER_PROCESS
    if _skip_test_server():
        return
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
    env.setdefault("LUMINA_LOCAL_PASSWORDLESS", "0")
    env.setdefault("MONGO_URL", "mongomock://localhost")
    env.setdefault("DB_NAME", "lumina_test")
    env["LUMINA_DOCUMENT_AI_PROVIDER"] = "ollama"
    env["GROQ_DOCUMENT_MODEL"] = "openai/gpt-oss-120b"
    env["GROQ_API_KEY"] = ""
    env["SAMBANOVA_API_KEY"] = ""
    env["SAMBANOVA_BASE_URL"] = ""
    env["SAMBANOVA_MODEL"] = ""
    env["PATH"] = str(repo_root / "tools" / "ffmpeg") + os.pathsep + env.get("PATH", "")
    _SERVER_PROCESS = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(backend_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if _port_open():
            return
        if _SERVER_PROCESS.poll() is not None:
            raise RuntimeError(
                "Backend test server exited before opening 127.0.0.1:8000.\n"
                    "Server output was redirected to DEVNULL to prevent pipe backpressure."
            )
        time.sleep(0.2)
    _SERVER_PROCESS.terminate()
    try:
        _SERVER_PROCESS.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _SERVER_PROCESS.kill()
        _SERVER_PROCESS.wait(timeout=5)
    raise RuntimeError(
        "Backend test server did not start on 127.0.0.1:8000 within 30 seconds.\n"
        "Server output was redirected to DEVNULL to prevent pipe backpressure."
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    global _SERVER_PROCESS
    if _skip_test_server():
        return
    if _SERVER_PROCESS and _SERVER_PROCESS.poll() is None:
        _SERVER_PROCESS.terminate()
        try:
            _SERVER_PROCESS.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _SERVER_PROCESS.kill()
            _SERVER_PROCESS.wait(timeout=5)
    _SERVER_PROCESS = None
