from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class CommandExecutor:
    repository_root: Path

    def run(self, command: str, timeout_seconds: int) -> CommandResult:
        completed = subprocess.run(
            command,
            cwd=self.repository_root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
