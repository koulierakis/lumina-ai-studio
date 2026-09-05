from pathlib import Path

import pytest

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
