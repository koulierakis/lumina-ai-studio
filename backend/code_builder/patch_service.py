"""Safe repository patch application for the LUMINA Code Builder.

This module validates and applies proposed source-code changes to files
inside a repository.

Primary guarantees:

- Every target path remains inside the configured repository root.
- Protected and blocked paths are rejected through security.py.
- All text files are read and written using UTF-8.
- UTF-8 BOM input is accepted but output is normalized to UTF-8 without BOM.
- Windows and POSIX path notation are normalized safely.
- Existing file hashes can be verified before modification.
- File writes are atomic through temporary files and os.replace.
- Newline handling is deterministic.
- Full replacement, exact text replacement, line-range replacement,
  insertion, deletion, rename, and unified-diff patches are supported.
- Duplicate, ambiguous, overlapping, or stale changes are rejected.
- Dry-run execution is supported.
- A patch transaction can be rolled back when any operation fails.
- Binary files and undecodable source files are never modified as text.

The transaction orchestration, rollback logic, models.py conversion, and
public helper functions continue in Part 2 of this file.
"""

from __future__ import annotations

import codecs
import difflib
import hashlib
import inspect
import logging
import os
import re
import shutil
import stat
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import models as code_builder_models
from .security import (
    BlockedFileError,
    UnsafePathError,
    evaluate_safe_path,
)


LOGGER = logging.getLogger(__name__)

UTC = timezone.utc

DEFAULT_ENCODING: Final[str] = "utf-8"
UTF8_BOM: Final[bytes] = codecs.BOM_UTF8
DEFAULT_NEWLINE: Final[str] = "\n"
WINDOWS_NEWLINE: Final[str] = "\r\n"

DEFAULT_MAX_FILE_BYTES: Final[int] = 20 * 1024 * 1024
DEFAULT_MAX_PATCH_BYTES: Final[int] = 10 * 1024 * 1024
DEFAULT_MAX_OPERATIONS: Final[int] = 1_000
DEFAULT_MAX_REPLACEMENTS: Final[int] = 10_000
DEFAULT_MAX_PATH_CHARACTERS: Final[int] = 1_024
DEFAULT_MAX_SEARCH_CHARACTERS: Final[int] = 2_000_000
DEFAULT_TEMP_FILE_PREFIX: Final[str] = ".lumina-patch-"
DEFAULT_TRANSACTION_DIRECTORY: Final[str] = ".lumina"
DEFAULT_TRANSACTION_BACKUP_DIRECTORY: Final[str] = "patch-transactions"

MAX_LINE_NUMBER: Final[int] = 100_000_000
MAX_TEXT_CHARACTERS: Final[int] = 20_000_000
MAX_WARNING_COUNT: Final[int] = 10_000

CONTROL_CHARACTER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
)

WINDOWS_DRIVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z]:"
)

MULTIPLE_SLASH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"/{2,}"
)

UNIFIED_DIFF_HEADER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^@@ -(?P<old_start>\d+)"
    r"(?:,(?P<old_count>\d+))?"
    r" \+(?P<new_start>\d+)"
    r"(?:,(?P<new_count>\d+))?"
    r" @@(?: .*)?$"
)

HEX_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-fA-F0-9]{64}$"
)

MODEL_PATCH_RESULT_CANDIDATES: Final[tuple[str, ...]] = (
    "PatchResult",
    "PatchApplicationResult",
    "ApplyPatchResult",
    "CodePatchResult",
)

MODEL_FILE_RESULT_CANDIDATES: Final[tuple[str, ...]] = (
    "FilePatchResult",
    "PatchFileResult",
    "AppliedFileChange",
    "FileChangeResult",
)

MODEL_PATCH_REQUEST_CANDIDATES: Final[tuple[str, ...]] = (
    "PatchRequest",
    "ApplyPatchRequest",
    "CodePatchRequest",
)

MODEL_PATCH_OPERATION_CANDIDATES: Final[tuple[str, ...]] = (
    "PatchOperation",
    "FilePatchOperation",
    "CodePatchOperation",
    "ProposedFileChange",
)

OPERATION_ALIASES: Final[dict[str, str]] = {
    "add": "create",
    "new": "create",
    "create_file": "create",
    "write": "replace_file",
    "overwrite": "replace_file",
    "full_replace": "replace_file",
    "replace": "replace_text",
    "search_replace": "replace_text",
    "modify": "replace_text",
    "edit": "replace_text",
    "insert_before_text": "insert_before",
    "insert_after_text": "insert_after",
    "append": "append_text",
    "prepend": "prepend_text",
    "replace_lines": "replace_range",
    "line_replace": "replace_range",
    "remove": "delete",
    "delete_file": "delete",
    "move": "rename",
    "rename_file": "rename",
    "diff": "unified_diff",
    "patch": "unified_diff",
    "apply_diff": "unified_diff",
}

VALID_OPERATION_VALUES: Final[frozenset[str]] = frozenset(
    {
        "create",
        "replace_file",
        "replace_text",
        "replace_range",
        "insert_before",
        "insert_after",
        "append_text",
        "prepend_text",
        "delete",
        "rename",
        "unified_diff",
    }
)


class PatchServiceError(RuntimeError):
    """Base exception for patch-service failures."""


class PatchConfigurationError(PatchServiceError):
    """Raised when patch configuration is invalid."""


class PatchRequestError(PatchServiceError):
    """Raised when a patch request is malformed."""


class PatchPathError(PatchServiceError):
    """Raised when a patch path is unsafe or invalid."""


class PatchEncodingError(PatchServiceError):
    """Raised when a file is not valid UTF-8 text."""


class PatchConflictError(PatchServiceError):
    """Raised when source content does not match patch expectations."""


class PatchHashMismatchError(PatchConflictError):
    """Raised when a source file hash differs from the expected hash."""


class PatchOperationError(PatchServiceError):
    """Raised when one file operation cannot be applied."""


class PatchTransactionError(PatchServiceError):
    """Raised when a multi-file patch transaction fails."""


class PatchRollbackError(PatchServiceError):
    """Raised when transaction rollback cannot fully restore files."""


class PatchModelCompatibilityError(PatchServiceError):
    """Raised when models.py does not expose a compatible model."""


class PatchOperationType(str, Enum):
    """Supported repository patch operations."""

    CREATE = "create"
    REPLACE_FILE = "replace_file"
    REPLACE_TEXT = "replace_text"
    REPLACE_RANGE = "replace_range"
    INSERT_BEFORE = "insert_before"
    INSERT_AFTER = "insert_after"
    APPEND_TEXT = "append_text"
    PREPEND_TEXT = "prepend_text"
    DELETE = "delete"
    RENAME = "rename"
    UNIFIED_DIFF = "unified_diff"


class PatchStatus(str, Enum):
    """Patch execution status."""

    PENDING = "pending"
    VALIDATED = "validated"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    DRY_RUN = "dry_run"


class NewlineMode(str, Enum):
    """How text newlines are selected for output."""

    PRESERVE = "preserve"
    LF = "lf"
    CRLF = "crlf"


@dataclass(frozen=True, slots=True)
class PatchConfiguration:
    """Runtime safety and behavior settings."""

    maximum_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    maximum_patch_bytes: int = DEFAULT_MAX_PATCH_BYTES
    maximum_operations: int = DEFAULT_MAX_OPERATIONS
    maximum_replacements: int = DEFAULT_MAX_REPLACEMENTS
    maximum_search_characters: int = DEFAULT_MAX_SEARCH_CHARACTERS
    encoding: str = DEFAULT_ENCODING
    newline_mode: NewlineMode = NewlineMode.PRESERVE
    create_parent_directories: bool = True
    allow_create: bool = True
    allow_delete: bool = True
    allow_rename: bool = True
    allow_overwrite_on_create: bool = False
    allow_overwrite_on_rename: bool = False
    require_expected_hash_for_existing_files: bool = False
    reject_symbolic_links: bool = True
    reject_protected_paths: bool = True
    preserve_file_permissions: bool = True
    preserve_final_newline: bool = True
    fsync_writes: bool = True
    rollback_on_failure: bool = True
    retain_transaction_backup_on_success: bool = False
    transaction_directory_name: str = (
        DEFAULT_TRANSACTION_DIRECTORY
    )
    backup_directory_name: str = (
        DEFAULT_TRANSACTION_BACKUP_DIRECTORY
    )

    def __post_init__(self) -> None:
        """Validate all patch-service configuration values."""

        numeric_settings = {
            "maximum_file_bytes": (
                self.maximum_file_bytes,
                1,
                2_000_000_000,
            ),
            "maximum_patch_bytes": (
                self.maximum_patch_bytes,
                1,
                2_000_000_000,
            ),
            "maximum_operations": (
                self.maximum_operations,
                1,
                100_000,
            ),
            "maximum_replacements": (
                self.maximum_replacements,
                1,
                10_000_000,
            ),
            "maximum_search_characters": (
                self.maximum_search_characters,
                1,
                100_000_000,
            ),
        }

        for name, (
            value,
            minimum,
            maximum,
        ) in numeric_settings.items():
            if isinstance(value, bool) or not isinstance(
                value,
                int,
            ):
                raise PatchConfigurationError(
                    f"{name} must be an integer."
                )

            if value < minimum or value > maximum:
                raise PatchConfigurationError(
                    f"{name} must be between "
                    f"{minimum} and {maximum}."
                )

        if self.encoding.casefold().replace(
            "_",
            "-",
        ) != "utf-8":
            raise PatchConfigurationError(
                "PatchService requires UTF-8 encoding."
            )

        if not isinstance(
            self.newline_mode,
            NewlineMode,
        ):
            try:
                object.__setattr__(
                    self,
                    "newline_mode",
                    NewlineMode(
                        str(self.newline_mode).casefold()
                    ),
                )
            except ValueError as exc:
                raise PatchConfigurationError(
                    "newline_mode must be preserve, lf, or crlf."
                ) from exc

        for field_name in (
            "transaction_directory_name",
            "backup_directory_name",
        ):
            value = getattr(self, field_name)

            if not isinstance(value, str):
                raise PatchConfigurationError(
                    f"{field_name} must be a string."
                )

            normalized = value.strip()

            if (
                not normalized
                or normalized in {".", ".."}
                or "/" in normalized
                or "\\" in normalized
                or CONTROL_CHARACTER_PATTERN.search(
                    normalized
                )
            ):
                raise PatchConfigurationError(
                    f"{field_name} must be a safe directory name."
                )

            object.__setattr__(
                self,
                field_name,
                normalized,
            )


class ProposedPatchOperation(BaseModel):
    """Canonical patch operation accepted by PatchService."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
    )

    operation_id: UUID = Field(
        default_factory=uuid4
    )
    operation: str = Field(
        min_length=1,
        max_length=100,
    )
    path: str = Field(
        min_length=1,
        max_length=DEFAULT_MAX_PATH_CHARACTERS,
    )
    destination_path: str | None = Field(
        default=None,
        max_length=DEFAULT_MAX_PATH_CHARACTERS,
    )

    content: str | None = Field(
        default=None,
        max_length=MAX_TEXT_CHARACTERS,
    )
    search_text: str | None = Field(
        default=None,
        max_length=MAX_TEXT_CHARACTERS,
    )
    replacement_text: str | None = Field(
        default=None,
        max_length=MAX_TEXT_CHARACTERS,
    )
    unified_diff: str | None = Field(
        default=None,
        max_length=MAX_TEXT_CHARACTERS,
    )

    start_line: int | None = Field(
        default=None,
        ge=1,
        le=MAX_LINE_NUMBER,
    )
    end_line: int | None = Field(
        default=None,
        ge=1,
        le=MAX_LINE_NUMBER,
    )

    expected_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    expected_occurrences: int | None = Field(
        default=None,
        ge=0,
        le=DEFAULT_MAX_REPLACEMENTS,
    )

    create_if_missing: bool = False
    ignore_if_missing: bool = False
    ignore_if_exists: bool = False
    preserve_final_newline: bool | None = None
    description: str | None = Field(
        default=None,
        max_length=100_000,
    )


class PatchRequestPayload(BaseModel):
    """Canonical multi-file patch request."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
    )

    request_id: UUID = Field(
        default_factory=uuid4
    )
    operations: list[ProposedPatchOperation] = Field(
        min_length=1,
        max_length=DEFAULT_MAX_OPERATIONS,
    )
    dry_run: bool = False
    rollback_on_failure: bool | None = None
    description: str | None = Field(
        default=None,
        max_length=100_000,
    )


