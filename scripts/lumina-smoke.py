"""Exercise a fresh local backend with isolated credentials and storage."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def request(url: str, *, data: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(data).encode() if data is not None else None
    with urlopen(Request(url, data=payload, headers=headers), timeout=8) as response:
        return response.status, json.load(response)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lumina-smoke-") as temp:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}/api"
        env = os.environ.copy()
        env.update({
            "JWT_SECRET": "isolated-smoke-secret-32-characters-long",
            "OWNER_EMAIL": "smoke@lumina.local",
            "OWNER_PASSWORD": "isolated-smoke-password",
            "OWNER_PASSWORD_HASH": "",
            "LUMINA_LOCAL_PASSWORDLESS": "0",
            "LUMINA_DATABASE_PROVIDER": "sqlite",
            "LUMINA_SQLITE_PATH": str(Path(temp) / "smoke.db"),
            "STORAGE_BACKEND": "local",
            "STORAGE_DIR": str(Path(temp) / "storage"),
            "LUMINA_ENV": "development",
            "PYTHONPATH": str(ROOT / "backend"),
        })
        # A private process prevents accidentally testing another server on port 8000.
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT / "backend", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"Backend exited during startup ({process.returncode})")
                try:
                    status, health = request(base + "/health")
                    break
                except (URLError, TimeoutError):
                    time.sleep(0.2)
            else:
                raise RuntimeError("Backend health endpoint did not respond within 20 seconds")
            assert status == 200 and health["backend"] == "ok", health
            try:
                request(base + "/auth/me")
                raise AssertionError("Protected route accepted a request without a token")
            except HTTPError as exc:
                assert exc.code == 401, exc.code
            status, login = request(base + "/auth/login", data={
                "email": "smoke@lumina.local", "password": "isolated-smoke-password",
            })
            assert status == 200 and login.get("access_token"), login
            status, owner = request(base + "/auth/me", token=login["access_token"])
            assert status == 200 and owner["email"] == "smoke@lumina.local", owner
            print("PASS: startup, health, protected route, login, auth/me")
            return 0
        except Exception as exc:
            print(f"FAIL: local backend smoke: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        finally:
            process.terminate()
            try:
                output, _ = process.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                output, _ = process.communicate()
            if process.returncode not in (0, -15, 1) and output:
                print(output.decode(errors="replace")[-2000:], file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
