from pathlib import Path
from unittest.mock import patch

import pytest
from code_builder_v2.executor import CommandExecutor
from code_builder_v2.security import UnsafePathError, normalize_relative_path, resolve_inside


def test_normalize_relative_path_accepts_windows_separators():
    assert normalize_relative_path(r"src\feature\app.py") == "src/feature/app.py"


@pytest.mark.parametrize(
    "value",
    ["", "../outside.py", "src/../outside.py", "/etc/passwd", r"C:\temp\bad.py"],
)
def test_normalize_relative_path_rejects_unsafe_values(value: str):
    with pytest.raises(UnsafePathError):
        normalize_relative_path(value)


def test_resolve_inside_returns_path_under_repository(tmp_path: Path):
    resolved = resolve_inside(tmp_path, "src/app.py")

    assert resolved == (tmp_path / "src" / "app.py").resolve()


def test_resolve_inside_rejects_repository_root(tmp_path: Path):
    with pytest.raises(UnsafePathError):
        resolve_inside(tmp_path, ".")


def test_command_executor_disables_shell_interpretation(tmp_path: Path):
    completed = type("Completed", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
    with patch("code_builder_v2.executor.subprocess.run", return_value=completed) as run:
        result = CommandExecutor(tmp_path).run("pytest -q & echo injected", timeout_seconds=5)

    assert result.returncode == 0
    run.assert_called_once()
    assert run.call_args.args[0] == ["pytest", "-q", "&", "echo", "injected"]
    assert run.call_args.kwargs.get("shell") is None
