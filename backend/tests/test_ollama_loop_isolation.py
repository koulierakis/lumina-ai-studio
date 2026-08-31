"""Regression tests for the Code Builder "Event loop is closed" failure.

Production pattern: one ``OllamaService`` instance is shared by every Code
Builder task, while each planning request runs on a dedicated worker thread
with a fresh event loop (``asyncio.run``). A single eagerly-created
``httpx.AsyncClient`` binds its connection pool to the first loop that uses
it; the next request on a new loop then fails with ``RuntimeError: Event loop
is closed``.

These tests drive real HTTP requests against a local stub Ollama server and
require consecutive/concurrent fresh event loops to succeed, which is exactly
the sequence that used to fail.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from code_builder.ollama_service import (
    OllamaClientConfiguration,
    OllamaService,
)
from code_builder.planning_service import (
    PlanningConfiguration,
    PlanningService,
)

PRIMARY_MODEL = "qwen2.5-coder:1.5b"
FALLBACK_MODEL = "qwen2.5-coder:7b"
USER_REQUEST = "Please change FLAG from False to True in app.py."


def _valid_payload() -> dict[str, Any]:
    """A minimal plan payload accepted by ``CompactGeneratedChangePlan``."""

    return {
        "title": "Enable feature flag",
        "summary": "Change the existing feature flag from false to true.",
        "objective": (
            "Apply the requested behavior without changing unrelated files."
        ),
        "files": [
            {
                "path": "app.py",
                "operation": "modify",
                "summary": "Enable the existing feature flag.",
                "rationale": "The user explicitly requested the flag change.",
            }
        ],
        "steps": [
            {
                "order": 1,
                "title": "Update flag",
                "description": "Change FLAG from False to True in app.py.",
                "file_paths": ["app.py"],
            }
        ],
        "acceptance_criteria": ["app.py contains FLAG = True and compiles."],
        "test_plan": ["python -m py_compile app.py"],
    }


class _StubOllamaHandler(BaseHTTPRequestHandler):
    """Tiny Ollama-compatible HTTP stub (``/api/generate`` + ``/api/tags``)."""

    def log_message(self, *args: Any) -> None:  # keep test output quiet
        return

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path == "/api/tags":
            self._send_json(
                {
                    "models": [
                        {"name": PRIMARY_MODEL},
                        {"name": FALLBACK_MODEL},
                    ]
                }
            )
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        if self.path == "/api/generate":
            self._send_json(
                {
                    "response": json.dumps(_valid_payload()),
                    "done": True,
                    "done_reason": "stop",
                    "created_at": "2026-01-01T00:00:00.000000Z",
                }
            )
            return
        self.send_response(404)
        self.end_headers()


@pytest.fixture()
def stub_ollama_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubOllamaHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("FLAG = False\n", encoding="utf-8")
    return tmp_path


class _StubAnalysis:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self.repository_name = repository_root.name
        self.analysis_id = "analysis-1"
        self.files: list[Any] = []


def _planning_service(base_url: str) -> PlanningService:
    return PlanningService(
        ollama_service=OllamaService(
            configuration=OllamaClientConfiguration(base_url=base_url)
        ),
        configuration=PlanningConfiguration(timeout_seconds=10.0),
    )


def _plan(service: PlanningService, analysis: _StubAnalysis) -> Any:
    # One fresh event loop per planning request — the production pattern.
    return asyncio.run(
        service.plan(
            user_request=USER_REQUEST,
            analysis=analysis,
            return_normalized=True,
        )
    )


def test_consecutive_planning_requests_on_fresh_event_loops(
    stub_ollama_url: str,
    repository: Path,
) -> None:
    """Two consecutive planning requests (two fresh loops) must both succeed.

    With the previous eagerly-created shared ``httpx.AsyncClient`` the second
    ``asyncio.run`` failed with ``RuntimeError: Event loop is closed``.
    """

    service = _planning_service(stub_ollama_url)

    first = _plan(service, _StubAnalysis(repository))
    second = _plan(service, _StubAnalysis(repository))

    assert first.title == "Enable feature flag"
    assert second.title == "Enable feature flag"
    # One isolated client per event loop proves the pools are not shared.
    assert service.ollama_service.loop_client_count == 2


def test_generate_across_consecutive_event_loops(stub_ollama_url: str) -> None:
    service = OllamaService(
        configuration=OllamaClientConfiguration(base_url=stub_ollama_url)
    )

    first = asyncio.run(
        service.generate(model=PRIMARY_MODEL, prompt="first request")
    )
    second = asyncio.run(
        service.generate(model=PRIMARY_MODEL, prompt="second request")
    )

    assert first.content == json.dumps(_valid_payload())
    assert second.content == json.dumps(_valid_payload())
    assert service.loop_client_count == 2

    asyncio.run(service.close())
    assert service.is_closed


def test_concurrent_worker_threads_are_isolated(stub_ollama_url: str) -> None:
    """Simultaneous worker-thread loops must not share a client."""

    service = OllamaService(
        configuration=OllamaClientConfiguration(base_url=stub_ollama_url)
    )
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            result = asyncio.run(
                service.generate(model=PRIMARY_MODEL, prompt="threaded")
            )
            assert result.content == json.dumps(_valid_payload())
        except BaseException as exc:  # noqa: BLE001 - collected for assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert service.loop_client_count == 4

    asyncio.run(service.close())
    assert service.is_closed


def test_injected_client_is_reused_across_loops(stub_ollama_url: str) -> None:
    """An explicitly injected client stays the caller's responsibility."""

    injected = httpx.AsyncClient(base_url=stub_ollama_url)
    service = OllamaService(
        configuration=OllamaClientConfiguration(base_url=stub_ollama_url),
        client=injected,
    )

    asyncio.run(service.generate(model=PRIMARY_MODEL, prompt="one"))
    asyncio.run(service.generate(model=PRIMARY_MODEL, prompt="two"))

    assert service.loop_client_count == 0

    asyncio.run(service.close())
    assert service.is_closed
    assert injected.is_closed


def test_close_tolerates_clients_from_finished_event_loops(
    stub_ollama_url: str,
) -> None:
    """Shutdown must never fail because a planning worker loop already ended."""

    service = OllamaService(
        configuration=OllamaClientConfiguration(base_url=stub_ollama_url)
    )

    asyncio.run(service.generate(model=PRIMARY_MODEL, prompt="bye"))

    # The client above is bound to a loop that is now closed. Closing the
    # service from a different loop must not raise.
    asyncio.run(service.close())

    assert service.is_closed
    assert service.loop_client_count == 0
