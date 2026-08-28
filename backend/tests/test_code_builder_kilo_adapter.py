from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_builder.kilo_adapter import (
    KiloAdapter,
    KiloAdapterConfiguration,
    KiloAdapterError,
    KiloExecutionError,
)


def _adapter(monkeypatch: pytest.MonkeyPatch, *, auto: bool = False) -> KiloAdapter:
    monkeypatch.setattr("shutil.which", lambda _binary: "/usr/local/bin/kilo")
    return KiloAdapter(
        KiloAdapterConfiguration(
            allow_auto_approve=auto,
            timeout_seconds=30,
            model="ollama/qwen2.5-coder:7b",
            agent="code",
        )
    )


def test_build_command_uses_json_dir_model_and_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _adapter(monkeypatch).build_command(
        prompt="Run tests and fix any failures",
        repository_root=tmp_path,
    )

    assert command[:3] == (
        "/usr/local/bin/kilo",
        "run",
        "Run tests and fix any failures",
    )
    assert "--format" in command
    assert command[command.index("--format") + 1] == "json"
    assert command[command.index("--dir") + 1] == str(tmp_path.resolve())
    assert command[command.index("--model") + 1] == "ollama/qwen2.5-coder:7b"
    assert command[command.index("--agent") + 1] == "code"
    assert "--auto" not in command


def test_auto_approval_requires_explicit_lumina_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(KiloAdapterError, match="explicit LUMINA configuration opt-in"):
        _adapter(monkeypatch, auto=False).build_command(
            prompt="Fix the repository",
            repository_root=tmp_path,
            auto_approve=True,
        )

    allowed = _adapter(monkeypatch, auto=True).build_command(
        prompt="Fix the repository",
        repository_root=tmp_path,
        auto_approve=True,
    )
    assert "--auto" in allowed


def test_attached_file_cannot_escape_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(KiloAdapterError, match="escapes the repository"):
        _adapter(monkeypatch).build_command(
            prompt="Review this file",
            repository_root=tmp_path,
            attached_files=("../outside.txt",),
        )


def test_run_parses_json_events_without_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(monkeypatch)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = tuple(command)
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=(
                json.dumps({"type": "session", "sessionID": "abc"})
                + "\n"
                + "informational line\n"
                + json.dumps({"type": "result", "status": "completed"})
                + "\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    result = adapter.run(
        prompt="Run tests and fix failures",
        repository_root=tmp_path,
    )

    assert result.successful
    assert [event["type"] for event in result.events] == ["session", "result"]
    assert captured["shell"] is False
    assert captured["stdin"] is not None
    assert captured["cwd"] == tmp_path.resolve()


def test_nonzero_exit_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(monkeypatch)

    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=2,
            stdout="",
            stderr="provider unavailable",
        ),
    )

    with pytest.raises(KiloExecutionError, match="exited with code 2"):
        adapter.run(prompt="Fix tests", repository_root=tmp_path)
