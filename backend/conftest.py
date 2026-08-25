"""Pytest configuration for the backend test suite.

Sets a repository-local basetemp directory to avoid Windows permission
errors when the default system temp directory (``%LOCALAPPDATA%\\Temp\\pytest-of-<user>``)
is not accessible.
"""

from __future__ import annotations

from pathlib import Path


def pytest_configure(config):
    """Redirect the ``tmp_path`` basetemp to a writable repo-local directory."""
    if config.option.basetemp:
        return  # respect explicit --basetemp from CLI
    basetemp = Path(__file__).resolve().parent / ".pytest_tmp"
    basetemp.mkdir(exist_ok=True)
    config.option.basetemp = str(basetemp)