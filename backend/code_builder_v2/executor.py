from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from shlex import split


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
        arguments = split(command)
        completed = subprocess.run(
            arguments,
            cwd=self.repository_root,
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
