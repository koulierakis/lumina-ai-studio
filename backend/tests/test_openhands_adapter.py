from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_builder.openhands_adapter import (
    OpenHandsAdapter,
    OpenHandsAdapterConfiguration,
    OpenHandsAdapterError,
)


def _adapter(tmp_path: Path) -> OpenHandsAdapter:
    fake_binary = tmp_path / "openhands"
    fake_binary.write_text("", encoding="utf-8")
    return OpenHandsAdapter(
        OpenHandsAdapterConfiguration(binary=str(fake_binary), timeout_seconds=30)
    )


def test_rejects_real_workspace_autonomous_execution(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    with pytest.raises(OpenHandsAdapterError, match="disposable workspace"):
        adapter.build_command(
            prompt="Fix the failing test",
            workspace_root=tmp_path,
            disposable_workspace=False,
        )


def test_builds_documented_headless_json_command_for_disposable_workspace(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)

    command = adapter.build_command(
        prompt="Fix the failing test",
        workspace_root=tmp_path,
        disposable_workspace=True,
    )

    assert command[1:] == (
        "--headless",
        "--json",
        "--always-approve",
        "-t",
        "Fix the failing test",
    )


def test_rejects_empty_prompt(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    with pytest.raises(OpenHandsAdapterError, match="must not be empty"):
        adapter.build_command(
            prompt="   ",
            workspace_root=tmp_path,
            disposable_workspace=True,
        )


def test_parses_json_lines_from_successful_process(monkeypatch, tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    class Completed:
        returncode = 0
        stdout = json.dumps({"type": "message", "content": "done"}) + "\n"
        stderr = ""

    monkeypatch.setattr(
        "code_builder.openhands_adapter.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )

    result = adapter.run(
        prompt="Inspect the project",
        workspace_root=tmp_path,
        disposable_workspace=True,
    )

    assert result.successful is True
    assert result.events == ({"type": "message", "content": "done"},)
