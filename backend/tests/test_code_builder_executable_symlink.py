from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from code_builder.build_service import resolve_executable


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink regression")
def test_resolve_executable_preserves_path_symlink(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    executable_link = bin_dir / "python"
    executable_link.symlink_to(Path(sys.executable))

    resolved = resolve_executable(
        "python",
        repository_root=repository_root,
        search_environment={"PATH": str(bin_dir)},
    )

    assert resolved == executable_link.absolute()
    assert resolved.is_symlink()