@dataclass(frozen=True, slots=True)
class NormalizedPatchOperation:
    """Validated repository-relative patch operation."""

    operation_id: UUID
    operation: PatchOperationType
    path: str
    absolute_path: Path
    destination_path: str | None
    destination_absolute_path: Path | None

    content: str | None
    search_text: str | None
    replacement_text: str | None
    unified_diff: str | None

    start_line: int | None
    end_line: int | None

    expected_sha256: str | None
    expected_occurrences: int | None

    create_if_missing: bool
    ignore_if_missing: bool
    ignore_if_exists: bool
    preserve_final_newline: bool | None
    description: str | None

    source_exists: bool
    destination_exists: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable operation data."""

        return {
            "operation_id": str(self.operation_id),
            "operation": self.operation.value,
            "path": self.path,
            "destination_path": self.destination_path,
            "content": self.content,
            "search_text": self.search_text,
            "replacement_text": self.replacement_text,
            "unified_diff": self.unified_diff,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "expected_sha256": self.expected_sha256,
            "expected_occurrences": (
                self.expected_occurrences
            ),
            "create_if_missing": self.create_if_missing,
            "ignore_if_missing": self.ignore_if_missing,
            "ignore_if_exists": self.ignore_if_exists,
            "preserve_final_newline": (
                self.preserve_final_newline
            ),
            "description": self.description,
            "source_exists": self.source_exists,
            "destination_exists": (
                self.destination_exists
            ),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """Pre-operation file snapshot used for rollback."""

    relative_path: str
    absolute_path: Path
    existed: bool
    content: bytes | None
    mode: int | None
    modified_time_ns: int | None
    is_directory: bool = False


@dataclass(frozen=True, slots=True)
class PreparedFileChange:
    """Computed file state before it is committed to disk."""

    operation: NormalizedPatchOperation
    original_bytes: bytes | None
    resulting_bytes: bytes | None
    original_sha256: str | None
    resulting_sha256: str | None
    original_size_bytes: int
    resulting_size_bytes: int
    changed: bool
    replacement_count: int
    unified_diff_preview: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AppliedFileResult:
    """Result of one patch operation."""

    operation_id: UUID
    operation: PatchOperationType
    path: str
    destination_path: str | None
    status: PatchStatus
    changed: bool
    original_sha256: str | None
    resulting_sha256: str | None
    original_size_bytes: int
    resulting_size_bytes: int
    replacement_count: int
    diff: str
    warnings: tuple[str, ...]
    error: str | None
    started_at: datetime
    completed_at: datetime
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable result data."""

        return {
            "operation_id": str(self.operation_id),
            "operation": self.operation.value,
            "path": self.path,
            "destination_path": self.destination_path,
            "status": self.status.value,
            "changed": self.changed,
            "original_sha256": self.original_sha256,
            "resulting_sha256": self.resulting_sha256,
            "original_size_bytes": (
                self.original_size_bytes
            ),
            "resulting_size_bytes": (
                self.resulting_size_bytes
            ),
            "replacement_count": self.replacement_count,
            "diff": self.diff,
            "warnings": list(self.warnings),
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class PatchTransactionResult:
    """Result of a complete patch transaction."""

    transaction_id: UUID
    request_id: UUID
    repository_root: str
    status: PatchStatus
    dry_run: bool
    rolled_back: bool
    results: tuple[AppliedFileResult, ...]
    warnings: tuple[str, ...]
    error: str | None
    started_at: datetime
    completed_at: datetime
    duration_seconds: float

    @property
    def successful(self) -> bool:
        """Return whether the transaction completed successfully."""

        return self.status in {
            PatchStatus.APPLIED,
            PatchStatus.DRY_RUN,
        }

    @property
    def changed_file_count(self) -> int:
        """Return the number of changed operations."""

        return sum(
            1
            for result in self.results
            if result.changed
        )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable transaction data."""

        return {
            "transaction_id": str(
                self.transaction_id
            ),
            "request_id": str(self.request_id),
            "repository_root": self.repository_root,
            "status": self.status.value,
            "dry_run": self.dry_run,
            "rolled_back": self.rolled_back,
            "successful": self.successful,
            "changed_file_count": (
                self.changed_file_count
            ),
            "results": [
                result.to_dict()
                for result in self.results
            ],
            "warnings": list(self.warnings),
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
        }


@dataclass(slots=True)
class PatchTransactionState:
    """Mutable state maintained while applying a transaction."""

    transaction_id: UUID
    backup_root: Path
    snapshots: dict[str, FileSnapshot] = field(
        default_factory=dict
    )
    created_directories: list[Path] = field(
        default_factory=list
    )
    committed_operations: list[
        NormalizedPatchOperation
    ] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class UnifiedDiffHunk:
    """Parsed unified-diff hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def _sha256_bytes(content: bytes) -> str:
    """Return the SHA-256 digest for bytes."""

    return hashlib.sha256(content).hexdigest()


def _normalize_sha256(
    value: str | None,
) -> str | None:
    """Validate and normalize an optional SHA-256 digest."""

    if value is None:
        return None

    if not isinstance(value, str):
        raise PatchRequestError(
            "expected_sha256 must be a string."
        )

    normalized = value.strip().casefold()

    if not HEX_SHA256_PATTERN.fullmatch(
        normalized
    ):
        raise PatchRequestError(
            "expected_sha256 must contain exactly "
            "64 hexadecimal characters."
        )

    return normalized


def _normalize_operation_type(
    value: str,
) -> PatchOperationType:
    """Normalize a user- or model-generated operation name."""

    if not isinstance(value, str):
        raise PatchRequestError(
            "Patch operation must be a string."
        )

    normalized = value.strip().casefold()
    normalized = normalized.replace(
        "-",
        "_",
    ).replace(
        " ",
        "_",
    )

    normalized = OPERATION_ALIASES.get(
        normalized,
        normalized,
    )

    if normalized not in VALID_OPERATION_VALUES:
        raise PatchRequestError(
            f"Unsupported patch operation: {value}"
        )

    return PatchOperationType(normalized)


def _canonical_path_text(
    value: str,
) -> str:
    """Normalize Windows or POSIX path text to forward slashes."""

    if not isinstance(value, str):
        raise PatchPathError(
            "Patch path must be a string."
        )

    normalized = value.strip()

    if not normalized:
        raise PatchPathError(
            "Patch path cannot be empty."
        )

    if len(normalized) > DEFAULT_MAX_PATH_CHARACTERS:
        raise PatchPathError(
            "Patch path exceeds the maximum permitted length."
        )

    if CONTROL_CHARACTER_PATTERN.search(normalized):
        raise PatchPathError(
            "Patch path contains invalid control characters."
        )

    normalized = normalized.replace("\\", "/")
    normalized = MULTIPLE_SLASH_PATTERN.sub(
        "/",
        normalized,
    )

    while normalized.startswith("./"):
        normalized = normalized[2:]

    return normalized.rstrip("/")


def _is_relative_to(
    path: Path,
    root: Path,
) -> bool:
    """Return whether path is inside root."""

    try:
        path.relative_to(root)
    except ValueError:
        return False

    return True


def _resolve_repository_root(
    repository_root: str | os.PathLike[str] | Path,
) -> Path:
    """Resolve and validate the repository root."""

    try:
        resolved = Path(
            repository_root
        ).expanduser().resolve(strict=True)
    except (
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise PatchConfigurationError(
            "The repository root could not be resolved."
        ) from exc

    if not resolved.is_dir():
        raise PatchConfigurationError(
            f"The repository root is not a directory: {resolved}"
        )

    return resolved


def _resolve_repository_path(
    value: str,
    *,
    repository_root: Path,
    require_exists: bool,
    reject_protected: bool,
    reject_symbolic_links: bool,
) -> tuple[str, Path, bool, str | None]:
    """Resolve and validate a repository-relative patch path."""

    normalized = _canonical_path_text(value)

    normalized_root = str(
        repository_root
    ).replace("\\", "/").rstrip("/")

    if normalized.casefold() == normalized_root.casefold():
        raise PatchPathError(
            "A patch cannot target the repository root."
        )

    if normalized.casefold().startswith(
        f"{normalized_root.casefold()}/"
    ):
        normalized = normalized[
            len(normalized_root) + 1:
        ]

    if WINDOWS_DRIVE_PATTERN.match(normalized):
        absolute_candidate = Path(
            str(PureWindowsPath(normalized))
        ).resolve(strict=False)

        if not _is_relative_to(
            absolute_candidate,
            repository_root,
        ):
            raise PatchPathError(
                "Absolute patch path is outside the repository: "
                f"{value}"
            )

        relative_path = absolute_candidate.relative_to(
            repository_root
        )

    elif normalized.startswith("/"):
        absolute_candidate = Path(
            normalized
        ).resolve(strict=False)

        if not _is_relative_to(
            absolute_candidate,
            repository_root,
        ):
            raise PatchPathError(
                "Absolute patch path is outside the repository: "
                f"{value}"
            )

        relative_path = absolute_candidate.relative_to(
            repository_root
        )

    else:
        pure_path = PurePosixPath(normalized)

        if not pure_path.parts:
            raise PatchPathError(
                "Patch path cannot be empty."
            )

        if any(
            part in {"", ".", ".."}
            for part in pure_path.parts
        ):
            raise PatchPathError(
                "Patch path contains an unsafe path segment: "
                f"{value}"
            )

        relative_path = Path(*pure_path.parts)

    try:
        resolved_path = (
            repository_root / relative_path
        ).resolve(strict=False)
    except (
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise PatchPathError(
            f"Patch path could not be resolved: {value}"
        ) from exc

    if not _is_relative_to(
        resolved_path,
        repository_root,
    ):
        raise PatchPathError(
            "Patch path escapes the repository: "
            f"{value}"
        )

    try:
        decision = evaluate_safe_path(
            repository_root=repository_root,
            requested_path=relative_path,
            allow_absolute=False,
            require_exists=require_exists,
            allow_repository_root=False,
            check_blocked=reject_protected,
        )
    except (
        UnsafePathError,
        BlockedFileError,
    ) as exc:
        raise PatchPathError(str(exc)) from exc

    allowed = getattr(
        decision,
        "allowed",
        True,
    )

    message = getattr(
        decision,
        "message",
        None,
    )

    if not allowed and reject_protected:
        raise PatchPathError(
            message
            or f"Patch path is not permitted: {value}"
        )

    warning = (
        str(message)
        if not allowed and message
        else None
    )

    if reject_symbolic_links:
        current = repository_root

        for part in relative_path.parts:
            current = current / part

            if current.exists() and current.is_symlink():
                raise PatchPathError(
                    "Symbolic-link patch targets are not permitted: "
                    f"{relative_path.as_posix()}"
                )

    return (
        relative_path.as_posix(),
        resolved_path,
        resolved_path.exists(),
        warning,
    )


def _normalize_text_input(
    value: str | None,
    *,
    field_name: str,
    required: bool,
    maximum_characters: int,
) -> str | None:
    """Validate an optional patch text field."""

    if value is None:
        if required:
            raise PatchRequestError(
                f"{field_name} is required."
            )

        return None

    if not isinstance(value, str):
        raise PatchRequestError(
            f"{field_name} must be a string."
        )

    if len(value) > maximum_characters:
        raise PatchRequestError(
            f"{field_name} exceeds the maximum permitted length."
        )

    if "\x00" in value:
        raise PatchRequestError(
            f"{field_name} contains a null byte."
        )

    return value


def _detect_newline(text: str) -> str:
    """Detect the dominant newline sequence in text."""

    crlf_count = text.count("\r\n")
    without_crlf = text.replace("\r\n", "")
    lf_count = without_crlf.count("\n")
    cr_count = without_crlf.count("\r")

    if crlf_count >= lf_count and crlf_count >= cr_count:
        if crlf_count > 0:
            return WINDOWS_NEWLINE

    if lf_count >= cr_count and lf_count > 0:
        return DEFAULT_NEWLINE

    if cr_count > 0:
        return "\r"

    return DEFAULT_NEWLINE


def _normalize_newlines(
    text: str,
    newline: str,
) -> str:
    """Convert all newline forms to the selected newline sequence."""

    canonical = text.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    if newline == "\n":
        return canonical

    return canonical.replace(
        "\n",
        newline,
    )


def _has_final_newline(text: str) -> bool:
    """Return whether text ends in any newline sequence."""

    return text.endswith(("\n", "\r"))


def _set_final_newline(
    text: str,
    *,
    should_have_final_newline: bool,
    newline: str,
) -> str:
    """Add or remove the final newline deterministically."""

    without_final_newline = text.rstrip("\r\n")

    if should_have_final_newline:
        return without_final_newline + newline

    return without_final_newline


def _decode_utf8(
    content: bytes,
    *,
    path: Path,
) -> tuple[str, bool]:
    """Decode UTF-8 or UTF-8-with-BOM bytes."""

    had_bom = content.startswith(UTF8_BOM)

    try:
        decoded = content.decode(
            "utf-8-sig"
            if had_bom
            else "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise PatchEncodingError(
            "File is not valid UTF-8 text and cannot be patched: "
            f"{path}"
        ) from exc

    if "\x00" in decoded:
        raise PatchEncodingError(
            "File appears to be binary and cannot be patched as text: "
            f"{path}"
        )

    return decoded, had_bom


def _encode_utf8(text: str) -> bytes:
    """Encode text as UTF-8 without a BOM."""

    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PatchEncodingError(
            "Resulting text could not be encoded as UTF-8."
        ) from exc


def _read_file_bytes(
    path: Path,
    *,
    maximum_bytes: int,
) -> bytes:
    """Read a bounded regular file."""

    try:
        file_stat = path.stat()
    except OSError as exc:
        raise PatchOperationError(
            f"Could not inspect source file: {path}"
        ) from exc

    if not stat.S_ISREG(file_stat.st_mode):
        raise PatchOperationError(
            f"Patch target is not a regular file: {path}"
        )

    if file_stat.st_size > maximum_bytes:
        raise PatchOperationError(
            "Patch target exceeds the maximum permitted file size: "
            f"{path}"
        )

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PatchOperationError(
            f"Could not read source file: {path}"
        ) from exc

    if len(content) > maximum_bytes:
        raise PatchOperationError(
            "Patch target exceeds the maximum permitted file size: "
            f"{path}"
        )

    return content


def _read_utf8_file(
    path: Path,
    *,
    maximum_bytes: int,
) -> tuple[str, bytes, bool]:
    """Read and decode a bounded UTF-8 source file."""

    raw_content = _read_file_bytes(
        path,
        maximum_bytes=maximum_bytes,
    )

    text, had_bom = _decode_utf8(
        raw_content,
        path=path,
    )

    return text, raw_content, had_bom


def _write_file_atomic(
    path: Path,
    content: bytes,
    *,
    preserve_mode_from: Path | None,
    preserve_file_permissions: bool,
    fsync_writes: bool,
) -> None:
    """Atomically write bytes using a temporary file and os.replace."""

    parent = path.parent

    try:
        parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as exc:
        raise PatchOperationError(
            f"Could not create parent directory: {parent}"
        ) from exc

    source_mode: int | None = None

    if (
        preserve_file_permissions
        and preserve_mode_from is not None
        and preserve_mode_from.exists()
    ):
        try:
            source_mode = stat.S_IMODE(
                preserve_mode_from.stat().st_mode
            )
        except OSError:
            source_mode = None

    temporary_path: Path | None = None

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=DEFAULT_TEMP_FILE_PREFIX,
            suffix=".tmp",
            dir=str(parent),
        )

        temporary_path = Path(temporary_name)

        with os.fdopen(
            file_descriptor,
            mode="wb",
            closefd=True,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()

            if fsync_writes:
                os.fsync(temporary_file.fileno())

        if source_mode is not None:
            os.chmod(
                temporary_path,
                source_mode,
            )

        os.replace(
            temporary_path,
            path,
        )

        temporary_path = None

        if fsync_writes:
            try:
                directory_descriptor = os.open(
                    str(parent),
                    os.O_RDONLY,
                )
            except OSError:
                directory_descriptor = None

            if directory_descriptor is not None:
                try:
                    os.fsync(directory_descriptor)
                except OSError:
                    pass
                finally:
                    os.close(directory_descriptor)

    except OSError as exc:
        raise PatchOperationError(
            f"Atomic file write failed: {path}"
        ) from exc

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            try:
                temporary_path.unlink()
            except OSError:
                LOGGER.warning(
                    "Could not remove temporary patch file: %s",
                    temporary_path,
                )


def _create_unified_diff(
    original_text: str,
    resulting_text: str,
    *,
    path: str,
    destination_path: str | None = None,
) -> str:
    """Create a readable unified diff preview."""

    old_name = f"a/{path}"
    new_name = (
        f"b/{destination_path}"
        if destination_path is not None
        else f"b/{path}"
    )

    original_lines = original_text.splitlines(
        keepends=True
    )
    resulting_lines = resulting_text.splitlines(
        keepends=True
    )

    return "".join(
        difflib.unified_diff(
            original_lines,
            resulting_lines,
            fromfile=old_name,
            tofile=new_name,
            lineterm="\n",
        )
    )


def _create_binary_change_description(
    *,
    path: str,
    operation: PatchOperationType,
    original_size: int,
    resulting_size: int,
) -> str:
    """Create a textual description for non-text deletion or rename."""

    return (
        f"{operation.value}: {path}\n"
        f"original size: {original_size} bytes\n"
        f"resulting size: {resulting_size} bytes\n"
    )


def _split_lines_without_endings(
    text: str,
) -> list[str]:
    """Split text into logical lines without newline suffixes."""

    return text.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    ).split("\n")


def _join_logical_lines(
    lines: Sequence[str],
    *,
    newline: str,
) -> str:
    """Join logical lines using a selected newline."""

    return newline.join(lines)


def _replace_text_exact(
    original: str,
    *,
    search_text: str,
    replacement_text: str,
    expected_occurrences: int | None,
    maximum_replacements: int,
) -> tuple[str, int]:
    """Replace exact text with strict ambiguity checking."""

    if search_text == "":
        raise PatchRequestError(
            "search_text cannot be empty for replace_text."
        )

    occurrence_count = original.count(
        search_text
    )

    if expected_occurrences is not None:
        if occurrence_count != expected_occurrences:
            raise PatchConflictError(
                "Exact replacement occurrence count mismatch. "
                f"Expected {expected_occurrences}, "
                f"found {occurrence_count}."
            )
    elif occurrence_count != 1:
        raise PatchConflictError(
            "Exact replacement requires one unique occurrence when "
            "expected_occurrences is omitted. "
            f"Found {occurrence_count}."
        )

    if occurrence_count > maximum_replacements:
        raise PatchConflictError(
            "Replacement count exceeds the configured maximum."
        )

    if occurrence_count == 0:
        raise PatchConflictError(
            "search_text was not found in the source file."
        )

    return (
        original.replace(
            search_text,
            replacement_text,
        ),
        occurrence_count,
    )


def _insert_relative_to_text(
    original: str,
    *,
    anchor_text: str,
    inserted_text: str,
    before: bool,
    expected_occurrences: int | None,
    maximum_replacements: int,
) -> tuple[str, int]:
    """Insert text before or after exact anchor occurrences."""

    if anchor_text == "":
        raise PatchRequestError(
            "Anchor text cannot be empty."
        )

    occurrence_count = original.count(
        anchor_text
    )

    if expected_occurrences is not None:
        if occurrence_count != expected_occurrences:
            raise PatchConflictError(
                "Anchor occurrence count mismatch. "
                f"Expected {expected_occurrences}, "
                f"found {occurrence_count}."
            )
    elif occurrence_count != 1:
        raise PatchConflictError(
            "Insertion requires one unique anchor when "
            "expected_occurrences is omitted. "
            f"Found {occurrence_count}."
        )

    if occurrence_count == 0:
        raise PatchConflictError(
            "Insertion anchor was not found."
        )

    if occurrence_count > maximum_replacements:
        raise PatchConflictError(
            "Insertion count exceeds the configured maximum."
        )

    replacement = (
        inserted_text + anchor_text
        if before
        else anchor_text + inserted_text
    )

    return (
        original.replace(
            anchor_text,
            replacement,
        ),
        occurrence_count,
    )


def _replace_line_range(
    original: str,
    *,
    replacement_text: str,
    start_line: int,
    end_line: int,
    newline: str,
) -> tuple[str, int]:
    """Replace an inclusive one-based line range."""

    if end_line < start_line:
        raise PatchRequestError(
            "end_line cannot be lower than start_line."
        )

    had_final_newline = _has_final_newline(
        original
    )

    lines = _split_lines_without_endings(
        original
    )

    if had_final_newline and lines and lines[-1] == "":
        lines = lines[:-1]

    total_lines = len(lines)

    if start_line > total_lines:
        raise PatchConflictError(
            "start_line is outside the source file. "
            f"File has {total_lines} lines."
        )

    if end_line > total_lines:
        raise PatchConflictError(
            "end_line is outside the source file. "
            f"File has {total_lines} lines."
        )

    replacement_lines = _split_lines_without_endings(
        replacement_text
    )

    if (
        replacement_text.endswith(
            ("\n", "\r")
        )
        and replacement_lines
        and replacement_lines[-1] == ""
    ):
        replacement_lines = replacement_lines[:-1]

    start_index = start_line - 1
    end_index = end_line

    result_lines = [
        *lines[:start_index],
        *replacement_lines,
        *lines[end_index:],
    ]

    result = _join_logical_lines(
        result_lines,
        newline=newline,
    )

    if had_final_newline:
        result += newline

    return result, end_line - start_line + 1


def _parse_unified_diff(
    diff_text: str,
) -> tuple[UnifiedDiffHunk, ...]:
    """Parse unified-diff hunks without trusting file header paths."""

    normalized = diff_text.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    lines = normalized.splitlines(
        keepends=True
    )

    hunks: list[UnifiedDiffHunk] = []
    current_header: re.Match[str] | None = None
    current_lines: list[str] = []

    def finish_current_hunk() -> None:
        nonlocal current_header
        nonlocal current_lines

        if current_header is None:
            return

        old_start = int(
            current_header.group("old_start")
        )
        old_count = int(
            current_header.group("old_count")
            or "1"
        )
        new_start = int(
            current_header.group("new_start")
        )
        new_count = int(
            current_header.group("new_count")
            or "1"
        )

        hunks.append(
            UnifiedDiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=tuple(current_lines),
            )
        )

        current_header = None
        current_lines = []

    for raw_line in lines:
        line_without_ending = raw_line.rstrip(
            "\r\n"
        )

        header_match = (
            UNIFIED_DIFF_HEADER_PATTERN.match(
                line_without_ending
            )
        )

        if header_match is not None:
            finish_current_hunk()
            current_header = header_match
            continue

        if current_header is None:
            if line_without_ending.startswith(
                ("--- ", "+++ ", "diff ", "index ")
            ):
                continue

            if line_without_ending == "":
                continue

            raise PatchRequestError(
                "Unified diff contains content outside a hunk."
            )

        if raw_line.startswith(
            (" ", "+", "-")
        ):
            current_lines.append(raw_line)
            continue

        if raw_line.startswith(
            "\\ No newline at end of file"
        ):
            continue

        raise PatchRequestError(
            "Unified diff contains an invalid hunk line."
        )

    finish_current_hunk()

    if not hunks:
        raise PatchRequestError(
            "Unified diff does not contain any hunks."
        )

    return tuple(hunks)


def _apply_unified_diff(
    original: str,
    *,
    diff_text: str,
) -> tuple[str, int]:
    """Apply validated unified-diff hunks to source text."""

    hunks = _parse_unified_diff(
        diff_text
    )

    original_normalized = original.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    original_lines = original_normalized.splitlines(
        keepends=True
    )

    result_lines: list[str] = []
    source_index = 0
    applied_change_count = 0

    for hunk in hunks:
        hunk_start_index = max(
            hunk.old_start - 1,
            0,
        )

        if hunk_start_index < source_index:
            raise PatchConflictError(
                "Unified diff contains overlapping or out-of-order hunks."
            )

        if hunk_start_index > len(original_lines):
            raise PatchConflictError(
                "Unified diff hunk starts beyond the source file."
            )

        result_lines.extend(
            original_lines[
                source_index:hunk_start_index
            ]
        )

        source_index = hunk_start_index
        consumed_old_lines = 0
        produced_new_lines = 0

        for diff_line in hunk.lines:
            prefix = diff_line[:1]
            payload = diff_line[1:]

            if prefix == " ":
                if source_index >= len(
                    original_lines
                ):
                    raise PatchConflictError(
                        "Unified diff context exceeds the source file."
                    )

                if (
                    original_lines[source_index]
                    != payload
                ):
                    raise PatchConflictError(
                        "Unified diff context does not match "
                        "the source file."
                    )

                result_lines.append(
                    original_lines[source_index]
                )
                source_index += 1
                consumed_old_lines += 1
                produced_new_lines += 1

            elif prefix == "-":
                if source_index >= len(
                    original_lines
                ):
                    raise PatchConflictError(
                        "Unified diff deletion exceeds the source file."
                    )

                if (
                    original_lines[source_index]
                    != payload
                ):
                    raise PatchConflictError(
                        "Unified diff deletion does not match "
                        "the source file."
                    )

                source_index += 1
                consumed_old_lines += 1
                applied_change_count += 1

            elif prefix == "+":
                result_lines.append(payload)
                produced_new_lines += 1
                applied_change_count += 1

            else:
                raise PatchRequestError(
                    "Unified diff contains an unsupported line prefix."
                )

        if consumed_old_lines != hunk.old_count:
            raise PatchConflictError(
                "Unified diff old-line count does not match "
                "the hunk header."
            )

        if produced_new_lines != hunk.new_count:
            raise PatchConflictError(
                "Unified diff new-line count does not match "
                "the hunk header."
            )

    result_lines.extend(
        original_lines[source_index:]
    )

    return "".join(result_lines), applied_change_count


def _find_model_class(
    candidate_names: Sequence[str],
) -> type[BaseModel] | None:
    """Find the first matching Pydantic model in models.py."""

    for name in candidate_names:
        candidate = getattr(
            code_builder_models,
            name,
            None,
        )

        if (
            isinstance(candidate, type)
            and issubclass(candidate, BaseModel)
        ):
            return candidate

    return None


def _filter_model_payload(
    model_class: type[BaseModel],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter data to fields accepted by a models.py Pydantic model."""

    model_fields = getattr(
        model_class,
        "model_fields",
        {},
    )

    field_names = set(
        model_fields.keys()
    )

    if not field_names:
        return dict(payload)

    return {
        key: value
        for key, value in payload.items()
        if key in field_names
    }


def _model_or_mapping_to_dict(
    value: Any,
) -> dict[str, Any]:
    """Convert a Pydantic model or mapping to a mutable dictionary."""

    if isinstance(value, BaseModel):
        return value.model_dump(
            mode="python",
            exclude_none=False,
        )

    if isinstance(value, Mapping):
        return dict(value)

    result: dict[str, Any] = {}

    for name in dir(value):
        if name.startswith("_"):
            continue

        try:
            attribute = getattr(
                value,
                name,
            )
        except Exception:
            continue

        if callable(attribute):
            continue

        result[name] = attribute

    return result


def _first_value(
    value: Any,
    *names: str,
    default: Any = None,
) -> Any:
    """Return the first matching key or attribute."""

    for name in names:
        if isinstance(value, Mapping):
            if name in value:
                return value[name]
        elif hasattr(value, name):
            try:
                return getattr(value, name)
            except Exception:
                continue

    return default


class PatchService:
    """Safely validate, prepare, and apply repository patches."""

    def __init__(
        self,
        *,
        repository_root: str | os.PathLike[str] | Path,
        configuration: PatchConfiguration | None = None,
    ) -> None:
        """Initialize PatchService for one repository."""

        self.repository_root = (
            _resolve_repository_root(
                repository_root
            )
        )
        self.configuration = (
            configuration
            if configuration is not None
            else PatchConfiguration()
        )

    def _transaction_storage_root(self) -> Path:
        """Return the transaction-backup storage directory."""

        root = (
            self.repository_root
            / self.configuration.transaction_directory_name
            / self.configuration.backup_directory_name
        )

        resolved = root.resolve(
            strict=False
        )

        if not _is_relative_to(
            resolved,
            self.repository_root,
        ):
            raise PatchConfigurationError(
                "Transaction storage path escapes the repository."
            )

        return resolved

    def normalize_request(
        self,
        request: (
            PatchRequestPayload
            | BaseModel
            | Mapping[str, Any]
            | Sequence[Any]
        ),
        *,
        dry_run: bool | None = None,
    ) -> PatchRequestPayload:
        """Convert a models.py request or raw mapping to canonical form."""

        if isinstance(
            request,
            PatchRequestPayload,
        ):
            payload = request.model_dump(
                mode="python"
            )

        elif isinstance(
            request,
            Sequence,
        ) and not isinstance(
            request,
            (str, bytes, bytearray),
        ):
            payload = {
                "operations": [
                    _model_or_mapping_to_dict(item)
                    for item in request
                ]
            }

        else:
            payload = _model_or_mapping_to_dict(
                request
            )

        operations_value = _first_value(
            payload,
            "operations",
            "patches",
            "changes",
            "file_changes",
            default=None,
        )

        if operations_value is None:
            raise PatchRequestError(
                "Patch request does not contain operations."
            )

        if isinstance(
            operations_value,
            (str, bytes, bytearray),
        ):
            raise PatchRequestError(
                "Patch operations must be a sequence."
            )

        normalized_operations: list[
            ProposedPatchOperation
        ] = []

        try:
            operation_values = list(
                operations_value
            )
        except TypeError as exc:
            raise PatchRequestError(
                "Patch operations are not iterable."
            ) from exc

        if not operation_values:
            raise PatchRequestError(
                "Patch request must contain at least one operation."
            )

        if (
            len(operation_values)
            > self.configuration.maximum_operations
        ):
            raise PatchRequestError(
                "Patch request exceeds the configured operation limit."
            )

        for raw_operation in operation_values:
            raw = _model_or_mapping_to_dict(
                raw_operation
            )

            canonical = {
                "operation_id": _first_value(
                    raw,
                    "operation_id",
                    "id",
                    "patch_id",
                    "change_id",
                    default=uuid4(),
                ),
                "operation": _first_value(
                    raw,
                    "operation",
                    "type",
                    "change_type",
                    "action",
                    default=None,
                ),
                "path": _first_value(
                    raw,
                    "path",
                    "file_path",
                    "relative_path",
                    "target_path",
                    default=None,
                ),
                "destination_path": _first_value(
                    raw,
                    "destination_path",
                    "new_path",
                    "target_destination",
                    default=None,
                ),
                "content": _first_value(
                    raw,
                    "content",
                    "new_content",
                    "proposed_content",
                    "code",
                    default=None,
                ),
                "search_text": _first_value(
                    raw,
                    "search_text",
                    "old_text",
                    "find",
                    "target_text",
                    default=None,
                ),
                "replacement_text": _first_value(
                    raw,
                    "replacement_text",
                    "new_text",
                    "replace_with",
                    default=None,
                ),
                "unified_diff": _first_value(
                    raw,
                    "unified_diff",
                    "diff",
                    "patch",
                    default=None,
                ),
                "start_line": _first_value(
                    raw,
                    "start_line",
                    "line_start",
                    default=None,
                ),
                "end_line": _first_value(
                    raw,
                    "end_line",
                    "line_end",
                    default=None,
                ),
                "expected_sha256": _first_value(
                    raw,
                    "expected_sha256",
                    "source_sha256",
                    "original_sha256",
                    "expected_hash",
                    default=None,
                ),
                "expected_occurrences": _first_value(
                    raw,
                    "expected_occurrences",
                    "occurrences",
                    "expected_matches",
                    default=None,
                ),
                "create_if_missing": bool(
                    _first_value(
                        raw,
                        "create_if_missing",
                        default=False,
                    )
                ),
                "ignore_if_missing": bool(
                    _first_value(
                        raw,
                        "ignore_if_missing",
                        default=False,
                    )
                ),
                "ignore_if_exists": bool(
                    _first_value(
                        raw,
                        "ignore_if_exists",
                        default=False,
                    )
                ),
                "preserve_final_newline": _first_value(
                    raw,
                    "preserve_final_newline",
                    default=None,
                ),
                "description": _first_value(
                    raw,
                    "description",
                    "summary",
                    "reason",
                    default=None,
                ),
            }

            try:
                normalized_operations.append(
                    ProposedPatchOperation.model_validate(
                        canonical
                    )
                )
            except ValidationError as exc:
                raise PatchRequestError(
                    "A patch operation does not match the "
                    "required schema."
                ) from exc

        request_identifier = _first_value(
            payload,
            "request_id",
            "id",
            "patch_request_id",
            default=uuid4(),
        )

        requested_dry_run = bool(
            _first_value(
                payload,
                "dry_run",
                "preview_only",
                default=False,
            )
        )

        if dry_run is not None:
            requested_dry_run = bool(dry_run)

        canonical_request = {
            "request_id": request_identifier,
            "operations": normalized_operations,
            "dry_run": requested_dry_run,
            "rollback_on_failure": _first_value(
                payload,
                "rollback_on_failure",
                default=None,
            ),
            "description": _first_value(
                payload,
                "description",
                "summary",
                default=None,
            ),
        }

        try:
            return PatchRequestPayload.model_validate(
                canonical_request
            )
        except ValidationError as exc:
            raise PatchRequestError(
                "Patch request does not match the required schema."
            ) from exc

    def _validate_operation_fields(
        self,
        operation: ProposedPatchOperation,
        operation_type: PatchOperationType,
    ) -> None:
        """Validate fields required or prohibited by an operation type."""

        content_required = operation_type in {
            PatchOperationType.CREATE,
            PatchOperationType.REPLACE_FILE,
            PatchOperationType.APPEND_TEXT,
            PatchOperationType.PREPEND_TEXT,
        }

        if content_required:
            _normalize_text_input(
                operation.content,
                field_name="content",
                required=True,
                maximum_characters=MAX_TEXT_CHARACTERS,
            )

        if operation_type == PatchOperationType.REPLACE_TEXT:
            _normalize_text_input(
                operation.search_text,
                field_name="search_text",
                required=True,
                maximum_characters=(
                    self.configuration
                    .maximum_search_characters
                ),
            )
            _normalize_text_input(
                operation.replacement_text,
                field_name="replacement_text",
                required=True,
                maximum_characters=MAX_TEXT_CHARACTERS,
            )

        if operation_type in {
            PatchOperationType.INSERT_BEFORE,
            PatchOperationType.INSERT_AFTER,
        }:
            _normalize_text_input(
                operation.search_text,
                field_name="search_text",
                required=True,
                maximum_characters=(
                    self.configuration
                    .maximum_search_characters
                ),
            )
            _normalize_text_input(
                operation.content,
                field_name="content",
                required=True,
                maximum_characters=MAX_TEXT_CHARACTERS,
            )

        if operation_type == PatchOperationType.REPLACE_RANGE:
            _normalize_text_input(
                operation.content,
                field_name="content",
                required=True,
                maximum_characters=MAX_TEXT_CHARACTERS,
            )

            if (
                operation.start_line is None
                or operation.end_line is None
            ):
                raise PatchRequestError(
                    "replace_range requires start_line and end_line."
                )

            if operation.end_line < operation.start_line:
                raise PatchRequestError(
                    "replace_range end_line cannot be lower "
                    "than start_line."
                )

        if operation_type == PatchOperationType.UNIFIED_DIFF:
            diff_text = _normalize_text_input(
                operation.unified_diff,
                field_name="unified_diff",
                required=True,
                maximum_characters=MAX_TEXT_CHARACTERS,
            )

            if diff_text is None:
                raise PatchRequestError(
                    "unified_diff is required."
                )

            if len(
                diff_text.encode("utf-8")
            ) > self.configuration.maximum_patch_bytes:
                raise PatchRequestError(
                    "Unified diff exceeds the maximum patch size."
                )

            _parse_unified_diff(diff_text)

        if operation_type == PatchOperationType.RENAME:
            if not operation.destination_path:
                raise PatchRequestError(
                    "rename requires destination_path."
                )

        elif operation.destination_path is not None:
            raise PatchRequestError(
                "destination_path is only valid for rename operations."
            )

        if (
            operation.expected_occurrences is not None
            and operation_type
            not in {
                PatchOperationType.REPLACE_TEXT,
                PatchOperationType.INSERT_BEFORE,
                PatchOperationType.INSERT_AFTER,
            }
        ):
            raise PatchRequestError(
                "expected_occurrences is only valid for exact "
                "text replacement or insertion operations."
            )

    def normalize_operation(
        self,
        operation: ProposedPatchOperation,
    ) -> NormalizedPatchOperation:
        """Validate and normalize one patch operation."""

        operation_type = _normalize_operation_type(
            operation.operation
        )

        self._validate_operation_fields(
            operation,
            operation_type,
        )

        if (
            operation_type == PatchOperationType.CREATE
            and not self.configuration.allow_create
        ):
            raise PatchRequestError(
                "Create operations are disabled."
            )

        if (
            operation_type == PatchOperationType.DELETE
            and not self.configuration.allow_delete
        ):
            raise PatchRequestError(
                "Delete operations are disabled."
            )

        if (
            operation_type == PatchOperationType.RENAME
            and not self.configuration.allow_rename
        ):
            raise PatchRequestError(
                "Rename operations are disabled."
            )

        source_may_not_exist = (
            operation_type == PatchOperationType.CREATE
            or operation.create_if_missing
            or operation.ignore_if_missing
        )

        (
            relative_path,
            absolute_path,
            source_exists,
            path_warning,
        ) = _resolve_repository_path(
            operation.path,
            repository_root=self.repository_root,
            require_exists=not source_may_not_exist,
            reject_protected=(
                self.configuration.reject_protected_paths
            ),
            reject_symbolic_links=(
                self.configuration.reject_symbolic_links
            ),
        )

        warnings: list[str] = []

        if path_warning:
            warnings.append(path_warning)

        destination_relative: str | None = None
        destination_absolute: Path | None = None
        destination_exists = False

        if operation_type == PatchOperationType.RENAME:
            if operation.destination_path is None:
                raise PatchRequestError(
                    "rename requires destination_path."
                )

            (
                destination_relative,
                destination_absolute,
                destination_exists,
                destination_warning,
            ) = _resolve_repository_path(
                operation.destination_path,
                repository_root=self.repository_root,
                require_exists=False,
                reject_protected=(
                    self.configuration
                    .reject_protected_paths
                ),
                reject_symbolic_links=(
                    self.configuration
                    .reject_symbolic_links
                ),
            )

            if destination_warning:
                warnings.append(
                    destination_warning
                )

            if (
                destination_relative.casefold()
                == relative_path.casefold()
            ):
                raise PatchRequestError(
                    "Rename source and destination are identical."
                )

        expected_sha256 = _normalize_sha256(
            operation.expected_sha256
        )

        existing_file_operation = (
            operation_type
            not in {
                PatchOperationType.CREATE,
            }
        )

        if (
            existing_file_operation
            and source_exists
            and self.configuration
            .require_expected_hash_for_existing_files
            and expected_sha256 is None
        ):
            raise PatchRequestError(
                "expected_sha256 is required for existing-file "
                f"operation: {relative_path}"
            )

        if (
            operation_type == PatchOperationType.CREATE
            and source_exists
            and not (
                operation.ignore_if_exists
                or self.configuration
                .allow_overwrite_on_create
            )
        ):
            raise PatchConflictError(
                "Create operation targets an existing file: "
                f"{relative_path}"
            )

        if (
            operation_type == PatchOperationType.RENAME
            and destination_exists
            and not self.configuration
            .allow_overwrite_on_rename
        ):
            raise PatchConflictError(
                "Rename destination already exists: "
                f"{destination_relative}"
            )

        normalized_content = _normalize_text_input(
            operation.content,
            field_name="content",
            required=False,
            maximum_characters=MAX_TEXT_CHARACTERS,
        )
        normalized_search_text = _normalize_text_input(
            operation.search_text,
            field_name="search_text",
            required=False,
            maximum_characters=(
                self.configuration
                .maximum_search_characters
            ),
        )
        normalized_replacement_text = _normalize_text_input(
            operation.replacement_text,
            field_name="replacement_text",
            required=False,
            maximum_characters=MAX_TEXT_CHARACTERS,
        )
        normalized_diff = _normalize_text_input(
            operation.unified_diff,
            field_name="unified_diff",
            required=False,
            maximum_characters=MAX_TEXT_CHARACTERS,
        )

        return NormalizedPatchOperation(
            operation_id=operation.operation_id,
            operation=operation_type,
            path=relative_path,
            absolute_path=absolute_path,
            destination_path=destination_relative,
            destination_absolute_path=(
                destination_absolute
            ),
            content=normalized_content,
            search_text=normalized_search_text,
            replacement_text=(
                normalized_replacement_text
            ),
            unified_diff=normalized_diff,
            start_line=operation.start_line,
            end_line=operation.end_line,
            expected_sha256=expected_sha256,
            expected_occurrences=(
                operation.expected_occurrences
            ),
            create_if_missing=(
                operation.create_if_missing
            ),
            ignore_if_missing=(
                operation.ignore_if_missing
            ),
            ignore_if_exists=(
                operation.ignore_if_exists
            ),
            preserve_final_newline=(
                operation.preserve_final_newline
            ),
            description=operation.description,
            source_exists=source_exists,
            destination_exists=destination_exists,
            warnings=tuple(warnings),
        )

    def normalize_operations(
        self,
        request: PatchRequestPayload,
    ) -> tuple[NormalizedPatchOperation, ...]:
        """Normalize all operations and reject path conflicts."""

        normalized: list[
            NormalizedPatchOperation
        ] = []

        claimed_paths: dict[str, UUID] = {}
        destination_paths: dict[str, UUID] = {}

        for operation in request.operations:
            normalized_operation = (
                self.normalize_operation(operation)
            )

            source_key = (
                normalized_operation.path.casefold()
            )

            if source_key in claimed_paths:
                raise PatchConflictError(
                    "Multiple patch operations target the same path: "
                    f"{normalized_operation.path}"
                )

            if source_key in destination_paths:
                raise PatchConflictError(
                    "Patch source conflicts with a rename destination: "
                    f"{normalized_operation.path}"
                )

            claimed_paths[source_key] = (
                normalized_operation.operation_id
            )

            if (
                normalized_operation.destination_path
                is not None
            ):
                destination_key = (
                    normalized_operation
                    .destination_path
                    .casefold()
                )

                if (
                    destination_key in claimed_paths
                    or destination_key
                    in destination_paths
                ):
                    raise PatchConflictError(
                        "Rename destination conflicts with another "
                        "operation: "
                        f"{normalized_operation.destination_path}"
                    )

                destination_paths[destination_key] = (
                    normalized_operation.operation_id
                )

            normalized.append(
                normalized_operation
            )

        return tuple(normalized)

    def _select_output_newline(
        self,
        original_text: str | None,
    ) -> str:
        """Select output newline according to configuration."""

        if (
            self.configuration.newline_mode
            == NewlineMode.LF
        ):
            return DEFAULT_NEWLINE

        if (
            self.configuration.newline_mode
            == NewlineMode.CRLF
        ):
            return WINDOWS_NEWLINE

        if original_text is None:
            return DEFAULT_NEWLINE

        return _detect_newline(original_text)

    def _select_final_newline_behavior(
        self,
        operation: NormalizedPatchOperation,
        original_text: str | None,
        resulting_text: str,
    ) -> bool:
        """Determine whether resulting text should end in a newline."""

        if (
            operation.preserve_final_newline
            is not None
        ):
            return bool(
                operation.preserve_final_newline
            )

        if not self.configuration.preserve_final_newline:
            return _has_final_newline(
                resulting_text
            )

        if original_text is None:
            return _has_final_newline(
                resulting_text
            )

        return _has_final_newline(
            original_text
        )

    def _verify_expected_hash(
        self,
        operation: NormalizedPatchOperation,
        original_bytes: bytes,
    ) -> str:
        """Verify optional optimistic-lock hash."""

        actual_hash = _sha256_bytes(
            original_bytes
        )

        if (
            operation.expected_sha256 is not None
            and actual_hash
            != operation.expected_sha256
        ):
            raise PatchHashMismatchError(
                "Source file hash mismatch for "
                f"{operation.path}. Expected "
                f"{operation.expected_sha256}, "
                f"found {actual_hash}."
            )

        return actual_hash

    def _prepare_text_result(
        self,
        *,
        operation: NormalizedPatchOperation,
        original_text: str | None,
    ) -> tuple[str, int]:
        """Compute resulting text for one text operation."""

        operation_type = operation.operation
        newline = self._select_output_newline(
            original_text
        )

        source_text = (
            original_text
            if original_text is not None
            else ""
        )

        replacement_count = 0

        if operation_type in {
            PatchOperationType.CREATE,
            PatchOperationType.REPLACE_FILE,
        }:
            if operation.content is None:
                raise PatchRequestError(
                    f"{operation_type.value} requires content."
                )

            resulting_text = operation.content
            replacement_count = 1

        elif operation_type == PatchOperationType.REPLACE_TEXT:
            if (
                operation.search_text is None
                or operation.replacement_text is None
            ):
                raise PatchRequestError(
                    "replace_text requires search_text and "
                    "replacement_text."
                )

            (
                resulting_text,
                replacement_count,
            ) = _replace_text_exact(
                source_text,
                search_text=operation.search_text,
                replacement_text=(
                    operation.replacement_text
                ),
                expected_occurrences=(
                    operation.expected_occurrences
                ),
                maximum_replacements=(
                    self.configuration
                    .maximum_replacements
                ),
            )

        elif operation_type in {
            PatchOperationType.INSERT_BEFORE,
            PatchOperationType.INSERT_AFTER,
        }:
            if (
                operation.search_text is None
                or operation.content is None
            ):
                raise PatchRequestError(
                    f"{operation_type.value} requires "
                    "search_text and content."
                )

            (
                resulting_text,
                replacement_count,
            ) = _insert_relative_to_text(
                source_text,
                anchor_text=operation.search_text,
                inserted_text=operation.content,
                before=(
                    operation_type
                    == PatchOperationType.INSERT_BEFORE
                ),
                expected_occurrences=(
                    operation.expected_occurrences
                ),
                maximum_replacements=(
                    self.configuration
                    .maximum_replacements
                ),
            )

        elif operation_type == PatchOperationType.REPLACE_RANGE:
            if (
                operation.content is None
                or operation.start_line is None
                or operation.end_line is None
            ):
                raise PatchRequestError(
                    "replace_range requires content, "
                    "start_line, and end_line."
                )

            (
                resulting_text,
                replacement_count,
            ) = _replace_line_range(
                source_text,
                replacement_text=operation.content,
                start_line=operation.start_line,
                end_line=operation.end_line,
                newline=newline,
            )

        elif operation_type == PatchOperationType.APPEND_TEXT:
            if operation.content is None:
                raise PatchRequestError(
                    "append_text requires content."
                )

            resulting_text = (
                source_text + operation.content
            )
            replacement_count = 1

        elif operation_type == PatchOperationType.PREPEND_TEXT:
            if operation.content is None:
                raise PatchRequestError(
                    "prepend_text requires content."
                )

            resulting_text = (
                operation.content + source_text
            )
            replacement_count = 1

        elif operation_type == PatchOperationType.UNIFIED_DIFF:
            if operation.unified_diff is None:
                raise PatchRequestError(
                    "unified_diff requires diff content."
                )

            (
                resulting_text,
                replacement_count,
            ) = _apply_unified_diff(
                source_text,
                diff_text=operation.unified_diff,
            )

        else:
            raise PatchOperationError(
                "Operation does not produce text content: "
                f"{operation_type.value}"
            )

        resulting_text = _normalize_newlines(
            resulting_text,
            newline,
        )

        should_have_final_newline = (
            self._select_final_newline_behavior(
                operation,
                original_text,
                resulting_text,
            )
        )

        resulting_text = _set_final_newline(
            resulting_text,
            should_have_final_newline=(
                should_have_final_newline
            ),
            newline=newline,
        )

        return resulting_text, replacement_count

    def prepare_operation(
        self,
        operation: NormalizedPatchOperation,
    ) -> PreparedFileChange:
        """Prepare one patch operation without changing the repository."""

        warnings = list(operation.warnings)
        operation_type = operation.operation

        original_bytes: bytes | None = None
        original_text: str | None = None
        original_sha256: str | None = None

        if operation.source_exists:
            original_bytes = _read_file_bytes(
                operation.absolute_path,
                maximum_bytes=(
                    self.configuration.maximum_file_bytes
                ),
            )

            original_sha256 = (
                self._verify_expected_hash(
                    operation,
                    original_bytes,
                )
            )

        elif operation.expected_sha256 is not None:
            raise PatchHashMismatchError(
                "expected_sha256 was supplied but the source "
                f"file does not exist: {operation.path}"
            )

        if (
            not operation.source_exists
            and operation.ignore_if_missing
        ):
            return PreparedFileChange(
                operation=operation,
                original_bytes=None,
                resulting_bytes=None,
                original_sha256=None,
                resulting_sha256=None,
                original_size_bytes=0,
                resulting_size_bytes=0,
                changed=False,
                replacement_count=0,
                unified_diff_preview="",
                warnings=tuple(
                    [
                        *warnings,
                        "Operation skipped because source file "
                        "does not exist.",
                    ]
                ),
            )

        if (
            operation_type == PatchOperationType.CREATE
            and operation.source_exists
            and operation.ignore_if_exists
        ):
            return PreparedFileChange(
                operation=operation,
                original_bytes=original_bytes,
                resulting_bytes=original_bytes,
                original_sha256=original_sha256,
                resulting_sha256=original_sha256,
                original_size_bytes=len(
                    original_bytes or b""
                ),
                resulting_size_bytes=len(
                    original_bytes or b""
                ),
                changed=False,
                replacement_count=0,
                unified_diff_preview="",
                warnings=tuple(
                    [
                        *warnings,
                        "Create operation skipped because the "
                        "target already exists.",
                    ]
                ),
            )

        if operation_type == PatchOperationType.DELETE:
            if not operation.source_exists:
                if operation.ignore_if_missing:
                    resulting_bytes = None
                    changed = False
                else:
                    raise PatchConflictError(
                        "Delete target does not exist: "
                        f"{operation.path}"
                    )
            else:
                resulting_bytes = None
                changed = True

            return PreparedFileChange(
                operation=operation,
                original_bytes=original_bytes,
                resulting_bytes=resulting_bytes,
                original_sha256=original_sha256,
                resulting_sha256=None,
                original_size_bytes=len(
                    original_bytes or b""
                ),
                resulting_size_bytes=0,
                changed=changed,
                replacement_count=(
                    1 if changed else 0
                ),
                unified_diff_preview=(
                    _create_binary_change_description(
                        path=operation.path,
                        operation=operation_type,
                        original_size=len(
                            original_bytes or b""
                        ),
                        resulting_size=0,
                    )
                ),
                warnings=tuple(warnings),
            )

        if operation_type == PatchOperationType.RENAME:
            if not operation.source_exists:
                raise PatchConflictError(
                    "Rename source does not exist: "
                    f"{operation.path}"
                )

            if (
                operation.destination_absolute_path
                is None
                or operation.destination_path is None
            ):
                raise PatchRequestError(
                    "Rename destination is missing."
                )

            if (
                operation.destination_absolute_path.exists()
                and not self.configuration
                .allow_overwrite_on_rename
            ):
                raise PatchConflictError(
                    "Rename destination already exists: "
                    f"{operation.destination_path}"
                )

            return PreparedFileChange(
                operation=operation,
                original_bytes=original_bytes,
                resulting_bytes=original_bytes,
                original_sha256=original_sha256,
                resulting_sha256=original_sha256,
                original_size_bytes=len(
                    original_bytes or b""
                ),
                resulting_size_bytes=len(
                    original_bytes or b""
                ),
                changed=True,
                replacement_count=1,
                unified_diff_preview=(
                    _create_binary_change_description(
                        path=operation.path,
                        operation=operation_type,
                        original_size=len(
                            original_bytes or b""
                        ),
                        resulting_size=len(
                            original_bytes or b""
                        ),
                    )
                    + "destination: "
                    + operation.destination_path
                    + "\n"
                ),
                warnings=tuple(warnings),
            )

        if operation.source_exists:
            if original_bytes is None:
                raise PatchOperationError(
                    "Source bytes were not loaded."
                )

            original_text, _ = _decode_utf8(
                original_bytes,
                path=operation.absolute_path,
            )

        elif operation.create_if_missing:
            original_text = None
            original_bytes = None

            warnings.append(
                "Source file did not exist and will be created."
            )

        elif operation_type != PatchOperationType.CREATE:
            raise PatchConflictError(
                "Patch target does not exist: "
                f"{operation.path}"
            )

        resulting_text, replacement_count = (
            self._prepare_text_result(
                operation=operation,
                original_text=original_text,
            )
        )

        resulting_bytes = _encode_utf8(
            resulting_text
        )

        if (
            len(resulting_bytes)
            > self.configuration.maximum_file_bytes
        ):
            raise PatchOperationError(
                "Resulting file exceeds the configured "
                f"maximum size: {operation.path}"
            )

        resulting_sha256 = _sha256_bytes(
            resulting_bytes
        )

        changed = (
            original_bytes != resulting_bytes
        )

        original_diff_text = (
            original_text
            if original_text is not None
            else ""
        )

        diff_preview = _create_unified_diff(
            original_diff_text,
            resulting_text,
            path=operation.path,
        )

        return PreparedFileChange(
            operation=operation,
            original_bytes=original_bytes,
            resulting_bytes=resulting_bytes,
            original_sha256=original_sha256,
            resulting_sha256=resulting_sha256,
            original_size_bytes=len(
                original_bytes or b""
            ),
            resulting_size_bytes=len(
                resulting_bytes
            ),
            changed=changed,
            replacement_count=replacement_count,
            unified_diff_preview=diff_preview,
            warnings=tuple(warnings),
        )

    def prepare_request(
        self,
        request: (
            PatchRequestPayload
            | BaseModel
            | Mapping[str, Any]
            | Sequence[Any]
        ),
        *,
        dry_run: bool | None = None,
    ) -> tuple[
        PatchRequestPayload,
        tuple[PreparedFileChange, ...],
    ]:
        """Normalize and prepare an entire patch request."""

        normalized_request = self.normalize_request(
            request,
            dry_run=dry_run,
        )

        normalized_operations = (
            self.normalize_operations(
                normalized_request
            )
        )

        prepared_changes = tuple(
            self.prepare_operation(operation)
            for operation in normalized_operations
        )

        return (
            normalized_request,
            prepared_changes,
        )
    def _create_transaction_state(
        self,
        *,
        transaction_id: UUID,
    ) -> PatchTransactionState:
        """Create isolated transaction state and backup directory."""

        storage_root = self._transaction_storage_root()
        backup_root = (
            storage_root / str(transaction_id)
        ).resolve(strict=False)

        if not _is_relative_to(
            backup_root,
            self.repository_root,
        ):
            raise PatchTransactionError(
                "Transaction backup path escapes the repository."
            )

        try:
            backup_root.mkdir(
                parents=True,
                exist_ok=False,
            )
        except FileExistsError as exc:
            raise PatchTransactionError(
                "Transaction backup directory already exists: "
                f"{backup_root}"
            ) from exc
        except OSError as exc:
            raise PatchTransactionError(
                "Could not create the transaction backup directory."
            ) from exc

        return PatchTransactionState(
            transaction_id=transaction_id,
            backup_root=backup_root,
        )

    def _snapshot_key(
        self,
        path: Path,
    ) -> str:
        """Return a canonical case-insensitive snapshot key."""

        try:
            relative = path.resolve(
                strict=False
            ).relative_to(self.repository_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PatchPathError(
                "Snapshot path is outside the repository."
            ) from exc

        return relative.as_posix().casefold()

    def _snapshot_path(
        self,
        *,
        state: PatchTransactionState,
        relative_path: str,
    ) -> Path:
        """Return the backup-file path for a repository-relative path."""

        pure_path = PurePosixPath(
            relative_path
        )

        if any(
            part in {"", ".", ".."}
            for part in pure_path.parts
        ):
            raise PatchPathError(
                "Invalid transaction snapshot path: "
                f"{relative_path}"
            )

        backup_path = (
            state.backup_root
            / "files"
            / Path(*pure_path.parts)
        ).resolve(strict=False)

        if not _is_relative_to(
            backup_path,
            state.backup_root,
        ):
            raise PatchPathError(
                "Snapshot backup path escapes the transaction directory."
            )

        return backup_path

    def _create_snapshot(
        self,
        *,
        state: PatchTransactionState,
        relative_path: str,
        absolute_path: Path,
    ) -> FileSnapshot:
        """Capture one path before it is modified."""

        snapshot_key = self._snapshot_key(
            absolute_path
        )

        existing_snapshot = state.snapshots.get(
            snapshot_key
        )

        if existing_snapshot is not None:
            return existing_snapshot

        exists = absolute_path.exists()

        if not exists:
            snapshot = FileSnapshot(
                relative_path=relative_path,
                absolute_path=absolute_path,
                existed=False,
                content=None,
                mode=None,
                modified_time_ns=None,
                is_directory=False,
            )

            state.snapshots[snapshot_key] = snapshot
            return snapshot

        if absolute_path.is_symlink():
            raise PatchPathError(
                "Cannot snapshot a symbolic link: "
                f"{relative_path}"
            )

        try:
            path_stat = absolute_path.stat()
        except OSError as exc:
            raise PatchTransactionError(
                f"Could not inspect path before patching: {relative_path}"
            ) from exc

        is_directory = stat.S_ISDIR(
            path_stat.st_mode
        )

        if is_directory:
            snapshot = FileSnapshot(
                relative_path=relative_path,
                absolute_path=absolute_path,
                existed=True,
                content=None,
                mode=stat.S_IMODE(
                    path_stat.st_mode
                ),
                modified_time_ns=(
                    path_stat.st_mtime_ns
                ),
                is_directory=True,
            )

            state.snapshots[snapshot_key] = snapshot
            return snapshot

        if not stat.S_ISREG(
            path_stat.st_mode
        ):
            raise PatchTransactionError(
                "Only regular files and directories can be snapshotted: "
                f"{relative_path}"
            )

        content = _read_file_bytes(
            absolute_path,
            maximum_bytes=(
                self.configuration.maximum_file_bytes
            ),
        )

        backup_path = self._snapshot_path(
            state=state,
            relative_path=relative_path,
        )

        try:
            backup_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            _write_file_atomic(
                backup_path,
                content,
                preserve_mode_from=absolute_path,
                preserve_file_permissions=True,
                fsync_writes=(
                    self.configuration.fsync_writes
                ),
            )
        except PatchServiceError:
            raise
        except OSError as exc:
            raise PatchTransactionError(
                "Could not write transaction backup for "
                f"{relative_path}."
            ) from exc

        snapshot = FileSnapshot(
            relative_path=relative_path,
            absolute_path=absolute_path,
            existed=True,
            content=content,
            mode=stat.S_IMODE(
                path_stat.st_mode
            ),
            modified_time_ns=path_stat.st_mtime_ns,
            is_directory=False,
        )

        state.snapshots[snapshot_key] = snapshot

        return snapshot

    def _snapshot_operation_paths(
        self,
        *,
        state: PatchTransactionState,
        operation: NormalizedPatchOperation,
    ) -> None:
        """Snapshot every path that an operation may modify."""

        self._create_snapshot(
            state=state,
            relative_path=operation.path,
            absolute_path=operation.absolute_path,
        )

        if (
            operation.destination_path is not None
            and operation.destination_absolute_path
            is not None
        ):
            self._create_snapshot(
                state=state,
                relative_path=operation.destination_path,
                absolute_path=(
                    operation.destination_absolute_path
                ),
            )

    def _record_created_directories(
        self,
        *,
        state: PatchTransactionState,
        target_parent: Path,
    ) -> None:
        """Record missing parent directories before they are created."""

        missing_directories: list[Path] = []
        current = target_parent

        while (
            current != self.repository_root
            and _is_relative_to(
                current,
                self.repository_root,
            )
            and not current.exists()
        ):
            missing_directories.append(
                current
            )
            current = current.parent

        for directory in reversed(
            missing_directories
        ):
            if directory not in state.created_directories:
                state.created_directories.append(
                    directory
                )

    def _ensure_parent_directory(
        self,
        *,
        state: PatchTransactionState,
        path: Path,
    ) -> None:
        """Create a target parent directory when permitted."""

        parent = path.parent

        if parent.exists():
            if not parent.is_dir():
                raise PatchOperationError(
                    "Target parent is not a directory: "
                    f"{parent}"
                )

            return

        if not self.configuration.create_parent_directories:
            raise PatchOperationError(
                "Target parent directory does not exist and automatic "
                f"creation is disabled: {parent}"
            )

        self._record_created_directories(
            state=state,
            target_parent=parent,
        )

        try:
            parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        except OSError as exc:
            raise PatchOperationError(
                f"Could not create target parent directory: {parent}"
            ) from exc

    def _commit_text_change(
        self,
        *,
        state: PatchTransactionState,
        prepared: PreparedFileChange,
    ) -> None:
        """Commit a prepared text-file operation."""

        operation = prepared.operation

        if prepared.resulting_bytes is None:
            raise PatchOperationError(
                "Prepared text operation has no resulting content."
            )

        self._ensure_parent_directory(
            state=state,
            path=operation.absolute_path,
        )

        preserve_mode_source = (
            operation.absolute_path
            if operation.absolute_path.exists()
            else None
        )

        _write_file_atomic(
            operation.absolute_path,
            prepared.resulting_bytes,
            preserve_mode_from=preserve_mode_source,
            preserve_file_permissions=(
                self.configuration.preserve_file_permissions
            ),
            fsync_writes=(
                self.configuration.fsync_writes
            ),
        )

    def _commit_delete(
        self,
        prepared: PreparedFileChange,
    ) -> None:
        """Commit a prepared delete operation."""

        target = prepared.operation.absolute_path

        if not target.exists():
            if prepared.operation.ignore_if_missing:
                return

            raise PatchConflictError(
                "Delete target disappeared before commit: "
                f"{prepared.operation.path}"
            )

        if target.is_symlink():
            raise PatchPathError(
                "Refusing to delete a symbolic link: "
                f"{prepared.operation.path}"
            )

        if not target.is_file():
            raise PatchOperationError(
                "Delete operation supports regular files only: "
                f"{prepared.operation.path}"
            )

        try:
            target.unlink()
        except OSError as exc:
            raise PatchOperationError(
                "Could not delete file: "
                f"{prepared.operation.path}"
            ) from exc

    def _commit_rename(
        self,
        *,
        state: PatchTransactionState,
        prepared: PreparedFileChange,
    ) -> None:
        """Commit a prepared rename operation."""

        operation = prepared.operation
        source = operation.absolute_path
        destination = (
            operation.destination_absolute_path
        )

        if destination is None:
            raise PatchOperationError(
                "Rename destination is missing."
            )

        if not source.exists():
            raise PatchConflictError(
                "Rename source disappeared before commit: "
                f"{operation.path}"
            )

        if source.is_symlink():
            raise PatchPathError(
                "Refusing to rename a symbolic link: "
                f"{operation.path}"
            )

        if not source.is_file():
            raise PatchOperationError(
                "Rename operation supports regular files only: "
                f"{operation.path}"
            )

        if (
            destination.exists()
            and not self.configuration
            .allow_overwrite_on_rename
        ):
            raise PatchConflictError(
                "Rename destination appeared before commit: "
                f"{operation.destination_path}"
            )

        self._ensure_parent_directory(
            state=state,
            path=destination,
        )

        try:
            if (
                destination.exists()
                and self.configuration
                .allow_overwrite_on_rename
            ):
                if destination.is_symlink():
                    raise PatchPathError(
                        "Refusing to overwrite a symbolic link during "
                        f"rename: {operation.destination_path}"
                    )

                if not destination.is_file():
                    raise PatchOperationError(
                        "Rename destination is not a regular file: "
                        f"{operation.destination_path}"
                    )

                destination.unlink()

            os.replace(
                source,
                destination,
            )
        except PatchServiceError:
            raise
        except OSError as exc:
            raise PatchOperationError(
                f"Could not rename {operation.path} to "
                f"{operation.destination_path}."
            ) from exc

    def _commit_prepared_change(
        self,
        *,
        state: PatchTransactionState,
        prepared: PreparedFileChange,
    ) -> None:
        """Commit one prepared operation."""

        if not prepared.changed:
            return

        operation_type = (
            prepared.operation.operation
        )

        if operation_type == PatchOperationType.DELETE:
            self._commit_delete(prepared)

        elif operation_type == PatchOperationType.RENAME:
            self._commit_rename(
                state=state,
                prepared=prepared,
            )

        else:
            self._commit_text_change(
                state=state,
                prepared=prepared,
            )

        state.committed_operations.append(
            prepared.operation
        )

    def _restore_snapshot(
        self,
        snapshot: FileSnapshot,
    ) -> None:
        """Restore one file snapshot during rollback."""

        target = snapshot.absolute_path

        if snapshot.existed:
            if snapshot.is_directory:
                if target.exists():
                    if not target.is_dir():
                        if target.is_file():
                            target.unlink()
                        else:
                            raise PatchRollbackError(
                                "Cannot restore directory because target "
                                "has an unsupported type: "
                                f"{snapshot.relative_path}"
                            )
                else:
                    target.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                if snapshot.mode is not None:
                    try:
                        os.chmod(
                            target,
                            snapshot.mode,
                        )
                    except OSError:
                        LOGGER.warning(
                            "Could not restore directory permissions: %s",
                            target,
                        )

                return

            if snapshot.content is None:
                raise PatchRollbackError(
                    "File snapshot is missing backup content: "
                    f"{snapshot.relative_path}"
                )

            if target.exists() and target.is_dir():
                try:
                    shutil.rmtree(target)
                except OSError as exc:
                    raise PatchRollbackError(
                        "Could not remove directory while restoring file: "
                        f"{snapshot.relative_path}"
                    ) from exc

            try:
                target.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
            except OSError as exc:
                raise PatchRollbackError(
                    "Could not recreate parent directory during rollback: "
                    f"{target.parent}"
                ) from exc

            _write_file_atomic(
                target,
                snapshot.content,
                preserve_mode_from=None,
                preserve_file_permissions=False,
                fsync_writes=(
                    self.configuration.fsync_writes
                ),
            )

            if snapshot.mode is not None:
                try:
                    os.chmod(
                        target,
                        snapshot.mode,
                    )
                except OSError as exc:
                    raise PatchRollbackError(
                        "Could not restore file permissions: "
                        f"{snapshot.relative_path}"
                    ) from exc

            if snapshot.modified_time_ns is not None:
                try:
                    os.utime(
                        target,
                        ns=(
                            snapshot.modified_time_ns,
                            snapshot.modified_time_ns,
                        ),
                    )
                except OSError:
                    LOGGER.warning(
                        "Could not restore modification time: %s",
                        target,
                    )

            return

        if not target.exists():
            return

        if target.is_symlink():
            try:
                target.unlink()
            except OSError as exc:
                raise PatchRollbackError(
                    "Could not remove created symbolic link during "
                    f"rollback: {snapshot.relative_path}"
                ) from exc

            return

        if target.is_file():
            try:
                target.unlink()
            except OSError as exc:
                raise PatchRollbackError(
                    "Could not remove created file during rollback: "
                    f"{snapshot.relative_path}"
                ) from exc

            return

        if target.is_dir():
            try:
                shutil.rmtree(target)
            except OSError as exc:
                raise PatchRollbackError(
                    "Could not remove created directory during rollback: "
                    f"{snapshot.relative_path}"
                ) from exc

            return

        raise PatchRollbackError(
            "Rollback encountered an unsupported target type: "
            f"{snapshot.relative_path}"
        )

    def _remove_created_directories(
        self,
        state: PatchTransactionState,
    ) -> tuple[str, ...]:
        """Remove empty directories created by the transaction."""

        warnings: list[str] = []

        directories = sorted(
            set(state.created_directories),
            key=lambda path: len(path.parts),
            reverse=True,
        )

        for directory in directories:
            if not directory.exists():
                continue

            if not _is_relative_to(
                directory,
                self.repository_root,
            ):
                warnings.append(
                    "Skipped removal of directory outside repository: "
                    f"{directory}"
                )
                continue

            try:
                directory.rmdir()
            except OSError:
                if directory.exists():
                    warnings.append(
                        "Created directory was not empty during cleanup: "
                        f"{directory}"
                    )

        return tuple(warnings)

    def rollback_transaction(
        self,
        state: PatchTransactionState,
    ) -> tuple[str, ...]:
        """Restore all paths captured by a transaction."""

        rollback_errors: list[str] = []

        snapshots = sorted(
            state.snapshots.values(),
            key=lambda snapshot: len(
                snapshot.absolute_path.parts
            ),
            reverse=True,
        )

        for snapshot in snapshots:
            try:
                self._restore_snapshot(snapshot)
            except Exception as exc:
                LOGGER.exception(
                    "Failed to restore transaction snapshot: %s",
                    snapshot.relative_path,
                )

                rollback_errors.append(
                    f"{snapshot.relative_path}: {exc}"
                )

        rollback_errors.extend(
            self._remove_created_directories(
                state
            )
        )

        if rollback_errors:
            raise PatchRollbackError(
                "Rollback did not fully restore the repository: "
                + "; ".join(rollback_errors)
            )

        return ()

    def _cleanup_transaction_backup(
        self,
        state: PatchTransactionState,
    ) -> None:
        """Delete a transaction backup directory."""

        backup_root = state.backup_root

        if not backup_root.exists():
            return

        if not _is_relative_to(
            backup_root,
            self.repository_root,
        ):
            raise PatchTransactionError(
                "Refusing to clean a backup path outside the repository."
            )

        try:
            shutil.rmtree(backup_root)
        except OSError as exc:
            raise PatchTransactionError(
                "Could not remove transaction backup directory: "
                f"{backup_root}"
            ) from exc

        parent = backup_root.parent

        while (
            parent != self.repository_root
            and _is_relative_to(
                parent,
                self.repository_root,
            )
        ):
            try:
                parent.rmdir()
            except OSError:
                break

            parent = parent.parent

    def _result_from_prepared(
        self,
        *,
        prepared: PreparedFileChange,
        status: PatchStatus,
        started_at: datetime,
        started_monotonic: float,
        error: str | None = None,
        warnings: Iterable[str] = (),
    ) -> AppliedFileResult:
        """Create one operation result from prepared data."""

        completed_at = utc_now()
        combined_warnings = _normalize_result_warnings(
            [
                *prepared.warnings,
                *warnings,
            ]
        )

        return AppliedFileResult(
            operation_id=(
                prepared.operation.operation_id
            ),
            operation=prepared.operation.operation,
            path=prepared.operation.path,
            destination_path=(
                prepared.operation.destination_path
            ),
            status=status,
            changed=(
                prepared.changed
                and status
                in {
                    PatchStatus.APPLIED,
                    PatchStatus.DRY_RUN,
                    PatchStatus.ROLLED_BACK,
                }
            ),
            original_sha256=prepared.original_sha256,
            resulting_sha256=(
                prepared.resulting_sha256
            ),
            original_size_bytes=(
                prepared.original_size_bytes
            ),
            resulting_size_bytes=(
                prepared.resulting_size_bytes
            ),
            replacement_count=(
                prepared.replacement_count
            ),
            diff=prepared.unified_diff_preview,
            warnings=combined_warnings,
            error=error,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=max(
                time.monotonic()
                - started_monotonic,
                0.0,
            ),
        )

    def _failed_result(
        self,
        *,
        prepared: PreparedFileChange,
        started_at: datetime,
        started_monotonic: float,
        error: Exception,
    ) -> AppliedFileResult:
        """Create a failed operation result."""

        return self._result_from_prepared(
            prepared=prepared,
            status=PatchStatus.FAILED,
            started_at=started_at,
            started_monotonic=started_monotonic,
            error=str(error),
        )

    def _rolled_back_result(
        self,
        result: AppliedFileResult,
        *,
        rollback_warning: str | None = None,
    ) -> AppliedFileResult:
        """Convert an applied result to rolled-back status."""

        warnings = list(result.warnings)

        if rollback_warning:
            warnings.append(rollback_warning)

        return AppliedFileResult(
            operation_id=result.operation_id,
            operation=result.operation,
            path=result.path,
            destination_path=result.destination_path,
            status=PatchStatus.ROLLED_BACK,
            changed=result.changed,
            original_sha256=result.original_sha256,
            resulting_sha256=result.resulting_sha256,
            original_size_bytes=(
                result.original_size_bytes
            ),
            resulting_size_bytes=(
                result.resulting_size_bytes
            ),
            replacement_count=result.replacement_count,
            diff=result.diff,
            warnings=_normalize_result_warnings(
                warnings
            ),
            error=result.error,
            started_at=result.started_at,
            completed_at=utc_now(),
            duration_seconds=result.duration_seconds,
        )

    def _verify_prepared_state(
        self,
        prepared: PreparedFileChange,
    ) -> None:
        """Verify that repository state has not changed since preparation."""

        operation = prepared.operation
        source = operation.absolute_path

        if prepared.original_bytes is None:
            if (
                source.exists()
                and operation.operation
                != PatchOperationType.CREATE
            ):
                raise PatchConflictError(
                    "Source path appeared after patch preparation: "
                    f"{operation.path}"
                )

            if (
                operation.operation
                == PatchOperationType.CREATE
                and source.exists()
                and not (
                    operation.ignore_if_exists
                    or self.configuration
                    .allow_overwrite_on_create
                )
            ):
                raise PatchConflictError(
                    "Create target appeared after patch preparation: "
                    f"{operation.path}"
                )

        else:
            if not source.exists():
                raise PatchConflictError(
                    "Source file disappeared after patch preparation: "
                    f"{operation.path}"
                )

            current_bytes = _read_file_bytes(
                source,
                maximum_bytes=(
                    self.configuration.maximum_file_bytes
                ),
            )

            current_hash = _sha256_bytes(
                current_bytes
            )

            if current_hash != prepared.original_sha256:
                raise PatchHashMismatchError(
                    "Source file changed after patch preparation: "
                    f"{operation.path}"
                )

        if (
            operation.operation
            == PatchOperationType.RENAME
            and operation.destination_absolute_path
            is not None
        ):
            destination_exists_now = (
                operation.destination_absolute_path.exists()
            )

            if (
                destination_exists_now
                and not operation.destination_exists
                and not self.configuration
                .allow_overwrite_on_rename
            ):
                raise PatchConflictError(
                    "Rename destination appeared after preparation: "
                    f"{operation.destination_path}"
                )

    def apply_patch(
        self,
        request: (
            PatchRequestPayload
            | BaseModel
            | Mapping[str, Any]
            | Sequence[Any]
        ),
        *,
        dry_run: bool | None = None,
    ) -> PatchTransactionResult:
        """Apply a validated multi-file patch transaction.

        All changes are prepared before any write occurs. During a real
        execution, every affected path is snapshotted before the first
        mutation. When configured, any failure triggers complete rollback.
        """

        transaction_id = uuid4()
        transaction_started_at = utc_now()
        transaction_started_monotonic = (
            time.monotonic()
        )

        normalized_request: (
            PatchRequestPayload | None
        ) = None
        prepared_changes: tuple[
            PreparedFileChange,
            ...
        ] = ()
        state: PatchTransactionState | None = None
        operation_results: list[
            AppliedFileResult
        ] = []
        transaction_warnings: list[str] = []
        transaction_error: str | None = None
        rolled_back = False

        try:
            (
                normalized_request,
                prepared_changes,
            ) = self.prepare_request(
                request,
                dry_run=dry_run,
            )

            if normalized_request.dry_run:
                for prepared in prepared_changes:
                    operation_started_at = utc_now()
                    operation_started_monotonic = (
                        time.monotonic()
                    )

                    operation_status = (
                        PatchStatus.DRY_RUN
                        if prepared.changed
                        else PatchStatus.SKIPPED
                    )

                    operation_results.append(
                        self._result_from_prepared(
                            prepared=prepared,
                            status=operation_status,
                            started_at=operation_started_at,
                            started_monotonic=(
                                operation_started_monotonic
                            ),
                        )
                    )

                completed_at = utc_now()

                return PatchTransactionResult(
                    transaction_id=transaction_id,
                    request_id=(
                        normalized_request.request_id
                    ),
                    repository_root=str(
                        self.repository_root
                    ),
                    status=PatchStatus.DRY_RUN,
                    dry_run=True,
                    rolled_back=False,
                    results=tuple(operation_results),
                    warnings=_normalize_result_warnings(
                        transaction_warnings
                    ),
                    error=None,
                    started_at=(
                        transaction_started_at
                    ),
                    completed_at=completed_at,
                    duration_seconds=max(
                        time.monotonic()
                        - transaction_started_monotonic,
                        0.0,
                    ),
                )

            state = self._create_transaction_state(
                transaction_id=transaction_id
            )

            for prepared in prepared_changes:
                self._snapshot_operation_paths(
                    state=state,
                    operation=prepared.operation,
                )

            for prepared in prepared_changes:
                operation_started_at = utc_now()
                operation_started_monotonic = (
                    time.monotonic()
                )

                try:
                    if not prepared.changed:
                        operation_results.append(
                            self._result_from_prepared(
                                prepared=prepared,
                                status=PatchStatus.SKIPPED,
                                started_at=(
                                    operation_started_at
                                ),
                                started_monotonic=(
                                    operation_started_monotonic
                                ),
                            )
                        )
                        continue

                    self._verify_prepared_state(
                        prepared
                    )

                    self._commit_prepared_change(
                        state=state,
                        prepared=prepared,
                    )

                    operation_results.append(
                        self._result_from_prepared(
                            prepared=prepared,
                            status=PatchStatus.APPLIED,
                            started_at=(
                                operation_started_at
                            ),
                            started_monotonic=(
                                operation_started_monotonic
                            ),
                        )
                    )

                except Exception as exc:
                    operation_results.append(
                        self._failed_result(
                            prepared=prepared,
                            started_at=(
                                operation_started_at
                            ),
                            started_monotonic=(
                                operation_started_monotonic
                            ),
                            error=exc,
                        )
                    )

                    raise

            if (
                not self.configuration
                .retain_transaction_backup_on_success
            ):
                try:
                    self._cleanup_transaction_backup(
                        state
                    )
                except PatchTransactionError as exc:
                    LOGGER.warning(
                        "Patch applied but transaction backup cleanup "
                        "failed: %s",
                        exc,
                    )

                    transaction_warnings.append(
                        str(exc)
                    )

            completed_at = utc_now()

            return PatchTransactionResult(
                transaction_id=transaction_id,
                request_id=(
                    normalized_request.request_id
                ),
                repository_root=str(
                    self.repository_root
                ),
                status=PatchStatus.APPLIED,
                dry_run=False,
                rolled_back=False,
                results=tuple(operation_results),
                warnings=_normalize_result_warnings(
                    transaction_warnings
                ),
                error=None,
                started_at=transaction_started_at,
                completed_at=completed_at,
                duration_seconds=max(
                    time.monotonic()
                    - transaction_started_monotonic,
                    0.0,
                ),
            )

        except Exception as exc:
            transaction_error = str(exc)
            rollback_requested = (
                normalized_request.rollback_on_failure
                if (
                    normalized_request is not None
                    and normalized_request
                    .rollback_on_failure
                    is not None
                )
                else self.configuration
                .rollback_on_failure
            )

            rollback_error: Exception | None = None

            if (
                state is not None
                and rollback_requested
            ):
                try:
                    self.rollback_transaction(
                        state
                    )
                    rolled_back = True

                    operation_results = [
                        self._rolled_back_result(
                            result
                        )
                        if result.status
                        == PatchStatus.APPLIED
                        else result
                        for result in operation_results
                    ]

                except Exception as caught_rollback_error:
                    rollback_error = (
                        caught_rollback_error
                    )

                    LOGGER.exception(
                        "Patch transaction rollback failed."
                    )

                    transaction_warnings.append(
                        "Rollback failure: "
                        f"{caught_rollback_error}"
                    )

            if state is not None:
                try:
                    if (
                        rolled_back
                        or not self.configuration
                        .retain_transaction_backup_on_success
                    ):
                        self._cleanup_transaction_backup(
                            state
                        )
                except Exception as cleanup_error:
                    LOGGER.warning(
                        "Could not clean failed patch transaction "
                        "backup: %s",
                        cleanup_error,
                    )

                    transaction_warnings.append(
                        "Transaction backup cleanup failure: "
                        f"{cleanup_error}"
                    )

            completed_at = utc_now()
            request_id = (
                normalized_request.request_id
                if normalized_request is not None
                else uuid4()
            )

            result = PatchTransactionResult(
                transaction_id=transaction_id,
                request_id=request_id,
                repository_root=str(
                    self.repository_root
                ),
                status=(
                    PatchStatus.ROLLED_BACK
                    if rolled_back
                    else PatchStatus.FAILED
                ),
                dry_run=bool(
                    normalized_request.dry_run
                    if normalized_request is not None
                    else dry_run
                ),
                rolled_back=rolled_back,
                results=tuple(operation_results),
                warnings=_normalize_result_warnings(
                    transaction_warnings
                ),
                error=transaction_error,
                started_at=transaction_started_at,
                completed_at=completed_at,
                duration_seconds=max(
                    time.monotonic()
                    - transaction_started_monotonic,
                    0.0,
                ),
            )

            if rollback_error is not None:
                raise PatchRollbackError(
                    "Patch transaction failed and rollback was "
                    "incomplete."
                ) from rollback_error

            raise PatchTransactionError(
                "Patch transaction failed"
                + (
                    " and was rolled back."
                    if rolled_back
                    else "."
                )
            ) from exc

    def preview_patch(
        self,
        request: (
            PatchRequestPayload
            | BaseModel
            | Mapping[str, Any]
            | Sequence[Any]
        ),
    ) -> PatchTransactionResult:
        """Prepare and return a dry-run patch result."""

        return self.apply_patch(
            request,
            dry_run=True,
        )

    @staticmethod
    def _validate_model_instance(
        *,
        model_class: type[BaseModel],
        payload: Mapping[str, Any],
        description: str,
    ) -> BaseModel:
        """Validate a payload against one models.py model."""

        filtered_payload = _filter_model_payload(
            model_class,
            payload,
        )

        try:
            return model_class.model_validate(
                filtered_payload
            )
        except ValidationError as exc:
            raise PatchModelCompatibilityError(
                f"The {description} model in models.py is not "
                "compatible with PatchService output."
            ) from exc

    @classmethod
    def _convert_file_result_for_model(
        cls,
        result: AppliedFileResult,
    ) -> BaseModel | dict[str, Any]:
        """Convert one internal result to a models.py result model."""

        model_class = _find_model_class(
            MODEL_FILE_RESULT_CANDIDATES
        )

        payload: dict[str, Any] = {
            "id": str(result.operation_id),
            "operation_id": str(
                result.operation_id
            ),
            "operation": result.operation.value,
            "change_type": result.operation.value,
            "path": result.path,
            "file_path": result.path,
            "relative_path": result.path,
            "destination_path": (
                result.destination_path
            ),
            "new_path": result.destination_path,
            "status": result.status.value,
            "changed": result.changed,
            "success": result.status
            in {
                PatchStatus.APPLIED,
                PatchStatus.SKIPPED,
                PatchStatus.DRY_RUN,
            },
            "original_sha256": (
                result.original_sha256
            ),
            "source_sha256": (
                result.original_sha256
            ),
            "resulting_sha256": (
                result.resulting_sha256
            ),
            "new_sha256": (
                result.resulting_sha256
            ),
            "original_size_bytes": (
                result.original_size_bytes
            ),
            "resulting_size_bytes": (
                result.resulting_size_bytes
            ),
            "replacement_count": (
                result.replacement_count
            ),
            "diff": result.diff,
            "warnings": list(result.warnings),
            "error": result.error,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "duration_seconds": (
                result.duration_seconds
            ),
        }

        if model_class is None:
            return result.to_dict()

        return cls._validate_model_instance(
            model_class=model_class,
            payload=payload,
            description="file patch result",
        )

    @classmethod
    def to_patch_result_model(
        cls,
        result: PatchTransactionResult,
    ) -> BaseModel:
        """Convert an internal transaction result to models.py."""

        model_class = _find_model_class(
            MODEL_PATCH_RESULT_CANDIDATES
        )

        if model_class is None:
            raise PatchModelCompatibilityError(
                "models.py does not expose a compatible patch result "
                "model. Expected one of: "
                + ", ".join(
                    MODEL_PATCH_RESULT_CANDIDATES
                )
            )

        converted_results = [
            cls._convert_file_result_for_model(
                file_result
            )
            for file_result in result.results
        ]

        payload: dict[str, Any] = {
            "id": str(result.transaction_id),
            "transaction_id": str(
                result.transaction_id
            ),
            "request_id": str(result.request_id),
            "repository_root": (
                result.repository_root
            ),
            "status": result.status.value,
            "success": result.successful,
            "successful": result.successful,
            "dry_run": result.dry_run,
            "rolled_back": result.rolled_back,
            "results": converted_results,
            "file_results": converted_results,
            "changes": converted_results,
            "changed_file_count": (
                result.changed_file_count
            ),
            "warnings": list(result.warnings),
            "error": result.error,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "duration_seconds": (
                result.duration_seconds
            ),
        }

        return cls._validate_model_instance(
            model_class=model_class,
            payload=payload,
            description="patch transaction result",
        )

    def apply_patch_model(
        self,
        request: (
            PatchRequestPayload
            | BaseModel
            | Mapping[str, Any]
            | Sequence[Any]
        ),
        *,
        dry_run: bool | None = None,
    ) -> BaseModel:
        """Apply a patch and return the result model from models.py."""

        result = self.apply_patch(
            request,
            dry_run=dry_run,
        )

        return self.to_patch_result_model(
            result
        )

    def preview_patch_model(
        self,
        request: (
            PatchRequestPayload
            | BaseModel
            | Mapping[str, Any]
            | Sequence[Any]
        ),
    ) -> BaseModel:
        """Preview a patch and return the models.py result model."""

        result = self.preview_patch(
            request
        )

        return self.to_patch_result_model(
            result
        )


def _normalize_result_warnings(
    warnings: Iterable[Any],
) -> tuple[str, ...]:
    """Normalize and deduplicate result warnings."""

    result: list[str] = []
    seen: set[str] = set()

    for warning in warnings:
        if len(result) >= MAX_WARNING_COUNT:
            break

        normalized = str(warning).strip()

        if not normalized:
            continue

        key = normalized.casefold()

        if key in seen:
            continue

        seen.add(key)
        result.append(normalized)

    return tuple(result)


def create_patch_service(
    *,
    repository_root: str | os.PathLike[str] | Path,
    maximum_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    maximum_patch_bytes: int = DEFAULT_MAX_PATCH_BYTES,
    maximum_operations: int = DEFAULT_MAX_OPERATIONS,
    maximum_replacements: int = (
        DEFAULT_MAX_REPLACEMENTS
    ),
    maximum_search_characters: int = (
        DEFAULT_MAX_SEARCH_CHARACTERS
    ),
    newline_mode: NewlineMode | str = (
        NewlineMode.PRESERVE
    ),
    create_parent_directories: bool = True,
    allow_create: bool = True,
    allow_delete: bool = True,
    allow_rename: bool = True,
    allow_overwrite_on_create: bool = False,
    allow_overwrite_on_rename: bool = False,
    require_expected_hash_for_existing_files: bool = False,
    reject_symbolic_links: bool = True,
    reject_protected_paths: bool = True,
    preserve_file_permissions: bool = True,
    preserve_final_newline: bool = True,
    fsync_writes: bool = True,
    rollback_on_failure: bool = True,
    retain_transaction_backup_on_success: bool = False,
) -> PatchService:
    """Create a configured PatchService instance."""

    normalized_newline_mode = (
        newline_mode
        if isinstance(
            newline_mode,
            NewlineMode,
        )
        else NewlineMode(
            str(newline_mode).strip().casefold()
        )
    )

    configuration = PatchConfiguration(
        maximum_file_bytes=maximum_file_bytes,
        maximum_patch_bytes=maximum_patch_bytes,
        maximum_operations=maximum_operations,
        maximum_replacements=(
            maximum_replacements
        ),
        maximum_search_characters=(
            maximum_search_characters
        ),
        encoding=DEFAULT_ENCODING,
        newline_mode=normalized_newline_mode,
        create_parent_directories=(
            create_parent_directories
        ),
        allow_create=allow_create,
        allow_delete=allow_delete,
        allow_rename=allow_rename,
        allow_overwrite_on_create=(
            allow_overwrite_on_create
        ),
        allow_overwrite_on_rename=(
            allow_overwrite_on_rename
        ),
        require_expected_hash_for_existing_files=(
            require_expected_hash_for_existing_files
        ),
        reject_symbolic_links=(
            reject_symbolic_links
        ),
        reject_protected_paths=(
            reject_protected_paths
        ),
        preserve_file_permissions=(
            preserve_file_permissions
        ),
        preserve_final_newline=(
            preserve_final_newline
        ),
        fsync_writes=fsync_writes,
        rollback_on_failure=(
            rollback_on_failure
        ),
        retain_transaction_backup_on_success=(
            retain_transaction_backup_on_success
        ),
    )

    return PatchService(
        repository_root=repository_root,
        configuration=configuration,
    )


def apply_repository_patch(
    *,
    repository_root: str | os.PathLike[str] | Path,
    request: (
        PatchRequestPayload
        | BaseModel
        | Mapping[str, Any]
        | Sequence[Any]
    ),
    configuration: PatchConfiguration | None = None,
    dry_run: bool | None = None,
) -> PatchTransactionResult:
    """Apply one patch request to a repository."""

    service = PatchService(
        repository_root=repository_root,
        configuration=configuration,
    )

    return service.apply_patch(
        request,
        dry_run=dry_run,
    )


def preview_repository_patch(
    *,
    repository_root: str | os.PathLike[str] | Path,
    request: (
        PatchRequestPayload
        | BaseModel
        | Mapping[str, Any]
        | Sequence[Any]
    ),
    configuration: PatchConfiguration | None = None,
) -> PatchTransactionResult:
    """Preview one patch request without modifying the repository."""

    service = PatchService(
        repository_root=repository_root,
        configuration=configuration,
    )

    return service.preview_patch(
        request
    )


def apply_repository_patch_model(
    *,
    repository_root: str | os.PathLike[str] | Path,
    request: (
        PatchRequestPayload
        | BaseModel
        | Mapping[str, Any]
        | Sequence[Any]
    ),
    configuration: PatchConfiguration | None = None,
    dry_run: bool | None = None,
) -> BaseModel:
    """Apply a patch and return the result model defined in models.py."""

    service = PatchService(
        repository_root=repository_root,
        configuration=configuration,
    )

    return service.apply_patch_model(
        request,
        dry_run=dry_run,
    )


__all__ = [
    "AppliedFileResult",
    "DEFAULT_ENCODING",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_OPERATIONS",
    "DEFAULT_MAX_PATCH_BYTES",
    "DEFAULT_MAX_REPLACEMENTS",
    "DEFAULT_MAX_SEARCH_CHARACTERS",
    "FileSnapshot",
    "NewlineMode",
    "NormalizedPatchOperation",
    "PatchConfiguration",
    "PatchConfigurationError",
    "PatchConflictError",
    "PatchEncodingError",
    "PatchHashMismatchError",
    "PatchModelCompatibilityError",
    "PatchOperationError",
    "PatchOperationType",
    "PatchPathError",
    "PatchRequestError",
    "PatchRequestPayload",
    "PatchRollbackError",
    "PatchService",
    "PatchServiceError",
    "PatchStatus",
    "PatchTransactionError",
    "PatchTransactionResult",
    "PreparedFileChange",
    "ProposedPatchOperation",
    "UnifiedDiffHunk",
    "apply_repository_patch",
    "apply_repository_patch_model",
    "create_patch_service",
    "preview_repository_patch",
]