"""Safe optional Kilo Code adapter for the LUMINA Code Builder.

The adapter deliberately keeps Kilo behind LUMINA's controller instead of
letting the external agent become the source of truth. It starts Kilo only in
a caller-selected repository directory, never invokes a shell, uses JSON event
output, applies bounded timeouts, and requires explicit opt-in before enabling
Kilo's auto-approval mode.

This module is dependency-free and does not require Kilo to be installed at
import time. Callers may probe availability and decide whether to fall back to
LUMINA's native Ollama pipeline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping, Sequence


DEFAULT_KILO_BINARY: Final[str] = "kilo"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 900.0
MAX_PROMPT_CHARACTERS: Final[int] = 200_000
MAX_OUTPUT_CHARACTERS: Final[int] = 2_000_000


class KiloAdapterError(RuntimeError):
    """Base error raised by the optional Kilo integration."""


class KiloUnavailableError(KiloAdapterError):
    """Raised when the Kilo CLI cannot be located."""


class KiloExecutionError(KiloAdapterError):
    """Raised when Kilo exits unsuccessfully or returns unusable output."""


@dataclass(frozen=True, slots=True)
class KiloAdapterConfiguration:
    binary: str = DEFAULT_KILO_BINARY
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    allow_auto_approve: bool = False
    model: str | None = None
    agent: str | None = None

    def __post_init__(self) -> None:
        if not self.binary.strip():
            raise ValueError("Kilo binary must not be empty.")
        if self.timeout_seconds <= 0:
            raise ValueError("Kilo timeout must be positive.")


@dataclass(frozen=True, slots=True)
class KiloRunResult:
    command: tuple[str, ...]
    returncode: int
    events: tuple[Mapping[str, Any], ...]
    stdout: str
    stderr: str

    @property
    def successful(self) -> bool:
        return self.returncode == 0


class KiloAdapter:
    """Launch Kilo in a tightly constrained, machine-readable mode."""

    def __init__(self, configuration: KiloAdapterConfiguration | None = None) -> None:
        self.configuration = configuration or KiloAdapterConfiguration()

    def resolve_binary(self) -> str:
        configured = self.configuration.binary.strip()
        if os.path.isabs(configured):
            path = Path(configured)
            if path.is_file():
                return str(path)
            raise KiloUnavailableError(f"Kilo executable was not found: {configured}")

        resolved = shutil.which(configured)
        if not resolved:
            raise KiloUnavailableError(
                "Kilo CLI is not installed or is not available on PATH."
            )
        return resolved

    def is_available(self) -> bool:
        try:
            self.resolve_binary()
        except KiloUnavailableError:
            return False
        return True

    @staticmethod
    def _safe_repository_root(repository_root: str | os.PathLike[str]) -> Path:
        root = Path(repository_root).expanduser().resolve()
        if not root.is_dir():
            raise KiloAdapterError(f"Repository directory does not exist: {root}")
        return root

    def build_command(
        self,
        *,
        prompt: str,
        repository_root: str | os.PathLike[str],
        session_id: str | None = None,
        auto_approve: bool = False,
        attached_files: Sequence[str] = (),
    ) -> tuple[str, ...]:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise KiloAdapterError("Kilo prompt must not be empty.")
        if len(normalized_prompt) > MAX_PROMPT_CHARACTERS:
            raise KiloAdapterError("Kilo prompt exceeds the safe size limit.")

        root = self._safe_repository_root(repository_root)
        command: list[str] = [
            self.resolve_binary(),
            "run",
            normalized_prompt,
            "--format",
            "json",
            "--dir",
            str(root),
        ]

        if self.configuration.model:
            command.extend(("--model", self.configuration.model))
        if self.configuration.agent:
            command.extend(("--agent", self.configuration.agent))
        if session_id:
            command.extend(("--session", session_id))

        if auto_approve:
            if not self.configuration.allow_auto_approve:
                raise KiloAdapterError(
                    "Kilo auto-approval requires explicit LUMINA configuration opt-in."
                )
            command.append("--auto")

        for raw_file in attached_files:
            candidate = (root / raw_file).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise KiloAdapterError(
                    f"Attached file escapes the repository: {raw_file}"
                ) from exc
            if not candidate.is_file():
                raise KiloAdapterError(f"Attached file does not exist: {raw_file}")
            command.extend(("--file", str(candidate)))

        return tuple(command)

    def run(
        self,
        *,
        prompt: str,
        repository_root: str | os.PathLike[str],
        session_id: str | None = None,
        auto_approve: bool = False,
        attached_files: Sequence[str] = (),
    ) -> KiloRunResult:
        command = self.build_command(
            prompt=prompt,
            repository_root=repository_root,
            session_id=session_id,
            auto_approve=auto_approve,
            attached_files=attached_files,
        )
        root = self._safe_repository_root(repository_root)

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
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            raise KiloExecutionError(
                f"Kilo execution exceeded {self.configuration.timeout_seconds:g} seconds."
            ) from exc
        except OSError as exc:
            raise KiloExecutionError(f"Could not start Kilo: {exc}") from exc

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if len(stdout) > MAX_OUTPUT_CHARACTERS or len(stderr) > MAX_OUTPUT_CHARACTERS:
            raise KiloExecutionError("Kilo output exceeded the safe size limit.")

        events: list[Mapping[str, Any]] = []
        for line in stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                # Kilo may emit non-event informational text. Preserve stdout but
                # never interpret such text as a trusted structured event.
                continue
            if isinstance(event, Mapping):
                events.append(dict(event))

        result = KiloRunResult(
            command=command,
            returncode=completed.returncode,
            events=tuple(events),
            stdout=stdout,
            stderr=stderr,
        )
        if not result.successful:
            detail = stderr.strip() or stdout.strip() or "unknown Kilo failure"
            if len(detail) > 4000:
                detail = detail[:4000] + " [TRUNCATED]"
            raise KiloExecutionError(
                f"Kilo exited with code {completed.returncode}: {detail}"
            )
        return result
