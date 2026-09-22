"""Hermetic production-acceptance E2E run (Groq Cloud mode only).

Owned backend + frontend on random/3000 ports, isolated sqlite + media,
real authentication, real Chromium through Playwright. Runs the baseline
smoke spec plus the production-acceptance matrix in one process and:

- redirects every Ollama reference to a blocked port (never contacts 127.0.0.1:11434);
- samples ``netstat`` continuously during the run to prove zero client
  connections to 127.0.0.1:11434 (the pre-existing local daemon must not be used);
- greps the backend log for server-side Tracebacks and Groq/error evidence.

Reuses the hardened helpers from run_local_e2e without changing it.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import run_local_e2e as base

ROOT = base.ROOT


def _netstat_sample() -> tuple[list[str], list[str]]:
    """Return (client-connection lines, listener lines) touching 127.0.0.1:11434."""
    try:
        output = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10, errors="replace",
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return [], []
    clients = []
    listeners = []
    for line in output.splitlines():
        if "TCP" not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        local, foreign = parts[1], parts[2]
        if "127.0.0.1:11434" not in local and "127.0.0.1:11434" not in foreign:
            continue
        if "127.0.0.1:11434" in local:
            if foreign in ("0.0.0.0:0", "*:*", "[::]:0"):
                listeners.append(line.strip())
        else:
            clients.append(line.strip())
    return clients, listeners


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required")

    specs = [
        str(spec) for spec in (os.environ.get("LUMINA_E2E_SPECS", "").split(",") if os.environ.get("LUMINA_E2E_SPECS") else ["lumina-render", "production-acceptance"])
    ]
    spec_files = []
    for spec in specs:
        spec_file = Path(spec)
        if not spec_file.suffix:
            spec_file = ROOT / "e2e" / f"{spec}.spec.js"
        if not spec_file.exists():
            raise RuntimeError(f"E2E spec does not exist: {spec_file}")
        spec_files.append(str(spec_file.relative_to(ROOT).as_posix()))

    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 3000))
        except OSError as exc:
            raise RuntimeError("Port 3000 is occupied; stop the owned frontend before this isolated run") from exc
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        backend_port = probe.getsockname()[1]

    groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        groq_api_key = base._env_file_value(ROOT / "backend" / ".env", "GROQ_API_KEY")
    if not groq_api_key:
        raise RuntimeError(
            "Acceptance E2E requires GROQ_API_KEY. Set it in the current PowerShell "
            "session without printing it, or place it in backend/.env. "
            "It is never printed by this runner."
        )
    target_groq_model = "openai/gpt-oss-120b"
    groq_model = (
        os.environ.get("LUMINA_GROQ_MODEL", "").strip()
        or base._env_file_value(ROOT / "backend" / ".env", "LUMINA_GROQ_MODEL")
        or target_groq_model
    )
    document_model = (
        os.environ.get("GROQ_DOCUMENT_MODEL", "").strip()
        or base._env_file_value(ROOT / "backend" / ".env", "GROQ_DOCUMENT_MODEL")
        or target_groq_model
    )

    temp = ROOT / "test_reports" / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    run_dir = temp / ("production-audit-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    run_dir.mkdir()
    backend_url = f"http://127.0.0.1:{backend_port}"
    base_url = "http://127.0.0.1:3000"
    password = secrets.token_urlsafe(24)
    email = "e2e@lumina.local"
    bypass_ollama_url = "http://127.0.0.1:9"

    env = os.environ.copy()
    env.update({
        "OWNER_EMAIL": email,
        "OWNER_PASSWORD": "",
        "OWNER_PASSWORD_HASH": base.bcrypt.hashpw(password.encode(), base.bcrypt.gensalt()).decode(),
        "JWT_SECRET": secrets.token_urlsafe(48),
        "LUMINA_ENV": "development",
        "LUMINA_LOCAL_PASSWORDLESS": "0",
        "LUMINA_DATABASE_PROVIDER": "sqlite",
        "LUMINA_SQLITE_PATH": str(run_dir / "lumina.db"),
        "LUMINA_ADVISOR_STATE_DIR": str(run_dir / "advisor"),
        "STORAGE_BACKEND": "local", "STORAGE_DIR": str(run_dir / "media"),
        "OPENAI_API_KEY": "",
        "REACT_APP_LOCAL_DEV_AUTH": "false", "REACT_APP_BACKEND_URL": backend_url,
        "LUMINA_BACKEND_PROXY": backend_url, "BROWSER": "none", "HOST": "127.0.0.1", "PORT": "3000",
        "LUMINA_E2E_EMAIL": email, "LUMINA_E2E_PASSWORD": password,
        "LUMINA_E2E_BASE_URL": base_url,
        "LUMINA_E2E_API_URL": backend_url + "/api",
        "LUMINA_E2E_ISOLATED": "1",
        "LUMINA_E2E_OUTPUT_DIR": str(run_dir / "artifacts"),
        "LUMINA_E2E_HTML_DIR": str(run_dir / "html"),
        "CORS_ORIGINS": base_url, "TRUSTED_HOSTS": "localhost,127.0.0.1",
    })
    for key in ("OLLAMA_HOST", "OLLAMA_DOCUMENT_MODEL", "OLLAMA_STRUCTURED_DOCUMENT_MODEL",
                "LUMINA_ADVISOR_MODEL", "LUMINA_DISABLE_LOGIN_LIMITER", "LUMINA_E2E_TOKEN"):
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

    servers = []
    logs = []
    summary = {
        "base_url": base_url, "backend_url": backend_url,
        "spec_files": spec_files, "provider": "groq", "model": groq_model,
        "ollama_blocked_url": bypass_ollama_url,
        "auth": "isolated test account; passwordless disabled",
        "result": "FAIL",
    }
    started = time.monotonic()
    monitor_stop = threading.Event()
    client_samples = []
    listener_samples = []
    monitor_lines = []

    def monitor():
        while not monitor_stop.is_set():
            try:
                clients, listeners = _netstat_sample()
                if clients:
                    client_samples.extend(clients)
                if listeners:
                    listener_samples.extend(listeners)
                monitor_lines.append(
                    f"{datetime.now().isoformat(timespec='seconds')} "
                    f"clients_to_11434={len(clients)} listeners_on_11434={len(listeners)}"
                )
            except Exception:
                pass
            monitor_stop.wait(0.5)

    try:
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        for name, command, cwd, ready_url in (
            ("backend", [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(backend_port)], ROOT / "backend", backend_url + "/api/health"),
            ("frontend", [node, str(ROOT / "frontend/node_modules/@craco/craco/dist/bin/craco.js"), "start"], ROOT / "frontend", base_url + "/login"),
        ):
            log = (run_dir / f"{name}.log").open("wb")
            logs.append(log)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT)
            servers.append(process)
            base.wait_ready(ready_url, process)
            summary[name + "_pid"] = process.pid
            print(f"{name} ready (PID {process.pid})", flush=True)

        # Bolt the Ollama listener identity down: expected pre-existing daemon only.
        listeners_at_start = [line for line in listener_samples]
        print("Running specs:", ", ".join(spec_files), flush=True)
        print("Evidence:", run_dir.relative_to(ROOT), flush=True)
        with (run_dir / "playwright.log").open("w", encoding="utf-8") as output:
            command = [node, str(ROOT / "node_modules/@playwright/test/cli.js"), "test", *spec_files, "--workers=1", "--reporter=list"]
            grep = os.environ.get("LUMINA_E2E_GREP", "").strip()
            if grep:
                command.extend(["--grep", grep])
            test = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace")
            try:
                for line in test.stdout:
                    safe = line.replace(password, "[REDACTED]").replace(email, "[REDACTED]")
                    output.write(safe)
                    print(safe, end="", flush=True)
                code = test.wait()
            finally:
                if test.poll() is None:
                    base.stop_owned(test)
        summary["playwright_exit_code"] = code
        summary["servers_alive_after_tests"] = all(p.poll() is None for p in servers)

        with (run_dir / "ollama-monitor.txt").open("w", encoding="utf-8") as log:
            log.write("netstat samples during the acceptance run\n")
            log.write("clients_to_11434 lines (should be empty):\n")
            log.writelines((line + "\n") for line in client_samples)
            log.write("listener lines (pre-existing daemon only):\n")
            for line in sorted(set(listener_samples)):
                log.write(line + "\n")
            log.write("continuous sample trail:\n")
            log.writelines((line + "\n") for line in monitor_lines)
        summary["ollama_11434_client_connections"] = len(client_samples)
        summary["ollama_11434_listener_samples"] = len(listener_samples)

        backend_log_text = (run_dir / "backend.log").read_text(encoding="utf-8", errors="replace")
        with (run_dir / "backend-evidence-grep.txt").open("w", encoding="utf-8") as log:
            log.write("Traceback/ERROR lines (redacted):\n")
            for line in backend_log_text.splitlines():
                if "Traceback" in line or ("ERROR" in line and "Traceback" not in line):
                    safe = line.replace(password, "[REDACTED]").replace(email, "[REDACTED]")
                    log.write(safe + "\n")
            log.write("\nGroq endpoint calls counted:\n")
            log.write(f"api.groq.com references: {backend_log_text.count('api.groq.com')}\n")
            log.write(f"11434 references: {backend_log_text.count('11434')}\n")
        summary["groq_requests_logged"] = backend_log_text.count("api.groq.com")
        summary["ollama_11434_refs_in_backend_log"] = backend_log_text.count("11434")

        checks = []
        for _ in range(2):
            with urllib.request.urlopen(urllib.request.Request(base_url + "/login", headers={"Accept": "text/html"}), timeout=5) as response:
                checks.append(response.status)
            time.sleep(1)
        summary["frontend_post_run_http"] = checks
        summary["result"] = "PASS" if code == 0 and summary["servers_alive_after_tests"] else "FAIL"
        return 0 if summary["result"] == "PASS" else 1
    finally:
        summary["elapsed_seconds"] = round(time.monotonic() - started, 1)
        monitor_stop.set()
        for process in reversed(servers):
            base.stop_owned(process)
        summary["owned_servers_stopped"] = all(p.poll() is not None for p in servers)
        for log in logs:
            log.close()
        (run_dir / "run-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print("Final acceptance E2E result:", summary["result"], flush=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as error:
        print("Acceptance E2E setup failed:", str(error), file=sys.stderr)
        raise SystemExit(1)