"""Pytest configuration for the backend test suite.

Sets a basetemp directory outside the repository to avoid Windows permission
errors when the default system temp directory (``%LOCALAPPDATA%\\Temp\\pytest-of-<user>``)
is not accessible.

CRITICAL: the basetemp must live OUTSIDE the repository tree. Code Builder
tests spawn a subprocess ``python -m pytest`` inside ``tmp_path``; if ``tmp_path``
is nested under the repo, that subprocess inherits the repo's ``pytest.ini``
(which enables xdist via ``addopts = -n --dist loadscope``), breaking the
isolated test workspace and corrupting rollback verification.
"""

from __future__ import annotations

from pathlib import Path
import tempfile


def pytest_configure(config):
    """Redirect the ``tmp_path`` basetemp to a writable dir outside the repo."""
    if config.option.basetemp:
        return  # respect explicit --basetemp from CLI
    basetemp = Path(tempfile.gettempdir()) / "lumina-pytest"
    basetemp.mkdir(exist_ok=True)
    config.option.basetemp = str(basetemp)