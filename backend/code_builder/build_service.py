from __future__ import annotations

import enum
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import models as domain_models
from . import patch_service
from . import repository_service
from . import security


IS_WINDOWS: Final[bool] = os.name == "nt"

DEFAULT_COMMAND_TIMEOUT_SECONDS: Final[float] = 900.0
DEFAULT_MAX_LOG_BYTES: Final[int] = 2 * 1024 * 1024
DEFAULT_STREAM_CHUNK_SIZE: Final[int] = 8192
DEFAULT_TERMINATION_GRACE_SECONDS: Final[float] = 5.0
DEFAULT_MAX_COMMANDS: Final[int] = 100
DEFAULT_MAX_ARGUMENTS: Final[int] = 256
DEFAULT_MAX_ARGUMENT_LENGTH: Final[int] = 8192
DEFAULT_MAX_ENVIRONMENT_VARIABLES: Final[int] = 64
DEFAULT_MAX_ENVIRONMENT_VALUE_LENGTH: Final[int] = 16_384

SENSITIVE_ENVIRONMENT_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    (
        SECRET
        |TOKEN
        |PASSWORD
        |PASSWD
        |API[_-]?KEY
        |PRIVATE[_-]?KEY
        |ACCESS[_-]?KEY
        |AUTH
        |CREDENTIAL
        |SESSION
        |COOKIE
        |SIGNING
        |ENCRYPTION
        |DATABASE[_-]?URL
        |CONNECTION[_-]?STRING
        |CLIENT[_-]?SECRET
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

SECRET_ASSIGNMENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    (?P<prefix>
        (?:
            api[_-]?key
            |secret
            |token
            |password
            |passwd
            |authorization
            |client[_-]?secret
            |access[_-]?key
            |private[_-]?key
        )
        \s*
        (?:
            =|:
        )
        \s*
    )
    (?P<value>
        ["']?
        [^\s,"';]+
        ["']?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

BEARER_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"
)

URL_CREDENTIAL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)"
    r"(?P<username>[^:/@\s]+)"
    r":"
    r"(?P<password>[^/@\s]+)"
    r"@",
    re.IGNORECASE,
)

FORBIDDEN_CONTROL_CHARACTER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
)

WINDOWS_DRIVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z]:[\\/]"
)

ENVIRONMENT_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)

PACKAGE_SCRIPT_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}$"
)

PYTHON_MODULE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*$"
)

SAFE_CUSTOM_ARGUMENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[^\x00-\x1f\x7f]*$"
)

CommandEnvironment: TypeAlias = Mapping[str, str] | None


class BuildServiceError(RuntimeError):
    """Base exception for all build-service failures."""


class BuildConfigurationError(BuildServiceError):
    """Raised when the build service is configured incorrectly."""


class BuildValidationError(BuildServiceError):
    """Raised when a command or execution request fails validation."""


class BuildSecurityError(BuildValidationError):
    """Raised when a command violates a security restriction."""


class BuildTimeoutError(BuildServiceError):
    """Raised when a process exceeds its configured timeout."""

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float,
        command_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.command_id = command_id


