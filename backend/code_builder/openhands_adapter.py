"""Safe optional OpenHands adapter for the LUMINA Code Builder.

OpenHands is treated as an execution engine, never as LUMINA's policy boundary.
The adapter intentionally permits autonomous execution only inside an explicitly
declared disposable workspace. This preserves LUMINA's approval/backup/rollback
layer while we evaluate OpenHands in parallel with the native Code Builder.

The integration uses OpenHands' documented headless JSON CLI contract. It is
optional: importing LUMINA does not require OpenHands to be installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping


DEFAULT_OPENHANDS_BINARY: Final[str] = "openhands"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 1800.0
MAX_PROMPT_CHARACTERS: Final[int] = 200_000
MAX_OUTPUT_CHARACTERS: Final[int] = 4_000_000
_SAFE_ENVIRONMENT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
    }
)


class OpenHandsAdapterError(RuntimeError):
    """Base error raised by the optional OpenHands integration."""


class OpenHandsUnavailableError(OpenHandsAdapterError):
    """Raised when the OpenHands executable cannot be located."""


class OpenHandsExecutionError(OpenHandsAdapterError):
    """Raised when OpenHands exits unsuccessfully or returns unsafe output."""


@dataclass(frozen=True, slots=True)
class OpenHandsAdapterConfiguration:
    binary: str = DEFAULT_OPENHANDS_BINARY
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    environment: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.binary.strip():
            raise ValueError("OpenHands binary must not be empty.")
        if self.timeout_seconds <= 0:
            raise ValueError("OpenHands timeout must be positive.")


@dataclass(frozen=True, slots=True)
class OpenHandsRunResult:
    command: tuple[str, ...]
    returncode: int
    events: tuple[Mapping[str, Any], ...]
    stdout: str
    stderr: str

    @property
    def successful(self) -> bool:
        return self.returncode == 0


class OpenHandsAdapter:
    """Launch OpenHands in documented headless JSON mode."""

    def __init__(
        self, configuration: OpenHandsAdapterConfiguration | None = None
    ) -> None:
        self.configuration = configuration or OpenHandsAdapterConfiguration()

    def resolve_binary(self) -> str:
        configured = self.configuration.binary.strip()
        if os.path.isabs(configured):
            path = Path(configured)
            if path.is_file():
                return str(path)
            raise OpenHandsUnavailableError(
                f"OpenHands executable was not found: {configured}"
            )

        resolved = shutil.which(configured)
        if not resolved:
            raise OpenHandsUnavailableError(
                "OpenHands is not installed or is not available on PATH."
            )
        return resolved

    def is_available(self) -> bool:
        try:
            self.resolve_binary()
        except OpenHandsUnavailableError:
            return False
        return True

    @staticmethod
    def _safe_workspace_root(workspace_root: str | os.PathLike[str]) -> Path:
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            raise OpenHandsAdapterError(f"Workspace directory does not exist: {root}")
        return root

    def _safe_environment(self) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in _SAFE_ENVIRONMENT_KEYS
        }
        for key, value in (self.configuration.environment or {}).items():
            normalized_key = str(key).strip()
            if not normalized_key:
                raise OpenHandsAdapterError(
                    "OpenHands environment variable name must not be empty."
                )
            environment[normalized_key] = str(value)
        return environment

    def build_command(
        self,
        *,
        prompt: str,
        workspace_root: str | os.PathLike[str],
        disposable_workspace: bool = False,
    ) -> tuple[str, ...]:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise OpenHandsAdapterError("OpenHands prompt must not be empty.")
        if len(normalized_prompt) > MAX_PROMPT_CHARACTERS:
            raise OpenHandsAdapterError("OpenHands prompt exceeds the safe size limit.")
        self._safe_workspace_root(workspace_root)

        # Headless agents can edit files and execute commands. LUMINA must never
        # point this mode at the real repository before its approval boundary.
        if not disposable_workspace:
            raise OpenHandsAdapterError(
                "OpenHands autonomous execution is allowed only inside a disposable "
                "workspace. Clone/copy the repository first, then review its diff "
                "through LUMINA before applying changes."
            )

        return (
            self.resolve_binary(),
            "--headless",
            "--json",
            "--always-approve",
            "-t",
            normalized_prompt,
        )

    def run(
        self,
        *,
        prompt: str,
        workspace_root: str | os.PathLike[str],
        disposable_workspace: bool = False,
    ) -> OpenHandsRunResult:
        root = self._safe_workspace_root(workspace_root)
        command = self.build_command(
            prompt=prompt,
            workspace_root=root,
            disposable_workspace=disposable_workspace,
        )

        try:
            completed = subprocess.run(
                command,
                cwd=root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.configuration.timeout_seconds,
                check=False,
                shell=False,
                env=self._safe_environment(),
            )
        except subprocess.TimeoutExpired as exc:
            raise OpenHandsExecutionError(
                f"OpenHands execution exceeded {self.configuration.timeout_seconds:g} seconds."
            ) from exc
        except OSError as exc:
            raise OpenHandsExecutionError(f"Could not start OpenHands: {exc}") from exc

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if len(stdout) > MAX_OUTPUT_CHARACTERS or len(stderr) > MAX_OUTPUT_CHARACTERS:
            raise OpenHandsExecutionError("OpenHands output exceeded the safe size limit.")

        events: list[Mapping[str, Any]] = []
        for line in stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(event, Mapping):
                events.append(dict(event))

        result = OpenHandsRunResult(
            command=command,
            returncode=completed.returncode,
            events=tuple(events),
            stdout=stdout,
            stderr=stderr,
        )
        if not result.successful:
            detail = stderr.strip() or stdout.strip() or "unknown OpenHands failure"
            if len(detail) > 4000:
                detail = detail[:4000] + " [TRUNCATED]"
            raise OpenHandsExecutionError(
                f"OpenHands exited with code {completed.returncode}: {detail}"
            )
        return result
