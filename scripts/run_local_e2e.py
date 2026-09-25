"""Run real local browser workflows with owned servers and isolated test data.

No saved credentials are changed. Credentials generated here exist only for this
local test backend. Provider modes:

- ``LUMINA_E2E_PROVIDER=ollama`` (default): the local model must already be installed.
- ``LUMINA_E2E_PROVIDER=groq``: Groq Cloud is required (GROQ_API_KEY from the caller
  environment or ``backend/.env``); the runner never starts or depends on Ollama and
  redirects every Ollama endpoint to a blocked local port.
- ``LUMINA_E2E_PROVIDER=sambanova``: the cloud provider is required and the runner
  never starts or depends on Ollama.

Server output goes to files, never an inherited terminal pipe. All child servers
are monitored through the test run and stopped by PID when the runner exits.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]


def get_json(url: str, timeout: float = 5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def wait_ready(url: str, process: subprocess.Popen, seconds: float = 120) -> None:
    deadline = time.monotonic() + seconds
    last_error = "not responding"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server PID {process.pid} exited with code {process.returncode}; inspect its log")
        try:
            request = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError as error:
            last_error = f"HTTP {error.code}"
        except (OSError, urllib.error.URLError) as error:
            last_error = type(error).__name__
        time.sleep(0.5)
    raise RuntimeError(f"Server readiness timed out: {url} ({last_error})")


def stop_owned(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _env_file_value(path: Path, name: str) -> str:
    """Read one ``KEY=value`` line from an env file without printing its contents."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if separator and key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required")
    # Never reuse or kill an unrelated listener.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 3000))
        except OSError as exc:
            raise RuntimeError("Port 3000 is occupied; stop the owned frontend before this isolated run") from exc
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        backend_port = probe.getsockname()[1]

    ollama = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    provider_mode = os.environ.get("LUMINA_E2E_PROVIDER", "ollama").strip().casefold()
    model = os.environ.get("LUMINA_E2E_MODEL", "qwen2.5-coder:1.5b")
    # No Ollama endpoint may be reachable in cloud modes: all references are pointed
    # at a deliberately closed local port so a running local Ollama is never called.
    bypass_ollama_url = "http://127.0.0.1:9"
    target_groq_model = "openai/gpt-oss-120b"
    groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if provider_mode == "groq":
        if not groq_api_key:
            groq_api_key = _env_file_value(ROOT / "backend" / ".env", "GROQ_API_KEY")
        if not groq_api_key:
            raise RuntimeError(
                "Groq E2E requires GROQ_API_KEY. Set it in the current PowerShell "
                "session without printing it, or place it in backend/.env. "
                "It is never printed by this runner."
            )
        groq_model = (
            os.environ.get("LUMINA_GROQ_MODEL", "").strip()
            or _env_file_value(ROOT / "backend" / ".env", "LUMINA_GROQ_MODEL")
            or target_groq_model
        )
        document_model = (
            os.environ.get("GROQ_DOCUMENT_MODEL", "").strip()
            or _env_file_value(ROOT / "backend" / ".env", "GROQ_DOCUMENT_MODEL")
            or target_groq_model
        )
    elif provider_mode == "sambanova":
        if not os.environ.get("SAMBANOVA_API_KEY", "").strip():
            raise RuntimeError(
                "SambaNova E2E requires SAMBANOVA_API_KEY. Set it in the current PowerShell "
                "session without printing it (see the run instructions), then set "
                "SAMBANOVA_BASE_URL=https://api.sambanova.ai/v1 and "
                "SAMBANOVA_MODEL=Qwen2.5-Coder-32B-Instruct."
            )
        if not os.environ.get("SAMBANOVA_BASE_URL", "").strip():
            raise RuntimeError(
                "SambaNova E2E requires SAMBANOVA_BASE_URL "
                "(required value: https://api.sambanova.ai/v1)."
            )
    else:
        models = get_json(ollama + "/api/tags").get("models", [])
        if model not in {item.get("name") for item in models}:
            raise RuntimeError(f"Required local Ollama model is not installed: {model}")

    temp = ROOT / "test_reports" / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    run_dir = temp / ("local-e2e-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    run_dir.mkdir()
    backend_url = f"http://127.0.0.1:{backend_port}"
    base_url = "http://127.0.0.1:3000"
    password = secrets.token_urlsafe(24)
    email = "e2e@lumina.local"
    env = os.environ.copy()
    env.update({
        "OWNER_EMAIL": email,
        "OWNER_PASSWORD": "",
        "OWNER_PASSWORD_HASH": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "JWT_SECRET": secrets.token_urlsafe(48),
        "LUMINA_ENV": "development",
        "LUMINA_LOCAL_PASSWORDLESS": "0",
        "LUMINA_DATABASE_PROVIDER": "sqlite",
        "LUMINA_SQLITE_PATH": str(run_dir / "lumina.db"),
        "LUMINA_ADVISOR_STATE_DIR": str(run_dir / "advisor"),
        "LUMINA_MIND_STATE_DIR": str(run_dir / "mind"),
        "STORAGE_BACKEND": "local", "STORAGE_DIR": str(run_dir / "media"),
        "OPENAI_API_KEY": "", "GROQ_API_KEY": "",
        "REACT_APP_LOCAL_DEV_AUTH": "false", "REACT_APP_BACKEND_URL": backend_url,
        "LUMINA_BACKEND_PROXY": backend_url, "BROWSER": "none", "HOST": "127.0.0.1", "PORT": "3000",
        "LUMINA_MIND_BASE_URL": backend_url,
        "LUMINA_E2E_EMAIL": email, "LUMINA_E2E_PASSWORD": password,
        "LUMINA_E2E_BASE_URL": base_url,
        "LUMINA_E2E_API_URL": backend_url + "/api",
        "LUMINA_E2E_ISOLATED": "1",
        "LUMINA_E2E_OUTPUT_DIR": str(run_dir / "artifacts"),
        "LUMINA_E2E_HTML_DIR": str(run_dir / "html"),
        "CORS_ORIGINS": base_url, "TRUSTED_HOSTS": "localhost,127.0.0.1",
    })
    if provider_mode == "groq":
        for key in ("OLLAMA_HOST", "OLLAMA_DOCUMENT_MODEL", "OLLAMA_STRUCTURED_DOCUMENT_MODEL",
                    "LUMINA_ADVISOR_MODEL"):
            env.pop(key, None)
        env["OLLAMA_URL"] = bypass_ollama_url
        env["GROQ_API_KEY"] = groq_api_key
        env["GROQ_API_URL"] = (
            os.environ.get("GROQ_API_URL", "").strip()
            or "https://api.groq.com/openai/v1/chat/completions"
        )
        env["LUMINA_GROQ_MODEL"] = groq_model
        env["GROQ_DOCUMENT_MODEL"] = document_model
        env["LUMINA_DOCUMENT_AI_PROVIDER"] = "groq"
        env["LUMINA_E2E_MIND_PROVIDER"] = "groq"
        env["LUMINA_E2E_MODEL"] = groq_model
    elif provider_mode == "sambanova":
        for key in ("OLLAMA_URL", "OLLAMA_HOST", "LUMINA_ADVISOR_MODEL", "OLLAMA_DOCUMENT_MODEL",
                    "OLLAMA_STRUCTURED_DOCUMENT_MODEL", "LUMINA_E2E_MIND_PROVIDER"):
            env.pop(key, None)
        env["OLLAMA_URL"] = bypass_ollama_url
        env["LUMINA_DOCUMENT_AI_PROVIDER"] = "sambanova"
        env["LUMINA_E2E_MIND_PROVIDER"] = "sambanova"
        # SAMBANOVA_API_KEY / SAMBANOVA_BASE_URL / SAMBANOVA_MODEL inherited from the caller.
    else:
        env.update({
            "OLLAMA_URL": ollama, "LUMINA_ADVISOR_MODEL": model,
            "LUMINA_DOCUMENT_AI_PROVIDER": "ollama",
            "OLLAMA_DOCUMENT_MODEL": model, "OLLAMA_STRUCTURED_DOCUMENT_MODEL": model,
            "LUMINA_E2E_MIND_PROVIDER": "local",
        })
    # Preserve normal authentication throttling, regardless of the caller's shell.
    for key in ("LUMINA_DISABLE_LOGIN_LIMITER", "LUMINA_E2E_TOKEN", "RENDER", "RENDER_SERVICE_ID"):
        env.pop(key, None)

    servers = []
    logs = []
    snapshot_model = (
        os.environ.get("SAMBANOVA_MODEL", "Qwen2.5-Coder-32B-Instruct")
        if provider_mode == "sambanova"
        else groq_model if provider_mode == "groq" else model
    )
    summary = {"base_url": base_url, "backend_url": backend_url, "provider": provider_mode,
               "model": snapshot_model, "mind_provider": provider_mode,
               "ollama_blocked_url": bypass_ollama_url,
               "auth": "isolated test account; passwordless disabled", "result": "FAIL"}
    started = time.monotonic()
    try:
        for name, command, cwd, ready_url in (
            ("backend", [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(backend_port)], ROOT / "backend", backend_url + "/api/health"),
            ("frontend", [node, str(ROOT / "frontend/node_modules/@craco/craco/dist/bin/craco.js"), "start"], ROOT / "frontend", base_url + "/login"),
        ):
            log = (run_dir / f"{name}.log").open("wb")
            logs.append(log)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT)
            servers.append(process)
            wait_ready(ready_url, process)
            summary[name + "_pid"] = process.pid
            print(f"{name} ready (PID {process.pid})", flush=True)

        with urllib.request.urlopen(urllib.request.Request(base_url + "/login", headers={"Accept": "text/html"}), timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("Frontend readiness failed")
        try:
            get_json(backend_url + "/api/auth/me")
            raise RuntimeError("Test backend unexpectedly permits passwordless access")
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise

        label = (
            "Groq Cloud" if provider_mode == "groq"
            else "SambaNova Cloud" if provider_mode == "sambanova"
            else "local Ollama"
        )
        print(f"Running all five workflows with real authentication and {label}.", flush=True)
        print("Evidence:", run_dir.relative_to(ROOT), flush=True)
        with (run_dir / "playwright.log").open("w", encoding="utf-8") as output:
            test = subprocess.Popen([node, str(ROOT / "node_modules/@playwright/test/cli.js"), "test", "e2e/lumina-render.spec.js", "e2e/mind-orchestration.spec.js", "--workers=1", "--reporter=list"],
                                    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace")
            try:
                for line in test.stdout:
                    # Do not let an assertion expose a test credential.
                    safe = line.replace(password, "[REDACTED]").replace(email, "[REDACTED]")
                    output.write(safe)
                    print(safe, end="", flush=True)
                code = test.wait()
            finally:
                if test.poll() is None:
                    stop_owned(test)

        summary["servers_alive_after_tests"] = all(p.poll() is None for p in servers)
        checks = []
        for _ in range(3):
            with urllib.request.urlopen(urllib.request.Request(base_url + "/login", headers={"Accept": "text/html"}), timeout=5) as response:
                checks.append(response.status)
            time.sleep(1)
        summary["frontend_post_run_http"] = checks
        summary["result"] = "PASS" if code == 0 and summary["servers_alive_after_tests"] else "FAIL"
        return 0 if summary["result"] == "PASS" else 1
    finally:
        summary["elapsed_seconds"] = round(time.monotonic() - started, 1)
        for process in reversed(servers):
            stop_owned(process)
        summary["owned_servers_stopped"] = all(p.poll() is not None for p in servers)
        for log in logs:
            log.close()
        (run_dir / "run-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print("Final local E2E result:", summary["result"], flush=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print("Local E2E setup failed:", str(error), file=sys.stderr)
        raise SystemExit(1)