class BuildCancellationError(BuildServiceError):
    """Raised when execution is cancelled."""

    def __init__(
        self,
        message: str = "Build execution was cancelled.",
        *,
        command_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.command_id = command_id


class BuildExecutableNotFoundError(BuildServiceError):
    """Raised when an approved executable cannot be located."""

    def __init__(
        self,
        executable: str,
        *,
        searched_paths: Sequence[str] | None = None,
    ) -> None:
        message = f"Approved executable was not found: {executable!r}."
        if searched_paths:
            message += f" Search paths: {', '.join(searched_paths)}"
        super().__init__(message)
        self.executable = executable
        self.searched_paths = tuple(searched_paths or ())


class BuildExecutionError(BuildServiceError):
    """Raised when process startup or process execution fails."""

    def __init__(
        self,
        message: str,
        *,
        command_id: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.command_id = command_id
        self.exit_code = exit_code


class BuildResultMappingError(BuildServiceError):
    """Raised when structured results cannot be mapped to domain models."""


class BuildStatus(str, enum.Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    READY = "ready"
    DRY_RUN = "dry_run"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    ERROR = "error"


class BuildCommandKind(str, enum.Enum):
    PYTHON_COMPILE = "python_compile"
    PYTEST = "pytest"
    UNITTEST = "unittest"
    RUFF = "ruff"
    MYPY = "mypy"
    FRONTEND_TEST = "frontend_test"
    FRONTEND_BUILD = "frontend_build"
    TYPESCRIPT = "typescript"
    NPM = "npm"
    NPX = "npx"
    YARN = "yarn"
    PNPM = "pnpm"
    CUSTOM = "custom"


class PackageManager(str, enum.Enum):
    NPM = "npm"
    YARN = "yarn"
    PNPM = "pnpm"


class LogStream(str, enum.Enum):
    STDOUT = "stdout"
    STDERR = "stderr"


class BuildCommandSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    command_id: str = Field(min_length=1, max_length=128)
    kind: BuildCommandKind
    executable: str | None = Field(default=None, max_length=4096)
    arguments: tuple[str, ...] = Field(default_factory=tuple)
    working_directory: str = "."
    timeout_seconds: float = Field(
        default=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        gt=0.0,
        le=86_400.0,
    )
    environment: dict[str, str] = Field(default_factory=dict)
    allowed_exit_codes: frozenset[int] = Field(
        default_factory=lambda: frozenset({0})
    )
    continue_on_failure: bool = False
    description: str | None = Field(default=None, max_length=1024)

    @field_validator("command_id")
    @classmethod
    def validate_command_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
            raise ValueError(
                "command_id must start with an alphanumeric character and "
                "contain only letters, digits, underscores, periods, colons "
                "or hyphens."
            )
        return value

    @field_validator("executable")
    @classmethod
    def validate_executable_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        _reject_control_characters(value, field_name="executable")

        stripped = value.strip()
        if not stripped:
            raise ValueError("executable cannot be empty.")

        return stripped

    @field_validator("arguments")
    @classmethod
    def validate_arguments_shape(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > DEFAULT_MAX_ARGUMENTS:
            raise ValueError(
                f"A command cannot contain more than "
                f"{DEFAULT_MAX_ARGUMENTS} arguments."
            )

        normalized: list[str] = []
        for index, argument in enumerate(value):
            if not isinstance(argument, str):
                raise TypeError(f"Argument {index} must be a string.")

            if len(argument) > DEFAULT_MAX_ARGUMENT_LENGTH:
                raise ValueError(
                    f"Argument {index} exceeds the maximum length of "
                    f"{DEFAULT_MAX_ARGUMENT_LENGTH} characters."
                )

            _reject_control_characters(
                argument,
                field_name=f"arguments[{index}]",
                allow_tab=False,
                allow_newline=False,
            )
            normalized.append(argument)

        return tuple(normalized)

    @field_validator("working_directory")
    @classmethod
    def validate_working_directory_text(cls, value: str) -> str:
        _reject_control_characters(
            value,
            field_name="working_directory",
            allow_tab=False,
            allow_newline=False,
        )
        if not value.strip():
            raise ValueError("working_directory cannot be empty.")
        return value.strip()

    @field_validator("environment")
    @classmethod
    def validate_environment_shape(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        if len(value) > DEFAULT_MAX_ENVIRONMENT_VARIABLES:
            raise ValueError(
                "Too many environment variables were provided. "
                f"Maximum: {DEFAULT_MAX_ENVIRONMENT_VARIABLES}."
            )

        normalized: dict[str, str] = {}
        for raw_name, raw_value in value.items():
            if not ENVIRONMENT_NAME_PATTERN.fullmatch(raw_name):
                raise ValueError(
                    f"Invalid environment variable name: {raw_name!r}."
                )

            if len(raw_value) > DEFAULT_MAX_ENVIRONMENT_VALUE_LENGTH:
                raise ValueError(
                    f"Environment variable {raw_name!r} exceeds the "
                    "maximum allowed value length."
                )

            _reject_control_characters(
                raw_value,
                field_name=f"environment[{raw_name!r}]",
                allow_tab=True,
                allow_newline=False,
            )
            normalized[raw_name.upper() if IS_WINDOWS else raw_name] = raw_value

        return normalized

    @field_validator("allowed_exit_codes")
    @classmethod
    def validate_allowed_exit_codes(
        cls,
        value: frozenset[int],
    ) -> frozenset[int]:
        if not value:
            raise ValueError("allowed_exit_codes cannot be empty.")

        for exit_code in value:
            if exit_code < -2_147_483_648 or exit_code > 2_147_483_647:
                raise ValueError(
                    f"Invalid exit code in allowed_exit_codes: {exit_code}."
                )

        return value

    @model_validator(mode="after")
    def validate_kind_and_executable(self) -> BuildCommandSpec:
        if self.kind is BuildCommandKind.CUSTOM and not self.executable:
            raise ValueError(
                "Custom commands must explicitly specify an executable."
            )

        return self


class BuildExecutionOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
    )

    dry_run: bool = False
    stop_on_first_failure: bool = True
    max_log_bytes_per_stream: int = Field(
        default=DEFAULT_MAX_LOG_BYTES,
        ge=4096,
        le=128 * 1024 * 1024,
    )
    termination_grace_seconds: float = Field(
        default=DEFAULT_TERMINATION_GRACE_SECONDS,
        ge=0.1,
        le=60.0,
    )
    stream_chunk_size: int = Field(
        default=DEFAULT_STREAM_CHUNK_SIZE,
        ge=256,
        le=1024 * 1024,
    )
    redact_logs: bool = True


class BuildCommandResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
    )

    command_id: str
    kind: BuildCommandKind
    status: BuildStatus
    executable: str
    arguments: tuple[str, ...]
    working_directory: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_seconds: float = Field(ge=0.0)
    started_at_epoch: float | None = None
    finished_at_epoch: float | None = None
    timed_out: bool = False
    cancelled: bool = False
    dry_run: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    error_type: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status in {
            BuildStatus.SUCCEEDED,
            BuildStatus.DRY_RUN,
        }


class BuildSequenceResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
    )

    status: BuildStatus
    commands: tuple[BuildCommandResult, ...]
    duration_seconds: float = Field(ge=0.0)
    started_at_epoch: float
    finished_at_epoch: float
    dry_run: bool = False
    stopped_early: bool = False
    cancelled: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status in {
            BuildStatus.SUCCEEDED,
            BuildStatus.DRY_RUN,
        }


class CustomCommandPolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    executable_names: frozenset[str] = Field(default_factory=frozenset)
    executable_paths: frozenset[str] = Field(default_factory=frozenset)
    allowed_argument_prefixes: tuple[str, ...] = Field(default_factory=tuple)
    forbidden_arguments: frozenset[str] = Field(default_factory=frozenset)
    allow_repository_file_arguments: bool = True

    @field_validator("executable_names")
    @classmethod
    def normalize_executable_names(
        cls,
        value: frozenset[str],
    ) -> frozenset[str]:
        normalized: set[str] = set()

        for name in value:
            _reject_control_characters(
                name,
                field_name="executable_names",
                allow_tab=False,
                allow_newline=False,
            )

            clean_name = name.strip()
            if not clean_name:
                raise ValueError("Custom executable names cannot be empty.")

            if "/" in clean_name or "\\" in clean_name:
                raise ValueError(
                    "Custom executable_names must contain names only, "
                    "not paths."
                )

            normalized.add(clean_name.casefold() if IS_WINDOWS else clean_name)

        return frozenset(normalized)

    @field_validator("executable_paths")
    @classmethod
    def normalize_executable_paths(
        cls,
        value: frozenset[str],
    ) -> frozenset[str]:
        normalized: set[str] = set()

        for path_text in value:
            _reject_control_characters(
                path_text,
                field_name="executable_paths",
                allow_tab=False,
                allow_newline=False,
            )

            path = Path(path_text).expanduser()
            if not path.is_absolute():
                raise ValueError(
                    "Every custom executable path must be absolute."
                )

            normalized_path = os.path.normcase(
                os.path.normpath(str(path.resolve(strict=False)))
            )
            normalized.add(normalized_path)

        return frozenset(normalized)


class BuildServiceConfiguration(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    repository_root: Path
    allowed_environment_variables: frozenset[str] = Field(
        default_factory=lambda: frozenset(
            {
                "CI",
                "NODE_ENV",
                "PYTHONPATH",
                "PYTHONUTF8",
                "PYTHONIOENCODING",
                "FORCE_COLOR",
                "NO_COLOR",
                "TERM",
                "TZ",
                "LANG",
                "LC_ALL",
                "VITE_MODE",
                "REACT_APP_ENV",
                "NEXT_TELEMETRY_DISABLED",
            }
        )
    )
    inherited_environment_variables: frozenset[str] = Field(
        default_factory=lambda: frozenset(
            {
                "PATH",
                "PATHEXT",
                "SYSTEMROOT",
                "WINDIR",
                "COMSPEC",
                "TEMP",
                "TMP",
                "LOCALAPPDATA",
                "APPDATA",
                "PROGRAMFILES",
                "PROGRAMFILES(X86)",
                "PROGRAMW6432",
                "USERPROFILE",
                "HOMEDRIVE",
                "HOMEPATH",
                "NUMBER_OF_PROCESSORS",
                "PROCESSOR_ARCHITECTURE",
                "PROCESSOR_IDENTIFIER",
                "PROCESSOR_LEVEL",
                "PROCESSOR_REVISION",
            }
        )
    )
    custom_command_policy: CustomCommandPolicy = Field(
        default_factory=CustomCommandPolicy
    )
    default_timeout_seconds: float = Field(
        default=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        gt=0.0,
        le=86_400.0,
    )
    max_commands_per_sequence: int = Field(
        default=DEFAULT_MAX_COMMANDS,
        ge=1,
        le=1000,
    )

    @field_validator("repository_root")
    @classmethod
    def normalize_repository_root(cls, value: Path) -> Path:
        expanded = value.expanduser()

        try:
            resolved = expanded.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValueError(
                f"Repository root does not exist: {expanded}"
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"Repository root could not be resolved: {expanded}"
            ) from exc

        if not resolved.is_dir():
            raise ValueError(
                f"Repository root is not a directory: {resolved}"
            )

        return resolved

    @field_validator(
        "allowed_environment_variables",
        "inherited_environment_variables",
    )
    @classmethod
    def normalize_environment_allowlist(
        cls,
        value: frozenset[str],
    ) -> frozenset[str]:
        normalized: set[str] = set()

        for variable_name in value:
            if not ENVIRONMENT_NAME_PATTERN.fullmatch(variable_name):
                raise ValueError(
                    f"Invalid environment variable in allowlist: "
                    f"{variable_name!r}."
                )
            normalized.add(
                variable_name.upper() if IS_WINDOWS else variable_name
            )

        return frozenset(normalized)


@dataclass(frozen=True, slots=True)
class ResolvedCommand:
    command_id: str
    kind: BuildCommandKind
    executable: Path
    arguments: tuple[str, ...]
    working_directory: Path
    environment: dict[str, str]
    timeout_seconds: float
    allowed_exit_codes: frozenset[int]
    continue_on_failure: bool
    description: str | None = None

    @property
    def argv(self) -> list[str]:
        return [str(self.executable), *self.arguments]

    @property
    def display_argv(self) -> tuple[str, ...]:
        return (str(self.executable), *self.arguments)


@dataclass(slots=True)
class BoundedTextBuffer:
    max_bytes: int
    encoding: str = "utf-8"
    _parts: list[str] = field(default_factory=list, init=False)
    _stored_bytes: int = field(default=0, init=False)
    _discarded_bytes: int = field(default=0, init=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def append(self, text: str) -> None:
        if not text:
            return

        encoded = text.encode(self.encoding, errors="replace")

        with self._lock:
            remaining = self.max_bytes - self._stored_bytes

            if remaining <= 0:
                self._discarded_bytes += len(encoded)
                return

            if len(encoded) <= remaining:
                self._parts.append(text)
                self._stored_bytes += len(encoded)
                return

            accepted = encoded[:remaining]
            safe_text = accepted.decode(self.encoding, errors="ignore")
            accepted_size = len(
                safe_text.encode(self.encoding, errors="replace")
            )

            if safe_text:
                self._parts.append(safe_text)
                self._stored_bytes += accepted_size

            self._discarded_bytes += len(encoded) - accepted_size

    def getvalue(self) -> str:
        with self._lock:
            return "".join(self._parts)

    @property
    def truncated(self) -> bool:
        with self._lock:
            return self._discarded_bytes > 0

    @property
    def discarded_bytes(self) -> int:
        with self._lock:
            return self._discarded_bytes


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason_lock = threading.Lock()
        self._reason: str | None = None

    def cancel(self, reason: str | None = None) -> None:
        with self._reason_lock:
            if reason and not self._reason:
                self._reason = reason
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(
        self,
        *,
        command_id: str | None = None,
    ) -> None:
        if self.is_cancelled():
            reason = self.reason or "Build execution was cancelled."
            raise BuildCancellationError(
                reason,
                command_id=command_id,
            )

    @property
    def reason(self) -> str | None:
        with self._reason_lock:
            return self._reason


class ProcessRegistry:
    """Tracks active subprocesses and supports cancellation by command ID."""

    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    def register(
        self,
        command_id: str,
        process: subprocess.Popen[str],
    ) -> None:
        with self._lock:
            if command_id in self._processes:
                raise BuildExecutionError(
                    f"A process is already registered for command "
                    f"{command_id!r}.",
                    command_id=command_id,
                )
            self._processes[command_id] = process

    def unregister(
        self,
        command_id: str,
        process: subprocess.Popen[str] | None = None,
    ) -> None:
        with self._lock:
            registered = self._processes.get(command_id)
            if registered is None:
                return
            if process is not None and registered is not process:
                return
            self._processes.pop(command_id, None)

    def get(
        self,
        command_id: str,
    ) -> subprocess.Popen[str] | None:
        with self._lock:
            return self._processes.get(command_id)

    def snapshot(self) -> dict[str, subprocess.Popen[str]]:
        with self._lock:
            return dict(self._processes)


def _reject_control_characters(
    value: str,
    *,
    field_name: str,
    allow_tab: bool = False,
    allow_newline: bool = False,
) -> None:
    for character in value:
        code_point = ord(character)

        if character == "\t" and allow_tab:
            continue

        if character in {"\r", "\n"} and allow_newline:
            continue

        if (
            code_point < 32
            or code_point == 127
        ):
            raise ValueError(
                f"{field_name} contains a forbidden control character "
                f"U+{code_point:04X}."
            )


def _normalize_case(value: str) -> str:
    return value.casefold() if IS_WINDOWS else value


def _normalized_path_key(path: Path) -> str:
    resolved = path.resolve(strict=False)
    return os.path.normcase(os.path.normpath(str(resolved)))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def normalize_repository_path(
    repository_root: Path,
    path_value: str | os.PathLike[str],
    *,
    must_exist: bool = False,
    require_directory: bool = False,
    require_file: bool = False,
) -> Path:
    """
    Resolve a path and guarantee that it remains inside repository_root.

    Absolute paths are accepted only when they resolve inside the repository.
    Relative paths are resolved against repository_root.
    """
    root = repository_root.expanduser().resolve(strict=True)
    raw_text = os.fspath(path_value)

    if not raw_text:
        raise BuildValidationError("Repository path cannot be empty.")

    try:
        _reject_control_characters(
            raw_text,
            field_name="repository path",
            allow_tab=False,
            allow_newline=False,
        )
    except ValueError as exc:
        raise BuildValidationError(str(exc)) from exc

    normalized_text = raw_text.replace("\\", os.sep).replace("/", os.sep)
    candidate = Path(normalized_text).expanduser()

    if not candidate.is_absolute():
        candidate = root / candidate

    try:
        resolved = candidate.resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise BuildValidationError(
            f"Repository path does not exist: {candidate}"
        ) from exc
    except OSError as exc:
        raise BuildValidationError(
            f"Repository path could not be resolved: {candidate}"
        ) from exc

    if not _is_relative_to(resolved, root):
        raise BuildSecurityError(
            f"Path escapes the repository root: {raw_text!r}."
        )

    if require_directory and resolved.exists() and not resolved.is_dir():
        raise BuildValidationError(
            f"Expected a directory path, received: {resolved}"
        )

    if require_file and resolved.exists() and not resolved.is_file():
        raise BuildValidationError(
            f"Expected a file path, received: {resolved}"
        )

    return resolved


def redact_sensitive_text(
    text: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    if not text:
        return text

    redacted = SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        text,
    )
    redacted = BEARER_TOKEN_PATTERN.sub(r"\1[REDACTED]", redacted)
    redacted = URL_CREDENTIAL_PATTERN.sub(
        lambda match: (
            f"{match.group('scheme')}"
            f"{match.group('username')}:[REDACTED]@"
        ),
        redacted,
    )

    if environment:
        secret_values = {
            value
            for name, value in environment.items()
            if value
            and len(value) >= 4
            and SENSITIVE_ENVIRONMENT_NAME_PATTERN.search(name)
        }

        for secret_value in sorted(secret_values, key=len, reverse=True):
            redacted = redacted.replace(secret_value, "[REDACTED]")

    return redacted


def sanitize_environment_for_display(
    environment: Mapping[str, str],
) -> dict[str, str]:
    sanitized: dict[str, str] = {}

    for name, value in environment.items():
        if SENSITIVE_ENVIRONMENT_NAME_PATTERN.search(name):
            sanitized[name] = "[REDACTED]"
        else:
            sanitized[name] = redact_sensitive_text(value)

    return sanitized


def build_safe_environment(
    configuration: BuildServiceConfiguration,
    command_environment: CommandEnvironment = None,
) -> dict[str, str]:
    inherited_allowlist = configuration.inherited_environment_variables
    override_allowlist = configuration.allowed_environment_variables

    safe_environment: dict[str, str] = {}

    for original_name, original_value in os.environ.items():
        normalized_name = (
            original_name.upper() if IS_WINDOWS else original_name
        )

        if normalized_name in inherited_allowlist:
            safe_environment[normalized_name] = original_value

    required_utf8_values = {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    for name, value in required_utf8_values.items():
        safe_environment[name] = value

    if command_environment:
        if len(command_environment) > DEFAULT_MAX_ENVIRONMENT_VARIABLES:
            raise BuildValidationError(
                "Too many command environment variables were provided."
            )

        for original_name, original_value in command_environment.items():
            normalized_name = (
                original_name.upper() if IS_WINDOWS else original_name
            )

            if not ENVIRONMENT_NAME_PATTERN.fullmatch(original_name):
                raise BuildValidationError(
                    f"Invalid environment variable name: "
                    f"{original_name!r}."
                )

            if normalized_name not in override_allowlist:
                raise BuildSecurityError(
                    f"Environment variable {original_name!r} is not "
                    "included in the safe allowlist."
                )

            if SENSITIVE_ENVIRONMENT_NAME_PATTERN.search(normalized_name):
                raise BuildSecurityError(
                    f"Sensitive environment variable {original_name!r} "
                    "cannot be supplied to build commands."
                )

            if not isinstance(original_value, str):
                raise BuildValidationError(
                    f"Environment variable {original_name!r} must have "
                    "a string value."
                )

            if len(original_value) > DEFAULT_MAX_ENVIRONMENT_VALUE_LENGTH:
                raise BuildValidationError(
                    f"Environment variable {original_name!r} exceeds "
                    "the maximum allowed length."
                )

            try:
                _reject_control_characters(
                    original_value,
                    field_name=f"environment[{original_name!r}]",
                    allow_tab=True,
                    allow_newline=False,
                )
            except ValueError as exc:
                raise BuildValidationError(str(exc)) from exc

            safe_environment[normalized_name] = original_value

    return safe_environment


def _windows_executable_extensions() -> tuple[str, ...]:
    if not IS_WINDOWS:
        return ("",)

    raw_extensions = os.environ.get(
        "PATHEXT",
        ".COM;.EXE;.BAT;.CMD",
    )
    extensions: list[str] = []

    for raw_extension in raw_extensions.split(os.pathsep):
        extension = raw_extension.strip()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = f".{extension}"
        extensions.append(extension.lower())

    for required_extension in (".exe", ".cmd", ".bat", ".com"):
        if required_extension not in extensions:
            extensions.append(required_extension)

    return tuple(extensions)


def _candidate_executable_names(executable: str) -> tuple[str, ...]:
    path = Path(executable)
    suffix = path.suffix.lower()

    if not IS_WINDOWS:
        return (executable,)

    extensions = _windows_executable_extensions()

    if suffix in extensions:
        return (executable,)

    return tuple(f"{executable}{extension}" for extension in extensions)


def _validate_resolved_executable_file(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise BuildExecutableNotFoundError(str(path)) from exc
    except OSError as exc:
        raise BuildExecutableNotFoundError(str(path)) from exc

    if not resolved.is_file():
        raise BuildExecutableNotFoundError(str(path))

    if not IS_WINDOWS and not os.access(resolved, os.X_OK):
        raise BuildSecurityError(
            f"Executable does not have execute permission: {resolved}"
        )

    return resolved


def resolve_executable(
    executable: str,
    *,
    repository_root: Path,
    search_environment: Mapping[str, str] | None = None,
    allow_repository_executable: bool = False,
    explicitly_allowed_paths: Iterable[str] = (),
) -> Path:
    """
    Resolve an executable without invoking a shell.

    Repository-local executable files are rejected unless explicitly enabled.
    """
    if not executable or not executable.strip():
        raise BuildExecutableNotFoundError(executable)

    executable = executable.strip()

    try:
        _reject_control_characters(
            executable,
            field_name="executable",
            allow_tab=False,
            allow_newline=False,
        )
    except ValueError as exc:
        raise BuildSecurityError(str(exc)) from exc

    if any(
        character in executable
        for character in ("|", "&", ";", ">", "<", "`", "\n", "\r", "\x00")
    ):
        raise BuildSecurityError(
            f"Executable contains forbidden shell metacharacters: "
            f"{executable!r}."
        )

    repository_root = repository_root.resolve(strict=True)
    explicitly_allowed_keys = {
        os.path.normcase(os.path.normpath(path))
        for path in explicitly_allowed_paths
    }

    executable_path = Path(executable).expanduser()
    contains_separator = (
        "/" in executable
        or "\\" in executable
        or executable_path.is_absolute()
    )

    if contains_separator:
        candidate = executable_path

        if not candidate.is_absolute():
            candidate = repository_root / candidate

        resolved = _validate_resolved_executable_file(candidate)
        execution_path = candidate.absolute()

        if _is_relative_to(resolved, repository_root):
            if (
                not allow_repository_executable
                and _normalized_path_key(resolved)
                not in explicitly_allowed_keys
            ):
                raise BuildSecurityError(
                    "Execution of repository-local binaries is disabled "
                    f"for executable: {resolved}"
                )
        elif (
            _normalized_path_key(resolved)
            not in explicitly_allowed_keys
        ):
            raise BuildSecurityError(
                "Absolute executable paths must be explicitly included "
                f"in the custom-command allowlist: {resolved}"
            )

        return execution_path

    environment = dict(search_environment or os.environ)
    path_value = environment.get("PATH") or environment.get("Path") or ""

    located = shutil.which(
        executable,
        path=path_value,
    )

    if located is None and IS_WINDOWS:
        for candidate_name in _candidate_executable_names(executable):
            located = shutil.which(candidate_name, path=path_value)
            if located is not None:
                break

    if located is None:
        search_paths = tuple(
            item for item in path_value.split(os.pathsep) if item
        )
        raise BuildExecutableNotFoundError(
            executable,
            searched_paths=search_paths,
        )

    resolved = _validate_resolved_executable_file(Path(located))
    execution_path = Path(located).absolute()

    if (
        _is_relative_to(resolved, repository_root)
        and not allow_repository_executable
        and _normalized_path_key(resolved) not in explicitly_allowed_keys
    ):
        raise BuildSecurityError(
            "PATH resolved to a repository-local executable, which is "
            f"not permitted: {resolved}"
        )

    return execution_path


def _invoke_optional_security_hook(
    hook_names: Sequence[str],
    *,
    command: BuildCommandSpec,
    repository_root: Path,
) -> None:
    """
    Invoke a compatible validation hook from security.py when available.

    The hook is optional because security.py may expose one of several
    repository-specific validation interfaces.
    """
    for hook_name in hook_names:
        hook = getattr(security, hook_name, None)
        if not callable(hook):
            continue

        call_attempts = (
            {
                "command": command,
                "repository_root": repository_root,
            },
            {
                "command_spec": command,
                "repository_root": repository_root,
            },
            {
                "executable": command.executable,
                "arguments": list(command.arguments),
                "working_directory": command.working_directory,
                "repository_root": repository_root,
            },
        )

        last_type_error: TypeError | None = None

        for keyword_arguments in call_attempts:
            try:
                result = hook(**keyword_arguments)
            except TypeError as exc:
                last_type_error = exc
                continue
            except Exception as exc:
                raise BuildSecurityError(
                    f"security.{hook_name} rejected command "
                    f"{command.command_id!r}: {exc}"
                ) from exc

            if result is False:
                raise BuildSecurityError(
                    f"security.{hook_name} rejected command "
                    f"{command.command_id!r}."
                )

            return

        if last_type_error is not None:
            continue


def _reject_shell_metacharacters(
    argument: str,
    *,
    argument_index: int,
) -> None:
    forbidden_characters = {
        "\x00",
        "\r",
        "\n",
    }

    for character in forbidden_characters:
        if character in argument:
            raise BuildSecurityError(
                f"Argument {argument_index} contains a forbidden "
                "control character."
            )


def _reject_dangerous_common_arguments(
    arguments: Sequence[str],
) -> None:
    forbidden_exact = {
        "--exec",
        "-exec",
        "--command",
        "-command",
        "/c",
        "/k",
        "-c",
        "-enc",
        "-encodedcommand",
        "--eval",
        "-e",
    }

    forbidden_casefolded = {
        item.casefold() for item in forbidden_exact
    }

    dangerous_fragments = (
        "&&",
        "||",
        "$(",
        "${",
        "`",
        "\x00",
    )

    for index, argument in enumerate(arguments):
        _reject_shell_metacharacters(
            argument,
            argument_index=index,
        )

        normalized = argument.strip().casefold()

        if normalized in forbidden_casefolded:
            raise BuildSecurityError(
                f"Argument {argument!r} is not permitted for build "
                "execution."
            )

        if any(fragment in argument for fragment in dangerous_fragments):
            raise BuildSecurityError(
                f"Argument {argument!r} contains a forbidden command "
                "composition fragment."
            )


def _validate_python_compile_arguments(
    arguments: Sequence[str],
    *,
    repository_root: Path,
    working_directory: Path,
) -> None:
    if not arguments:
        raise BuildValidationError(
            "Python compilation requires at least one file or directory."
        )

    for argument in arguments:
        if argument.startswith("-"):
            if argument not in {"-q", "-f"}:
                raise BuildSecurityError(
                    f"Unsupported Python compilation option: {argument!r}."
                )
            continue

        candidate = (
            Path(argument)
            if Path(argument).is_absolute()
            else working_directory / argument
        )

        normalize_repository_path(
            repository_root,
            candidate,
            must_exist=True,
        )


def _validate_pytest_arguments(
    arguments: Sequence[str],
    *,
    repository_root: Path,
    working_directory: Path,
) -> None:
    forbidden_options = {
        "--pdb",
        "--trace",
        "--pdbcls",
        "--basetemp",
    }

    for index, argument in enumerate(arguments):
        option_name = argument.split("=", 1)[0].casefold()

        if option_name in forbidden_options:
            raise BuildSecurityError(
                f"pytest option is not permitted: {argument!r}."
            )

        if argument.startswith("-"):
            continue

        if "::" in argument:
            path_part = argument.split("::", 1)[0]
        else:
            path_part = argument

        if not path_part:
            continue

        candidate = (
            Path(path_part)
            if Path(path_part).is_absolute()
            else working_directory / path_part
        )

        if candidate.exists():
            normalize_repository_path(
                repository_root,
                candidate,
                must_exist=True,
            )


def _validate_unittest_arguments(
    arguments: Sequence[str],
) -> None:
    for argument in arguments:
        if argument.startswith("-"):
            if argument not in {
                "-v",
                "--verbose",
                "-q",
                "--quiet",
                "-f",
                "--failfast",
                "-b",
                "--buffer",
                "-c",
                "--catch",
            }:
                raise BuildSecurityError(
                    f"Unsupported unittest option: {argument!r}."
                )
            continue

        if not PYTHON_MODULE_NAME_PATTERN.fullmatch(argument):
            raise BuildValidationError(
                f"Invalid unittest module name: {argument!r}."
            )


def _validate_static_analysis_arguments(
    arguments: Sequence[str],
    *,
    repository_root: Path,
    working_directory: Path,
) -> None:
    forbidden_options = {
        "--config",
        "--config-file",
        "--python-executable",
        "--custom-typeshed-dir",
        "--plugins",
    }

    for argument in arguments:
        option_name = argument.split("=", 1)[0].casefold()

        if option_name in forbidden_options:
            raise BuildSecurityError(
                f"Static-analysis option is not permitted: {argument!r}."
            )

        if argument.startswith("-"):
            continue

        candidate = (
            Path(argument)
            if Path(argument).is_absolute()
            else working_directory / argument
        )

        if candidate.exists():
            normalize_repository_path(
                repository_root,
                candidate,
                must_exist=True,
            )


def _validate_package_manager_arguments(
    arguments: Sequence[str],
    *,
    manager: PackageManager,
) -> None:
    if not arguments:
        raise BuildValidationError(
            f"{manager.value} requires at least one argument."
        )

    forbidden_commands = {
        "adduser",
        "author",
        "deprecate",
        "dist-tag",
        "login",
        "logout",
        "owner",
        "profile",
        "publish",
        "token",
        "unpublish",
        "whoami",
        "config",
        "set",
        "delete",
        "link",
        "unlink",
        "exec",
        "dlx",
        "create",
        "init",
    }

    first_command = next(
        (
            argument
            for argument in arguments
            if not argument.startswith("-")
        ),
        "",
    ).casefold()

    if first_command in forbidden_commands:
        raise BuildSecurityError(
            f"{manager.value} command is not permitted: "
            f"{first_command!r}."
        )

    forbidden_options = {
        "--global",
        "-g",
        "--registry",
        "--userconfig",
        "--globalconfig",
        "--prefix",
        "--script-shell",
        "--unsafe-perm",
        "--ignore-scripts=false",
    }

    for argument in arguments:
        option_name = argument.split("=", 1)[0].casefold()

        if option_name in forbidden_options:
            raise BuildSecurityError(
                f"{manager.value} option is not permitted: "
                f"{argument!r}."
            )


def _validate_npx_arguments(arguments: Sequence[str]) -> None:
    if not arguments:
        raise BuildValidationError("npx requires a package or command.")

    forbidden_options = {
        "--package",
        "-p",
        "--shell",
        "-c",
        "--call",
        "--yes",
        "-y",
    }

    for argument in arguments:
        option_name = argument.split("=", 1)[0].casefold()

        if option_name in forbidden_options:
            raise BuildSecurityError(
                f"npx option is not permitted: {argument!r}."
            )


def _validate_custom_command(
    command: BuildCommandSpec,
    *,
    policy: CustomCommandPolicy,
    repository_root: Path,
    working_directory: Path,
) -> None:
    if not command.executable:
        raise BuildValidationError(
            "Custom commands require an executable."
        )

    executable_name = Path(command.executable).name
    normalized_name = _normalize_case(executable_name)

    explicit_paths = {
        os.path.normcase(os.path.normpath(path))
        for path in policy.executable_paths
    }

    executable_path = Path(command.executable).expanduser()
    explicitly_allowed_by_path = False

    if executable_path.is_absolute():
        normalized_executable_path = os.path.normcase(
            os.path.normpath(
                str(executable_path.resolve(strict=False))
            )
        )
        explicitly_allowed_by_path = (
            normalized_executable_path in explicit_paths
        )

    if (
        normalized_name not in policy.executable_names
        and not explicitly_allowed_by_path
    ):
        raise BuildSecurityError(
            f"Custom executable is not allowlisted: "
            f"{command.executable!r}."
        )

    forbidden_arguments = {
        _normalize_case(argument)
        for argument in policy.forbidden_arguments
    }

    for index, argument in enumerate(command.arguments):
        if _normalize_case(argument) in forbidden_arguments:
            raise BuildSecurityError(
                f"Custom command argument is forbidden: {argument!r}."
            )

        if (
            policy.allowed_argument_prefixes
            and not any(
                argument.startswith(prefix)
                for prefix in policy.allowed_argument_prefixes
            )
        ):
            is_repository_path = False

            if policy.allow_repository_file_arguments:
                candidate = (
                    Path(argument)
                    if Path(argument).is_absolute()
                    else working_directory / argument
                )

                if candidate.exists():
                    normalize_repository_path(
                        repository_root,
                        candidate,
                        must_exist=True,
                    )
                    is_repository_path = True

            if not is_repository_path:
                raise BuildSecurityError(
                    f"Custom command argument {index} is not permitted "
                    f"by the configured prefixes: {argument!r}."
                )

        if not SAFE_CUSTOM_ARGUMENT_PATTERN.fullmatch(argument):
            raise BuildSecurityError(
                f"Custom command argument contains unsafe characters: "
                f"{argument!r}."
            )


def validate_command_spec(
    command: BuildCommandSpec,
    *,
    configuration: BuildServiceConfiguration,
) -> None:
    repository_root = configuration.repository_root

    working_directory = normalize_repository_path(
        repository_root,
        command.working_directory,
        must_exist=True,
        require_directory=True,
    )

    _reject_dangerous_common_arguments(command.arguments)

    if command.kind is BuildCommandKind.PYTHON_COMPILE:
        _validate_python_compile_arguments(
            command.arguments,
            repository_root=repository_root,
            working_directory=working_directory,
        )

    elif command.kind is BuildCommandKind.PYTEST:
        _validate_pytest_arguments(
            command.arguments,
            repository_root=repository_root,
            working_directory=working_directory,
        )

    elif command.kind is BuildCommandKind.UNITTEST:
        _validate_unittest_arguments(command.arguments)

    elif command.kind in {
        BuildCommandKind.RUFF,
        BuildCommandKind.MYPY,
    }:
        _validate_static_analysis_arguments(
            command.arguments,
            repository_root=repository_root,
            working_directory=working_directory,
        )

    elif command.kind is BuildCommandKind.NPM:
        _validate_package_manager_arguments(
            command.arguments,
            manager=PackageManager.NPM,
        )

    elif command.kind is BuildCommandKind.YARN:
        _validate_package_manager_arguments(
            command.arguments,
            manager=PackageManager.YARN,
        )

    elif command.kind is BuildCommandKind.PNPM:
        _validate_package_manager_arguments(
            command.arguments,
            manager=PackageManager.PNPM,
        )

    elif command.kind is BuildCommandKind.NPX:
        _validate_npx_arguments(command.arguments)

    elif command.kind is BuildCommandKind.CUSTOM:
        _validate_custom_command(
            command,
            policy=configuration.custom_command_policy,
            repository_root=repository_root,
            working_directory=working_directory,
        )

    _invoke_optional_security_hook(
        (
            "validate_build_command",
            "validate_command",
            "ensure_safe_command",
            "assert_safe_command",
        ),
        command=command,
        repository_root=repository_root,
    )
def _default_executable_for_kind(
    kind: BuildCommandKind,
) -> str:
    if kind in {
        BuildCommandKind.PYTHON_COMPILE,
        BuildCommandKind.PYTEST,
        BuildCommandKind.UNITTEST,
    }:
        return sys.executable

    executable_by_kind = {
        BuildCommandKind.RUFF: "ruff",
        BuildCommandKind.MYPY: "mypy",
        BuildCommandKind.FRONTEND_TEST: "npm",
        BuildCommandKind.FRONTEND_BUILD: "npm",
        BuildCommandKind.TYPESCRIPT: "npx",
        BuildCommandKind.NPM: "npm",
        BuildCommandKind.NPX: "npx",
        BuildCommandKind.YARN: "yarn",
        BuildCommandKind.PNPM: "pnpm",
    }

    try:
        return executable_by_kind[kind]
    except KeyError as exc:
        raise BuildConfigurationError(
            f"No default executable is configured for command kind "
            f"{kind.value!r}."
        ) from exc


def _normalized_arguments_for_kind(
    command: BuildCommandSpec,
) -> tuple[str, ...]:
    arguments = tuple(command.arguments)

    if command.kind is BuildCommandKind.PYTHON_COMPILE:
        return ("-m", "compileall", *arguments)

    if command.kind is BuildCommandKind.PYTEST:
        return ("-m", "pytest", *arguments)

    if command.kind is BuildCommandKind.UNITTEST:
        return ("-m", "unittest", *arguments)

    if command.kind is BuildCommandKind.FRONTEND_TEST:
        if arguments:
            return arguments
        return ("test", "--", "--runInBand")

    if command.kind is BuildCommandKind.FRONTEND_BUILD:
        if arguments:
            return arguments
        return ("run", "build")

    if command.kind is BuildCommandKind.TYPESCRIPT:
        if arguments:
            return arguments
        return ("tsc", "--noEmit")

    return arguments


def resolve_command(
    command: BuildCommandSpec,
    *,
    configuration: BuildServiceConfiguration,
) -> ResolvedCommand:
    validate_command_spec(
        command,
        configuration=configuration,
    )

    repository_root = configuration.repository_root
    working_directory = normalize_repository_path(
        repository_root,
        command.working_directory,
        must_exist=True,
        require_directory=True,
    )

    executable_text = (
        command.executable
        or _default_executable_for_kind(command.kind)
    )

    safe_environment = build_safe_environment(
        configuration,
        command.environment,
    )

    custom_policy = configuration.custom_command_policy
    explicitly_allowed_paths = custom_policy.executable_paths
    if command.kind in {
        BuildCommandKind.PYTHON_COMPILE,
        BuildCommandKind.PYTEST,
        BuildCommandKind.UNITTEST,
    }:
        # These built-in command kinds deliberately use the interpreter that is
        # already running LUMINA. On Windows ``sys.executable`` is absolute, so
        # include that trusted interpreter without weakening the allowlist for
        # user-supplied custom commands or other absolute executables.
        explicitly_allowed_paths = frozenset(
            {*explicitly_allowed_paths, sys.executable}
        )

    executable = resolve_executable(
        executable_text,
        repository_root=repository_root,
        search_environment=safe_environment,
        allow_repository_executable=False,
        explicitly_allowed_paths=explicitly_allowed_paths,
    )

    normalized_arguments = _normalized_arguments_for_kind(command)

    return ResolvedCommand(
        command_id=command.command_id,
        kind=command.kind,
        executable=executable,
        arguments=normalized_arguments,
        working_directory=working_directory,
        environment=safe_environment,
        timeout_seconds=command.timeout_seconds,
        allowed_exit_codes=command.allowed_exit_codes,
        continue_on_failure=command.continue_on_failure,
        description=command.description,
    )


def _startup_info() -> subprocess.STARTUPINFO | None:
    if not IS_WINDOWS:
        return None

    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE
    return startup_info


def _creation_flags() -> int:
    if not IS_WINDOWS:
        return 0

    flags = subprocess.CREATE_NEW_PROCESS_GROUP

    create_no_window = getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )
    flags |= create_no_window

    return flags


def _stream_reader(
    stream: Any,
    buffer: BoundedTextBuffer,
    *,
    chunk_size: int,
) -> None:
    try:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            buffer.append(chunk)
    except (OSError, ValueError):
        return
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _taskkill_process_tree(
    process_id: int,
    *,
    force: bool,
    timeout_seconds: float,
) -> bool:
    if not IS_WINDOWS:
        return False

    arguments = [
        "taskkill",
        "/PID",
        str(process_id),
        "/T",
    ]

    if force:
        arguments.append("/F")

    try:
        completed = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
            startupinfo=_startup_info(),
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            ),
        )
    except (
        FileNotFoundError,
        OSError,
        subprocess.TimeoutExpired,
    ):
        return False

    return completed.returncode == 0


def terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS,
) -> None:
    if process.poll() is not None:
        return

    if IS_WINDOWS:
        _taskkill_process_tree(
            process.pid,
            force=False,
            timeout_seconds=max(1.0, grace_seconds),
        )

        try:
            process.wait(timeout=grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass

        _taskkill_process_tree(
            process.pid,
            force=True,
            timeout_seconds=max(1.0, grace_seconds),
        )

        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
        return

    try:
        process.terminate()
    except OSError:
        return

    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        process.kill()
    except OSError:
        return

    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass


def _wait_for_process(
    process: subprocess.Popen[str],
    *,
    command_id: str,
    timeout_seconds: float,
    cancellation_token: CancellationToken | None,
    termination_grace_seconds: float,
    poll_interval_seconds: float = 0.05,
) -> int:
    started_monotonic = time.monotonic()

    while True:
        exit_code = process.poll()
        if exit_code is not None:
            return exit_code

        if (
            cancellation_token is not None
            and cancellation_token.is_cancelled()
        ):
            terminate_process_tree(
                process,
                grace_seconds=termination_grace_seconds,
            )
            raise BuildCancellationError(
                cancellation_token.reason
                or "Build execution was cancelled.",
                command_id=command_id,
            )

        elapsed = time.monotonic() - started_monotonic
        if elapsed >= timeout_seconds:
            terminate_process_tree(
                process,
                grace_seconds=termination_grace_seconds,
            )
            raise BuildTimeoutError(
                (
                    f"Command {command_id!r} exceeded its timeout of "
                    f"{timeout_seconds:.3f} seconds."
                ),
                timeout_seconds=timeout_seconds,
                command_id=command_id,
            )

        remaining = timeout_seconds - elapsed
        time.sleep(min(poll_interval_seconds, max(0.001, remaining)))


def _join_reader_threads(
    threads: Sequence[threading.Thread],
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds

    for thread in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        thread.join(timeout=remaining)


def _command_metadata(
    resolved_command: ResolvedCommand,
) -> dict[str, Any]:
    return {
        "description": resolved_command.description,
        "allowed_exit_codes": sorted(
            resolved_command.allowed_exit_codes
        ),
        "environment": sanitize_environment_for_display(
            resolved_command.environment
        ),
    }


def _make_dry_run_result(
    resolved_command: ResolvedCommand,
) -> BuildCommandResult:
    now = time.time()

    return BuildCommandResult(
        command_id=resolved_command.command_id,
        kind=resolved_command.kind,
        status=BuildStatus.DRY_RUN,
        executable=str(resolved_command.executable),
        arguments=resolved_command.arguments,
        working_directory=str(
            resolved_command.working_directory
        ),
        stdout="",
        stderr="",
        exit_code=None,
        duration_seconds=0.0,
        started_at_epoch=now,
        finished_at_epoch=now,
        timed_out=False,
        cancelled=False,
        dry_run=True,
        stdout_truncated=False,
        stderr_truncated=False,
        metadata=_command_metadata(resolved_command),
    )


def _make_skipped_result(
    command: BuildCommandSpec,
    *,
    reason: str,
    repository_root: Path,
) -> BuildCommandResult:
    now = time.time()

    try:
        working_directory = normalize_repository_path(
            repository_root,
            command.working_directory,
            must_exist=False,
        )
        working_directory_text = str(working_directory)
    except BuildServiceError:
        working_directory_text = command.working_directory

    executable = (
        command.executable
        or _default_executable_for_kind(command.kind)
    )

    return BuildCommandResult(
        command_id=command.command_id,
        kind=command.kind,
        status=BuildStatus.SKIPPED,
        executable=executable,
        arguments=command.arguments,
        working_directory=working_directory_text,
        stdout="",
        stderr="",
        exit_code=None,
        duration_seconds=0.0,
        started_at_epoch=now,
        finished_at_epoch=now,
        error_type="BuildSkipped",
        error_message=reason,
        metadata={
            "description": command.description,
        },
    )


def _make_resolution_failure_result(
    command: BuildCommandSpec,
    *,
    error: BuildServiceError,
) -> BuildCommandResult:
    now = time.time()

    return BuildCommandResult(
        command_id=command.command_id,
        kind=command.kind,
        status=BuildStatus.ERROR,
        executable=(
            command.executable
            or _default_executable_for_kind(command.kind)
        ),
        arguments=command.arguments,
        working_directory=command.working_directory,
        stdout="",
        stderr="",
        exit_code=None,
        duration_seconds=0.0,
        started_at_epoch=now,
        finished_at_epoch=now,
        error_type=type(error).__name__,
        error_message=str(error),
        metadata={
            "description": command.description,
        },
    )


def execute_resolved_command(
    resolved_command: ResolvedCommand,
    *,
    options: BuildExecutionOptions | None = None,
    cancellation_token: CancellationToken | None = None,
    process_registry: ProcessRegistry | None = None,
) -> BuildCommandResult:
    effective_options = options or BuildExecutionOptions()

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled(
            command_id=resolved_command.command_id
        )

    if effective_options.dry_run:
        return _make_dry_run_result(resolved_command)

    stdout_buffer = BoundedTextBuffer(
        effective_options.max_log_bytes_per_stream
    )
    stderr_buffer = BoundedTextBuffer(
        effective_options.max_log_bytes_per_stream
    )

    started_at_epoch = time.time()
    started_monotonic = time.monotonic()
    process: subprocess.Popen[str] | None = None
    reader_threads: list[threading.Thread] = []

    status = BuildStatus.ERROR
    exit_code: int | None = None
    timed_out = False
    cancelled = False
    error_type: str | None = None
    error_message: str | None = None

    try:
        process = subprocess.Popen(
            resolved_command.argv,
            cwd=str(resolved_command.working_directory),
            env=resolved_command.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            startupinfo=_startup_info(),
            creationflags=_creation_flags(),
        )

        if process.stdout is None or process.stderr is None:
            raise BuildExecutionError(
                "Subprocess output pipes could not be created.",
                command_id=resolved_command.command_id,
            )

        if process_registry is not None:
            process_registry.register(
                resolved_command.command_id,
                process,
            )

        stdout_thread = threading.Thread(
            target=_stream_reader,
            args=(process.stdout, stdout_buffer),
            kwargs={
                "chunk_size": effective_options.stream_chunk_size,
            },
            name=(
                f"build-stdout-"
                f"{resolved_command.command_id}"
            ),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_stream_reader,
            args=(process.stderr, stderr_buffer),
            kwargs={
                "chunk_size": effective_options.stream_chunk_size,
            },
            name=(
                f"build-stderr-"
                f"{resolved_command.command_id}"
            ),
            daemon=True,
        )

        reader_threads.extend(
            [stdout_thread, stderr_thread]
        )

        stdout_thread.start()
        stderr_thread.start()

        exit_code = _wait_for_process(
            process,
            command_id=resolved_command.command_id,
            timeout_seconds=resolved_command.timeout_seconds,
            cancellation_token=cancellation_token,
            termination_grace_seconds=(
                effective_options.termination_grace_seconds
            ),
        )

        status = (
            BuildStatus.SUCCEEDED
            if exit_code in resolved_command.allowed_exit_codes
            else BuildStatus.FAILED
        )

        if status is BuildStatus.FAILED:
            error_type = BuildExecutionError.__name__
            error_message = (
                f"Command {resolved_command.command_id!r} exited "
                f"with code {exit_code}."
            )

    except BuildTimeoutError as exc:
        timed_out = True
        status = BuildStatus.TIMED_OUT
        error_type = type(exc).__name__
        error_message = str(exc)

    except BuildCancellationError as exc:
        cancelled = True
        status = BuildStatus.CANCELLED
        error_type = type(exc).__name__
        error_message = str(exc)

    except FileNotFoundError as exc:
        status = BuildStatus.ERROR
        error_type = BuildExecutableNotFoundError.__name__
        error_message = (
            f"Executable was not found: "
            f"{resolved_command.executable}"
        )

        if process is not None:
            terminate_process_tree(
                process,
                grace_seconds=(
                    effective_options.termination_grace_seconds
                ),
            )

    except OSError as exc:
        status = BuildStatus.ERROR
        error_type = BuildExecutionError.__name__
        error_message = (
            f"Failed to start or execute command "
            f"{resolved_command.command_id!r}: {exc}"
        )

        if process is not None:
            terminate_process_tree(
                process,
                grace_seconds=(
                    effective_options.termination_grace_seconds
                ),
            )

    except BuildServiceError as exc:
        status = BuildStatus.ERROR
        error_type = type(exc).__name__
        error_message = str(exc)

        if process is not None:
            terminate_process_tree(
                process,
                grace_seconds=(
                    effective_options.termination_grace_seconds
                ),
            )

    except Exception as exc:
        status = BuildStatus.ERROR
        error_type = BuildExecutionError.__name__
        error_message = (
            f"Unexpected execution failure for command "
            f"{resolved_command.command_id!r}: "
            f"{type(exc).__name__}: {exc}"
        )

        if process is not None:
            terminate_process_tree(
                process,
                grace_seconds=(
                    effective_options.termination_grace_seconds
                ),
            )

    finally:
        if process is not None:
            if process.poll() is None:
                terminate_process_tree(
                    process,
                    grace_seconds=(
                        effective_options.termination_grace_seconds
                    ),
                )

            if process_registry is not None:
                process_registry.unregister(
                    resolved_command.command_id,
                    process,
                )

        _join_reader_threads(
            reader_threads,
            timeout_seconds=max(
                1.0,
                effective_options.termination_grace_seconds,
            ),
        )

    finished_at_epoch = time.time()
    duration_seconds = max(
        0.0,
        time.monotonic() - started_monotonic,
    )

    stdout = stdout_buffer.getvalue()
    stderr = stderr_buffer.getvalue()

    if effective_options.redact_logs:
        stdout = redact_sensitive_text(
            stdout,
            environment=resolved_command.environment,
        )
        stderr = redact_sensitive_text(
            stderr,
            environment=resolved_command.environment,
        )
        if error_message:
            error_message = redact_sensitive_text(
                error_message,
                environment=resolved_command.environment,
            )

    metadata = _command_metadata(resolved_command)
    metadata.update(
        {
            "stdout_discarded_bytes": (
                stdout_buffer.discarded_bytes
            ),
            "stderr_discarded_bytes": (
                stderr_buffer.discarded_bytes
            ),
        }
    )

    return BuildCommandResult(
        command_id=resolved_command.command_id,
        kind=resolved_command.kind,
        status=status,
        executable=str(resolved_command.executable),
        arguments=resolved_command.arguments,
        working_directory=str(
            resolved_command.working_directory
        ),
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_seconds=duration_seconds,
        started_at_epoch=started_at_epoch,
        finished_at_epoch=finished_at_epoch,
        timed_out=timed_out,
        cancelled=cancelled,
        dry_run=False,
        stdout_truncated=stdout_buffer.truncated,
        stderr_truncated=stderr_buffer.truncated,
        error_type=error_type,
        error_message=error_message,
        metadata=metadata,
    )


def execute_command(
    command: BuildCommandSpec,
    *,
    configuration: BuildServiceConfiguration,
    options: BuildExecutionOptions | None = None,
    cancellation_token: CancellationToken | None = None,
    process_registry: ProcessRegistry | None = None,
    raise_on_configuration_error: bool = False,
) -> BuildCommandResult:
    try:
        resolved = resolve_command(
            command,
            configuration=configuration,
        )
    except BuildServiceError as exc:
        if raise_on_configuration_error:
            raise

        return _make_resolution_failure_result(
            command,
            error=exc,
        )

    return execute_resolved_command(
        resolved,
        options=options,
        cancellation_token=cancellation_token,
        process_registry=process_registry,
    )


def _sequence_status_from_results(
    results: Sequence[BuildCommandResult],
    *,
    dry_run: bool,
) -> BuildStatus:
    if not results:
        return (
            BuildStatus.DRY_RUN
            if dry_run
            else BuildStatus.SUCCEEDED
        )

    statuses = {result.status for result in results}

    if BuildStatus.CANCELLED in statuses:
        return BuildStatus.CANCELLED

    if BuildStatus.TIMED_OUT in statuses:
        return BuildStatus.TIMED_OUT

    if BuildStatus.ERROR in statuses:
        return BuildStatus.ERROR

    if BuildStatus.FAILED in statuses:
        return BuildStatus.FAILED

    if dry_run:
        return BuildStatus.DRY_RUN

    return BuildStatus.SUCCEEDED


def execute_command_sequence(
    commands: Sequence[BuildCommandSpec],
    *,
    configuration: BuildServiceConfiguration,
    options: BuildExecutionOptions | None = None,
    cancellation_token: CancellationToken | None = None,
    process_registry: ProcessRegistry | None = None,
) -> BuildSequenceResult:
    effective_options = options or BuildExecutionOptions()

    if len(commands) > configuration.max_commands_per_sequence:
        raise BuildConfigurationError(
            "Build sequence exceeds the configured maximum number "
            f"of commands: {configuration.max_commands_per_sequence}."
        )

    command_ids = [command.command_id for command in commands]
    duplicate_ids = sorted(
        {
            command_id
            for command_id in command_ids
            if command_ids.count(command_id) > 1
        }
    )

    if duplicate_ids:
        raise BuildValidationError(
            "Build command IDs must be unique. Duplicates: "
            f"{', '.join(duplicate_ids)}"
        )

    started_at_epoch = time.time()
    started_monotonic = time.monotonic()
    results: list[BuildCommandResult] = []
    stopped_early = False
    sequence_cancelled = False

    for index, command in enumerate(commands):
        if (
            cancellation_token is not None
            and cancellation_token.is_cancelled()
        ):
            sequence_cancelled = True
            stopped_early = True

            results.append(
                _make_skipped_result(
                    command,
                    reason=(
                        cancellation_token.reason
                        or "Sequence was cancelled before execution."
                    ),
                    repository_root=configuration.repository_root,
                )
            )

            for remaining_command in commands[index + 1 :]:
                results.append(
                    _make_skipped_result(
                        remaining_command,
                        reason=(
                            "Sequence was cancelled before execution."
                        ),
                        repository_root=configuration.repository_root,
                    )
                )
            break

        result = execute_command(
            command,
            configuration=configuration,
            options=effective_options,
            cancellation_token=cancellation_token,
            process_registry=process_registry,
            raise_on_configuration_error=False,
        )
        results.append(result)

        if result.status is BuildStatus.CANCELLED:
            sequence_cancelled = True

        command_failed = result.status in {
            BuildStatus.FAILED,
            BuildStatus.TIMED_OUT,
            BuildStatus.CANCELLED,
            BuildStatus.ERROR,
        }

        should_stop = (
            command_failed
            and effective_options.stop_on_first_failure
            and not command.continue_on_failure
        )

        if should_stop:
            stopped_early = index < len(commands) - 1

            for remaining_command in commands[index + 1 :]:
                results.append(
                    _make_skipped_result(
                        remaining_command,
                        reason=(
                            "Skipped because a previous command failed "
                            "and stop_on_first_failure is enabled."
                        ),
                        repository_root=configuration.repository_root,
                    )
                )
            break

    finished_at_epoch = time.time()
    duration_seconds = max(
        0.0,
        time.monotonic() - started_monotonic,
    )

    sequence_status = _sequence_status_from_results(
        results,
        dry_run=effective_options.dry_run,
    )

    return BuildSequenceResult(
        status=sequence_status,
        commands=tuple(results),
        duration_seconds=duration_seconds,
        started_at_epoch=started_at_epoch,
        finished_at_epoch=finished_at_epoch,
        dry_run=effective_options.dry_run,
        stopped_early=stopped_early,
        cancelled=sequence_cancelled,
        metadata={
            "command_count": len(commands),
            "executed_count": sum(
                result.status is not BuildStatus.SKIPPED
                for result in results
            ),
            "skipped_count": sum(
                result.status is BuildStatus.SKIPPED
                for result in results
            ),
        },
    )


class BuildService:
    """Secure sequential build and validation command executor."""

    def __init__(
        self,
        configuration: BuildServiceConfiguration,
    ) -> None:
        self._configuration = configuration
        self._process_registry = ProcessRegistry()
        self._cancellation_tokens: dict[str, CancellationToken] = {}
        self._token_lock = threading.RLock()

    @property
    def configuration(self) -> BuildServiceConfiguration:
        return self._configuration

    def create_cancellation_token(
        self,
        execution_id: str,
    ) -> CancellationToken:
        if not execution_id or not execution_id.strip():
            raise BuildValidationError(
                "execution_id cannot be empty."
            )

        normalized_id = execution_id.strip()

        with self._token_lock:
            if normalized_id in self._cancellation_tokens:
                raise BuildValidationError(
                    f"A cancellation token already exists for "
                    f"execution {normalized_id!r}."
                )

            token = CancellationToken()
            self._cancellation_tokens[normalized_id] = token
            return token

    def get_cancellation_token(
        self,
        execution_id: str,
    ) -> CancellationToken | None:
        with self._token_lock:
            return self._cancellation_tokens.get(execution_id)

    def release_cancellation_token(
        self,
        execution_id: str,
    ) -> None:
        with self._token_lock:
            self._cancellation_tokens.pop(execution_id, None)

    def cancel(
        self,
        execution_id: str,
        *,
        reason: str | None = None,
    ) -> bool:
        token = self.get_cancellation_token(execution_id)

        if token is None:
            return False

        token.cancel(reason)
        return True

    def cancel_command(
        self,
        command_id: str,
        *,
        grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS,
    ) -> bool:
        process = self._process_registry.get(command_id)

        if process is None:
            return False

        terminate_process_tree(
            process,
            grace_seconds=grace_seconds,
        )
        return True

    def cancel_all(
        self,
        *,
        reason: str | None = None,
        grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS,
    ) -> int:
        with self._token_lock:
            tokens = tuple(self._cancellation_tokens.values())

        for token in tokens:
            token.cancel(reason)

        processes = self._process_registry.snapshot()

        for process in processes.values():
            terminate_process_tree(
                process,
                grace_seconds=grace_seconds,
            )

        return len(processes)

    def resolve(
        self,
        command: BuildCommandSpec,
    ) -> ResolvedCommand:
        return resolve_command(
            command,
            configuration=self._configuration,
        )

    def execute(
        self,
        command: BuildCommandSpec,
        *,
        options: BuildExecutionOptions | None = None,
        cancellation_token: CancellationToken | None = None,
        raise_on_configuration_error: bool = False,
    ) -> BuildCommandResult:
        return execute_command(
            command,
            configuration=self._configuration,
            options=options,
            cancellation_token=cancellation_token,
            process_registry=self._process_registry,
            raise_on_configuration_error=(
                raise_on_configuration_error
            ),
        )

    def execute_sequence(
        self,
        commands: Sequence[BuildCommandSpec],
        *,
        options: BuildExecutionOptions | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> BuildSequenceResult:
        return execute_command_sequence(
            commands,
            configuration=self._configuration,
            options=options,
            cancellation_token=cancellation_token,
            process_registry=self._process_registry,
        )


def create_build_service(
    repository_root: str | os.PathLike[str] | Path,
    *,
    allowed_environment_variables: Iterable[str] | None = None,
    inherited_environment_variables: Iterable[str] | None = None,
    custom_executable_names: Iterable[str] = (),
    custom_executable_paths: Iterable[str] = (),
    custom_allowed_argument_prefixes: Sequence[str] = (),
    custom_forbidden_arguments: Iterable[str] = (),
    allow_custom_repository_file_arguments: bool = True,
    default_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    max_commands_per_sequence: int = DEFAULT_MAX_COMMANDS,
) -> BuildService:
    configuration_values: dict[str, Any] = {
        "repository_root": Path(repository_root),
        "custom_command_policy": CustomCommandPolicy(
            executable_names=frozenset(custom_executable_names),
            executable_paths=frozenset(custom_executable_paths),
            allowed_argument_prefixes=tuple(
                custom_allowed_argument_prefixes
            ),
            forbidden_arguments=frozenset(
                custom_forbidden_arguments
            ),
            allow_repository_file_arguments=(
                allow_custom_repository_file_arguments
            ),
        ),
        "default_timeout_seconds": default_timeout_seconds,
        "max_commands_per_sequence": max_commands_per_sequence,
    }

    if allowed_environment_variables is not None:
        configuration_values[
            "allowed_environment_variables"
        ] = frozenset(allowed_environment_variables)

    if inherited_environment_variables is not None:
        configuration_values[
            "inherited_environment_variables"
        ] = frozenset(inherited_environment_variables)

    configuration = BuildServiceConfiguration(
        **configuration_values
    )
    return BuildService(configuration)


def create_python_compile_command(
    *,
    command_id: str = "python-compile",
    paths: Sequence[str] = (".",),
    working_directory: str = ".",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.PYTHON_COMPILE,
        arguments=tuple(paths),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description="Compile Python source files.",
    )


def create_pytest_command(
    *,
    command_id: str = "pytest",
    arguments: Sequence[str] = (),
    working_directory: str = ".",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.PYTEST,
        arguments=tuple(arguments),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description="Run pytest.",
    )


def create_unittest_command(
    *,
    command_id: str = "unittest",
    modules: Sequence[str] = (),
    working_directory: str = ".",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
    verbose: bool = True,
) -> BuildCommandSpec:
    arguments: list[str] = []

    if verbose:
        arguments.append("-v")

    arguments.extend(modules)

    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.UNITTEST,
        arguments=tuple(arguments),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description="Run Python unittest.",
    )


def create_ruff_command(
    *,
    command_id: str = "ruff",
    arguments: Sequence[str] = ("check", "."),
    working_directory: str = ".",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.RUFF,
        arguments=tuple(arguments),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description="Run Ruff static analysis.",
    )


def create_mypy_command(
    *,
    command_id: str = "mypy",
    arguments: Sequence[str] = (".",),
    working_directory: str = ".",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.MYPY,
        arguments=tuple(arguments),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description="Run mypy type validation.",
    )


def create_frontend_test_command(
    *,
    command_id: str = "frontend-test",
    package_manager: PackageManager = PackageManager.NPM,
    arguments: Sequence[str] | None = None,
    working_directory: str = "frontend",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
) -> BuildCommandSpec:
    default_arguments: tuple[str, ...]

    if package_manager is PackageManager.NPM:
        default_arguments = ("test", "--", "--runInBand")
    elif package_manager is PackageManager.YARN:
        default_arguments = ("test", "--runInBand")
    else:
        default_arguments = ("test", "--", "--runInBand")

    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind(package_manager.value),
        arguments=tuple(
            arguments
            if arguments is not None
            else default_arguments
        ),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description="Run frontend tests.",
    )


def create_frontend_build_command(
    *,
    command_id: str = "frontend-build",
    package_manager: PackageManager = PackageManager.NPM,
    arguments: Sequence[str] | None = None,
    working_directory: str = "frontend",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
) -> BuildCommandSpec:
    default_arguments = (
        ("run", "build")
        if package_manager is PackageManager.NPM
        else ("build",)
    )

    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind(package_manager.value),
        arguments=tuple(
            arguments
            if arguments is not None
            else default_arguments
        ),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description="Create the frontend production build.",
    )


def create_typescript_validation_command(
    *,
    command_id: str = "typescript",
    arguments: Sequence[str] = (
        "tsc",
        "--noEmit",
    ),
    working_directory: str = "frontend",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.NPX,
        arguments=tuple(arguments),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description="Run TypeScript validation without emitting files.",
    )


def create_package_manager_command(
    package_manager: PackageManager,
    arguments: Sequence[str],
    *,
    command_id: str,
    working_directory: str = ".",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
    description: str | None = None,
) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind(package_manager.value),
        arguments=tuple(arguments),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description=description,
    )


def create_npx_command(
    arguments: Sequence[str],
    *,
    command_id: str,
    working_directory: str = ".",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    continue_on_failure: bool = False,
    description: str | None = None,
) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.NPX,
        arguments=tuple(arguments),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        continue_on_failure=continue_on_failure,
        description=description,
    )


