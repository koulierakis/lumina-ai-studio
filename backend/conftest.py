"""Pytest configuration for the backend test suite.

Use a repository-local base temp directory on systems where the default OS temp
folder is unavailable, but isolate each pytest process. A fixed ``.pytest_tmp``
root is unsafe for nested pytest runs: the inner run may clean the directory that
contains the outer run's ``tmp_path`` repository, deleting its working directory
and Code Builder backups while validation is still running.
"""

from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config):
    """Redirect tmp_path to a writable, process-isolated local directory."""
    if config.option.basetemp:
        return  # respect explicit --basetemp from CLI / xdist controller
    basetemp = Path(__file__).resolve().parent / ".pytest_tmp" / str(os.getpid())
    basetemp.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(basetemp)