def create_custom_command(
    executable: str,
    arguments: Sequence[str],
    *,
    command_id: str,
    working_directory: str = ".",
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    allowed_exit_codes: Iterable[int] = (0,),
    continue_on_failure: bool = False,
    description: str | None = None,
) -> BuildCommandSpec:
    return BuildCommandSpec(
        command_id=command_id,
        kind=BuildCommandKind.CUSTOM,
        executable=executable,
        arguments=tuple(arguments),
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        environment=dict(environment or {}),
        allowed_exit_codes=frozenset(allowed_exit_codes),
        continue_on_failure=continue_on_failure,
        description=description,
    )


def create_default_validation_sequence(
    *,
    backend_directory: str = "backend",
    frontend_directory: str = "frontend",
    include_mypy: bool = True,
    include_ruff: bool = True,
    include_frontend_tests: bool = True,
    include_frontend_build: bool = True,
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> tuple[BuildCommandSpec, ...]:
    commands: list[BuildCommandSpec] = [
        create_python_compile_command(
            command_id="backend-python-compile",
            paths=(".",),
            working_directory=backend_directory,
            timeout_seconds=timeout_seconds,
        ),
        create_pytest_command(
            command_id="backend-pytest",
            working_directory=backend_directory,
            timeout_seconds=timeout_seconds,
        ),
    ]

    if include_ruff:
        commands.append(
            create_ruff_command(
                command_id="backend-ruff",
                arguments=("check", "."),
                working_directory=backend_directory,
                timeout_seconds=timeout_seconds,
            )
        )

    if include_mypy:
        commands.append(
            create_mypy_command(
                command_id="backend-mypy",
                arguments=(".",),
                working_directory=backend_directory,
                timeout_seconds=timeout_seconds,
            )
        )

    if include_frontend_tests:
        commands.append(
            create_frontend_test_command(
                command_id="frontend-tests",
                working_directory=frontend_directory,
                timeout_seconds=timeout_seconds,
            )
        )

    commands.append(
        create_typescript_validation_command(
            command_id="frontend-typescript",
            working_directory=frontend_directory,
            timeout_seconds=timeout_seconds,
        )
    )

    if include_frontend_build:
        commands.append(
            create_frontend_build_command(
                command_id="frontend-production-build",
                working_directory=frontend_directory,
                timeout_seconds=timeout_seconds,
            )
        )

    return tuple(commands)


def _model_field_names(
    model_type: type[Any],
) -> frozenset[str]:
    pydantic_fields = getattr(
        model_type,
        "model_fields",
        None,
    )
    if isinstance(pydantic_fields, Mapping):
        return frozenset(pydantic_fields.keys())

    dataclass_fields = getattr(
        model_type,
        "__dataclass_fields__",
        None,
    )
    if isinstance(dataclass_fields, Mapping):
        return frozenset(dataclass_fields.keys())

    annotations = getattr(
        model_type,
        "__annotations__",
        None,
    )
    if isinstance(annotations, Mapping):
        return frozenset(annotations.keys())

    return frozenset()


def _instantiate_compatible_model(
    model_type: type[Any],
    payload: Mapping[str, Any],
) -> Any:
    field_names = _model_field_names(model_type)

    filtered_payload = (
        {
            key: value
            for key, value in payload.items()
            if key in field_names
        }
        if field_names
        else dict(payload)
    )

    model_validate = getattr(
        model_type,
        "model_validate",
        None,
    )
    if callable(model_validate):
        return model_validate(filtered_payload)

    try:
        return model_type(**filtered_payload)
    except TypeError:
        from_dict = getattr(
            model_type,
            "from_dict",
            None,
        )
        if callable(from_dict):
            return from_dict(filtered_payload)
        raise


def _find_domain_model_type(
    candidate_names: Sequence[str],
) -> type[Any] | None:
    for candidate_name in candidate_names:
        candidate = getattr(
            domain_models,
            candidate_name,
            None,
        )
        if isinstance(candidate, type):
            return candidate

    return None


def command_result_to_domain_model(
    result: BuildCommandResult,
) -> Any:
    model_type = _find_domain_model_type(
        (
            "BuildCommandResult",
            "CommandExecutionResult",
            "BuildExecutionResult",
            "ValidationCommandResult",
            "ProcessExecutionResult",
        )
    )

    if model_type is None:
        return result

    payload = result.model_dump(mode="python")
    payload.update(
        {
            "success": result.succeeded,
            "command": [
                result.executable,
                *result.arguments,
            ],
            "cwd": result.working_directory,
            "duration": result.duration_seconds,
        }
    )

    try:
        return _instantiate_compatible_model(
            model_type,
            payload,
        )
    except Exception as exc:
        raise BuildResultMappingError(
            f"Could not map command result to "
            f"{model_type.__name__}: {exc}"
        ) from exc


def sequence_result_to_domain_model(
    result: BuildSequenceResult,
) -> Any:
    model_type = _find_domain_model_type(
        (
            "BuildSequenceResult",
            "BuildResult",
            "ValidationResult",
            "BuildExecutionSummary",
        )
    )

    if model_type is None:
        return result

    mapped_commands = [
        command_result_to_domain_model(command_result)
        for command_result in result.commands
    ]

    payload = result.model_dump(mode="python")
    payload.update(
        {
            "success": result.succeeded,
            "results": mapped_commands,
            "command_results": mapped_commands,
            "duration": result.duration_seconds,
        }
    )

    try:
        return _instantiate_compatible_model(
            model_type,
            payload,
        )
    except Exception as exc:
        raise BuildResultMappingError(
            f"Could not map sequence result to "
            f"{model_type.__name__}: {exc}"
        ) from exc


def repository_root_from_service(
    service: Any,
) -> Path:
    candidate_attributes = (
        "repository_root",
        "root",
        "root_path",
        "repo_root",
        "path",
    )

    for attribute_name in candidate_attributes:
        candidate = getattr(
            service,
            attribute_name,
            None,
        )

        if candidate is None:
            continue

        try:
            path = Path(candidate).expanduser().resolve(
                strict=True
            )
        except (TypeError, ValueError, OSError):
            continue

        if path.is_dir():
            return path

    getter_names = (
        "get_repository_root",
        "get_root",
        "resolve_repository_root",
    )

    for getter_name in getter_names:
        getter = getattr(service, getter_name, None)

        if not callable(getter):
            continue

        try:
            candidate = getter()
            path = Path(candidate).expanduser().resolve(
                strict=True
            )
        except (
            TypeError,
            ValueError,
            OSError,
        ):
            continue

        if path.is_dir():
            return path

    raise BuildConfigurationError(
        "Could not determine the repository root from the "
        "repository service."
    )


def create_build_service_from_repository_service(
    service: Any,
    **configuration_overrides: Any,
) -> BuildService:
    repository_root = repository_root_from_service(service)

    return create_build_service(
        repository_root,
        **configuration_overrides,
    )


def validate_after_patch(
    build_service: BuildService,
    commands: Sequence[BuildCommandSpec],
    *,
    options: BuildExecutionOptions | None = None,
    cancellation_token: CancellationToken | None = None,
) -> BuildSequenceResult:
    return build_service.execute_sequence(
        commands,
        options=options,
        cancellation_token=cancellation_token,
    )


def execute_validation_pipeline(
    repository_root: str | os.PathLike[str] | Path,
    commands: Sequence[BuildCommandSpec],
    *,
    dry_run: bool = False,
    stop_on_first_failure: bool = True,
    max_log_bytes_per_stream: int = DEFAULT_MAX_LOG_BYTES,
    termination_grace_seconds: float = (
        DEFAULT_TERMINATION_GRACE_SECONDS
    ),
    custom_executable_names: Iterable[str] = (),
    custom_executable_paths: Iterable[str] = (),
    custom_allowed_argument_prefixes: Sequence[str] = (),
    custom_forbidden_arguments: Iterable[str] = (),
    allowed_environment_variables: Iterable[str] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> BuildSequenceResult:
    service = create_build_service(
        repository_root,
        allowed_environment_variables=(
            allowed_environment_variables
        ),
        custom_executable_names=custom_executable_names,
        custom_executable_paths=custom_executable_paths,
        custom_allowed_argument_prefixes=(
            custom_allowed_argument_prefixes
        ),
        custom_forbidden_arguments=(
            custom_forbidden_arguments
        ),
    )

    options = BuildExecutionOptions(
        dry_run=dry_run,
        stop_on_first_failure=stop_on_first_failure,
        max_log_bytes_per_stream=max_log_bytes_per_stream,
        termination_grace_seconds=(
            termination_grace_seconds
        ),
    )

    return service.execute_sequence(
        commands,
        options=options,
        cancellation_token=cancellation_token,
    )


__all__ = [
    "BuildCancellationError",
    "BuildCommandKind",
    "BuildCommandResult",
    "BuildCommandSpec",
    "BuildConfigurationError",
    "BuildExecutableNotFoundError",
    "BuildExecutionError",
    "BuildExecutionOptions",
    "BuildResultMappingError",
    "BuildSecurityError",
    "BuildSequenceResult",
    "BuildService",
    "BuildServiceConfiguration",
    "BuildServiceError",
    "BuildStatus",
    "BuildTimeoutError",
    "BuildValidationError",
    "CancellationToken",
    "CustomCommandPolicy",
    "LogStream",
    "PackageManager",
    "ProcessRegistry",
    "ResolvedCommand",
    "build_safe_environment",
    "command_result_to_domain_model",
    "create_build_service",
    "create_build_service_from_repository_service",
    "create_custom_command",
    "create_default_validation_sequence",
    "create_frontend_build_command",
    "create_frontend_test_command",
    "create_mypy_command",
    "create_npx_command",
    "create_package_manager_command",
    "create_pytest_command",
    "create_python_compile_command",
    "create_ruff_command",
    "create_typescript_validation_command",
    "create_unittest_command",
    "execute_command",
    "execute_command_sequence",
    "execute_resolved_command",
    "execute_validation_pipeline",
    "normalize_repository_path",
    "redact_sensitive_text",
    "repository_root_from_service",
    "resolve_command",
    "resolve_executable",
    "sanitize_environment_for_display",
    "sequence_result_to_domain_model",
    "terminate_process_tree",
    "validate_after_patch",
    "validate_command_spec",
]
