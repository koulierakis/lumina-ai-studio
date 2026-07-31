"""Secure backup, rollback, and unified-diff services for LUMINA Code Builder.

The service stores repository backups under:

    <repository_root>/.lumina/backups/<backup_id>/

Each backup contains:

    manifest.json
    files/

The manifest records every selected path, its original state, size, SHA-256
digest, backup location, and rollback metadata.

Security guarantees:

- Every source and destination path must remain inside the configured repository.
- Path traversal and absolute user-supplied paths are rejected.
- Internal LUMINA backup storage cannot be backed up or overwritten directly.
- Protected files and directories are rejected.
- Backup writes use temporary files and atomic replacement.
- Rollback verifies backup integrity before changing repository files.
- A rollback safety backup is created before restoration.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_BACKUP_DIRECTORY = Path(".lumina") / "backups"
MANIFEST_FILENAME = "manifest.json"
BACKUP_FILES_DIRECTORY = "files"
BACKUP_ID_PATTERN = re.compile(
    r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}$"
)

DEFAULT_PROTECTED_PATH_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".env",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
    }
)

DEFAULT_PROTECTED_FILE_PATTERNS = (
    re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE),
    re.compile(r".*credentials.*", re.IGNORECASE),
    re.compile(r".*secrets?.*", re.IGNORECASE),
    re.compile(r".*api[_-]?keys?.*", re.IGNORECASE),
    re.compile(r".*passwords?.*", re.IGNORECASE),
    re.compile(r".*private[_-]?keys?.*", re.IGNORECASE),
    re.compile(r".*\.pem$", re.IGNORECASE),
    re.compile(r".*\.key$", re.IGNORECASE),
    re.compile(r".*\.p12$", re.IGNORECASE),
    re.compile(r".*\.pfx$", re.IGNORECASE),
)


class BackupServiceError(RuntimeError):
    """Base exception raised by the backup service."""


class InvalidRepositoryError(BackupServiceError):
    """Raised when the configured repository root is invalid."""


class UnsafePathError(BackupServiceError):
    """Raised when a path is outside the repository or otherwise unsafe."""


class ProtectedPathError(BackupServiceError):
    """Raised when an operation targets a protected path."""


class BackupNotFoundError(BackupServiceError):
    """Raised when a requested backup does not exist."""


class InvalidBackupError(BackupServiceError):
    """Raised when backup metadata or backup contents are invalid."""


class BackupIntegrityError(BackupServiceError):
    """Raised when a backup file fails integrity verification."""


class RollbackError(BackupServiceError):
    """Raised when rollback cannot be completed safely."""


@dataclass(frozen=True)
class BackupFileRecord:
    """Manifest record describing one repository path."""

    relative_path: str
    existed: bool
    is_file: bool
    size_bytes: int
    sha256: str | None
    backup_relative_path: str | None


@dataclass
class BackupManifest:
    """Serializable backup manifest."""

    schema_version: int
    backup_id: str
    repository_root: str
    created_at: str
    reason: str
    status: str
    files: list[BackupFileRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    rollback_count: int = 0
    last_rollback_at: str | None = None
    last_rollback_safety_backup_id: str | None = None


@dataclass(frozen=True)
class BackupResult:
    """Result returned after successful backup creation."""

    backup_id: str
    backup_directory: str
    manifest_path: str
    created_at: str
    file_count: int
    total_bytes: int
    reason: str


@dataclass(frozen=True)
class RollbackResult:
    """Result returned after successful rollback."""

    backup_id: str
    restored_files: tuple[str, ...]
    removed_files: tuple[str, ...]
    safety_backup_id: str | None
    completed_at: str


@dataclass(frozen=True)
class DiffResult:
    """Unified diff result for one file."""

    relative_path: str
    changed: bool
    old_sha256: str
    new_sha256: str
    unified_diff: str


class BackupService:
    """Manage secure repository backups, restoration, and code diffs."""

    def __init__(
        self,
        repository_root: str | Path,
        backup_directory: str | Path = DEFAULT_BACKUP_DIRECTORY,
        protected_path_names: Iterable[str] | None = None,
        protected_file_patterns: Sequence[re.Pattern[str]] | None = None,
    ) -> None:
        root = Path(repository_root).expanduser()

        if not root.exists():
            raise InvalidRepositoryError(
                f"Repository root does not exist: {root}"
            )

        if not root.is_dir():
            raise InvalidRepositoryError(
                f"Repository root is not a directory: {root}"
            )

        self._repository_root = root.resolve()

        configured_backup_directory = Path(backup_directory)

        if configured_backup_directory.is_absolute():
            resolved_backup_root = configured_backup_directory.resolve()
        else:
            resolved_backup_root = (
                self._repository_root / configured_backup_directory
            ).resolve()

        self._assert_inside_repository(resolved_backup_root)

        if resolved_backup_root == self._repository_root:
            raise InvalidRepositoryError(
                "Backup directory cannot be the repository root."
            )

        self._backup_root = resolved_backup_root
        self._backup_root.mkdir(parents=True, exist_ok=True)

        self._protected_path_names = frozenset(
            name.casefold()
            for name in (
                protected_path_names
                if protected_path_names is not None
                else DEFAULT_PROTECTED_PATH_NAMES
            )
        )

        self._protected_file_patterns = tuple(
            protected_file_patterns
            if protected_file_patterns is not None
            else DEFAULT_PROTECTED_FILE_PATTERNS
        )

        self._lock = threading.RLock()

    @property
    def repository_root(self) -> Path:
        """Return the resolved repository root."""

        return self._repository_root

    @property
    def backup_root(self) -> Path:
        """Return the resolved backup storage directory."""

        return self._backup_root

    def create_backup(
        self,
        relative_paths: Iterable[str | Path],
        reason: str = "Before Code Builder modification",
        metadata: Mapping[str, Any] | None = None,
    ) -> BackupResult:
        """Create a backup of selected repository files.

        Missing paths are recorded as ``existed=False``. This is necessary when
        the Code Builder intends to create a new file: rollback can then remove
        that newly created file.

        Directories are not accepted. The caller must provide explicit files.
        """

        normalized_paths = self._normalize_unique_paths(relative_paths)

        if not normalized_paths:
            raise ValueError("At least one repository file must be selected.")

        clean_reason = reason.strip()

        if not clean_reason:
            raise ValueError("Backup reason cannot be empty.")

        safe_metadata = self._normalize_metadata(metadata)

        with self._lock:
            backup_id = self._generate_backup_id()
            backup_directory = self._backup_directory(backup_id)
            files_directory = backup_directory / BACKUP_FILES_DIRECTORY

            if backup_directory.exists():
                raise BackupServiceError(
                    f"Backup directory already exists: {backup_directory}"
                )

            backup_directory.mkdir(parents=True, exist_ok=False)
            files_directory.mkdir(parents=True, exist_ok=False)

            records: list[BackupFileRecord] = []
            total_bytes = 0

            try:
                for relative_path in normalized_paths:
                    source = self._resolve_repository_path(
                        relative_path,
                        allow_missing=True,
                        allow_backup_storage=False,
                    )

                    if source.exists() and source.is_symlink():
                        raise UnsafePathError(
                            f"Symbolic links cannot be backed up: "
                            f"{relative_path}"
                        )

                    if source.exists() and source.is_dir():
                        raise UnsafePathError(
                            "Directories cannot be backed up directly. "
                            f"Provide explicit files instead: {relative_path}"
                        )

                    if not source.exists():
                        records.append(
                            BackupFileRecord(
                                relative_path=relative_path,
                                existed=False,
                                is_file=False,
                                size_bytes=0,
                                sha256=None,
                                backup_relative_path=None,
                            )
                        )
                        continue

                    size_bytes = source.stat().st_size
                    source_hash = self._sha256_file(source)
                    backup_file = files_directory / Path(relative_path)
                    backup_file.parent.mkdir(parents=True, exist_ok=True)

                    self._copy_file_atomic(source, backup_file)

                    copied_hash = self._sha256_file(backup_file)

                    if copied_hash != source_hash:
                        raise BackupIntegrityError(
                            f"Backup verification failed for: {relative_path}"
                        )

                    backup_relative_path = backup_file.relative_to(
                        backup_directory
                    ).as_posix()

                    records.append(
                        BackupFileRecord(
                            relative_path=relative_path,
                            existed=True,
                            is_file=True,
                            size_bytes=size_bytes,
                            sha256=source_hash,
                            backup_relative_path=backup_relative_path,
                        )
                    )
                    total_bytes += size_bytes

                created_at = self._utc_now()

                manifest = BackupManifest(
                    schema_version=1,
                    backup_id=backup_id,
                    repository_root=str(self._repository_root),
                    created_at=created_at,
                    reason=clean_reason,
                    status="completed",
                    files=records,
                    metadata=safe_metadata,
                )

                manifest_path = backup_directory / MANIFEST_FILENAME
                self._write_json_atomic(
                    manifest_path,
                    self._manifest_to_dict(manifest),
                )

                return BackupResult(
                    backup_id=backup_id,
                    backup_directory=str(backup_directory),
                    manifest_path=str(manifest_path),
                    created_at=created_at,
                    file_count=len(records),
                    total_bytes=total_bytes,
                    reason=clean_reason,
                )

            except Exception:
                shutil.rmtree(backup_directory, ignore_errors=True)
                raise

    def rollback(
        self,
        backup_id: str,
        create_safety_backup: bool = True,
    ) -> RollbackResult:
        """Restore repository files from a backup.

        Before restoration, the current versions of all affected files are
        optionally stored in a separate safety backup. If rollback fails after
        repository changes begin, the service attempts to restore that safety
        backup automatically.
        """

        validated_backup_id = self._validate_backup_id(backup_id)

        with self._lock:
            manifest = self.get_manifest(validated_backup_id)
            self._validate_manifest_integrity(manifest)

            affected_paths = [
                record.relative_path for record in manifest.files
            ]

            safety_backup_id: str | None = None

            if create_safety_backup:
                safety_result = self.create_backup(
                    affected_paths,
                    reason=f"Safety snapshot before rollback of "
                    f"{validated_backup_id}",
                    metadata={
                        "operation": "rollback_safety_backup",
                        "source_backup_id": validated_backup_id,
                    },
                )
                safety_backup_id = safety_result.backup_id

            restored_files: list[str] = []
            removed_files: list[str] = []
            repository_changes_started = False

            try:
                for record in manifest.files:
                    target = self._resolve_repository_path(
                        record.relative_path,
                        allow_missing=True,
                        allow_backup_storage=False,
                    )

                    repository_changes_started = True

                    if record.existed:
                        source = self._resolve_backup_file(
                            validated_backup_id,
                            record,
                        )

                        target.parent.mkdir(parents=True, exist_ok=True)
                        self._copy_file_atomic(source, target)

                        restored_hash = self._sha256_file(target)

                        if restored_hash != record.sha256:
                            raise BackupIntegrityError(
                                "Restored file hash does not match backup "
                                f"manifest: {record.relative_path}"
                            )

                        restored_files.append(record.relative_path)
                    else:
                        if target.exists():
                            if target.is_symlink():
                                raise UnsafePathError(
                                    "Rollback refuses to remove symbolic link: "
                                    f"{record.relative_path}"
                                )

                            if target.is_dir():
                                raise RollbackError(
                                    "Rollback expected a file but found a "
                                    f"directory: {record.relative_path}"
                                )

                            target.unlink()
                            self._remove_empty_parent_directories(
                                target.parent
                            )
                            removed_files.append(record.relative_path)

                completed_at = self._utc_now()
                manifest.rollback_count += 1
                manifest.last_rollback_at = completed_at
                manifest.last_rollback_safety_backup_id = safety_backup_id

                self._save_manifest(manifest)

                return RollbackResult(
                    backup_id=validated_backup_id,
                    restored_files=tuple(restored_files),
                    removed_files=tuple(removed_files),
                    safety_backup_id=safety_backup_id,
                    completed_at=completed_at,
                )

            except Exception as rollback_exception:
                recovery_exception: Exception | None = None

                if (
                    repository_changes_started
                    and safety_backup_id is not None
                ):
                    try:
                        self.rollback(
                            safety_backup_id,
                            create_safety_backup=False,
                        )
                    except Exception as exc:
                        recovery_exception = exc

                if recovery_exception is not None:
                    raise RollbackError(
                        "Rollback failed and automatic recovery from the "
                        f"safety backup also failed. Rollback error: "
                        f"{rollback_exception}. Recovery error: "
                        f"{recovery_exception}."
                    ) from rollback_exception

                raise RollbackError(
                    f"Rollback failed: {rollback_exception}"
                ) from rollback_exception

    def generate_unified_diff(
        self,
        relative_path: str | Path,
        old_content: str,
        new_content: str,
        context_lines: int = 3,
    ) -> DiffResult:
        """Generate a unified diff for two text versions of one file."""

        if context_lines < 0:
            raise ValueError("context_lines cannot be negative.")

        normalized_path = self._normalize_relative_path(relative_path)
        self._resolve_repository_path(
            normalized_path,
            allow_missing=True,
            allow_backup_storage=False,
        )

        normalized_old_content = self._normalize_text(old_content)
        normalized_new_content = self._normalize_text(new_content)

        old_lines = normalized_old_content.splitlines(keepends=True)
        new_lines = normalized_new_content.splitlines(keepends=True)

        diff_lines = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{normalized_path}",
            tofile=f"b/{normalized_path}",
            n=context_lines,
            lineterm="\n",
        )

        unified_diff = "".join(diff_lines)

        return DiffResult(
            relative_path=normalized_path,
            changed=normalized_old_content != normalized_new_content,
            old_sha256=self._sha256_text(normalized_old_content),
            new_sha256=self._sha256_text(normalized_new_content),
            unified_diff=unified_diff,
        )

    def generate_file_diff(
        self,
        relative_path: str | Path,
        new_content: str,
        context_lines: int = 3,
        encoding: str = "utf-8",
    ) -> DiffResult:
        """Generate a unified diff between a repository file and new content."""

        normalized_path = self._normalize_relative_path(relative_path)
        source = self._resolve_repository_path(
            normalized_path,
            allow_missing=True,
            allow_backup_storage=False,
        )

        if source.exists():
            if source.is_symlink():
                raise UnsafePathError(
                    f"Symbolic links cannot be diffed: {normalized_path}"
                )

            if not source.is_file():
                raise UnsafePathError(
                    f"Expected a file: {normalized_path}"
                )

            old_content = source.read_text(
                encoding=encoding,
                errors="strict",
            )
        else:
            old_content = ""

        return self.generate_unified_diff(
            relative_path=normalized_path,
            old_content=old_content,
            new_content=new_content,
            context_lines=context_lines,
        )

    def get_manifest(self, backup_id: str) -> BackupManifest:
        """Load and validate a backup manifest."""

        validated_backup_id = self._validate_backup_id(backup_id)
        manifest_path = (
            self._backup_directory(validated_backup_id)
            / MANIFEST_FILENAME
        )

        if not manifest_path.is_file():
            raise BackupNotFoundError(
                f"Backup manifest was not found: {validated_backup_id}"
            )

        try:
            payload = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidBackupError(
                f"Cannot read backup manifest: {validated_backup_id}"
            ) from exc

        return self._manifest_from_dict(payload)

    def list_backups(self) -> list[BackupManifest]:
        """Return all valid backups, newest first."""

        manifests: list[BackupManifest] = []

        with self._lock:
            for entry in self._backup_root.iterdir():
                if not entry.is_dir():
                    continue

                if not BACKUP_ID_PATTERN.fullmatch(entry.name):
                    continue

                try:
                    manifests.append(self.get_manifest(entry.name))
                except BackupServiceError:
                    continue

        manifests.sort(key=lambda item: item.created_at, reverse=True)
        return manifests

    def delete_backup(self, backup_id: str) -> None:
        """Delete one backup from internal backup storage."""

        validated_backup_id = self._validate_backup_id(backup_id)
        backup_directory = self._backup_directory(validated_backup_id)

        with self._lock:
            if not backup_directory.exists():
                raise BackupNotFoundError(
                    f"Backup was not found: {validated_backup_id}"
                )

            self._assert_inside_backup_root(backup_directory)
            shutil.rmtree(backup_directory)

    def verify_backup(self, backup_id: str) -> bool:
        """Verify manifest structure and all stored file hashes."""

        manifest = self.get_manifest(backup_id)
        self._validate_manifest_integrity(manifest)
        return True

    def _validate_manifest_integrity(
        self,
        manifest: BackupManifest,
    ) -> None:
        if manifest.status != "completed":
            raise InvalidBackupError(
                f"Backup is not complete: {manifest.backup_id}"
            )

        if Path(manifest.repository_root).resolve() != self._repository_root:
            raise InvalidBackupError(
                "Backup belongs to a different repository root."
            )

        for record in manifest.files:
            self._resolve_repository_path(
                record.relative_path,
                allow_missing=True,
                allow_backup_storage=False,
            )

            if not record.existed:
                if (
                    record.sha256 is not None
                    or record.backup_relative_path is not None
                ):
                    raise InvalidBackupError(
                        "Manifest contains invalid metadata for missing file: "
                        f"{record.relative_path}"
                    )
                continue

            source = self._resolve_backup_file(
                manifest.backup_id,
                record,
            )

            if source.stat().st_size != record.size_bytes:
                raise BackupIntegrityError(
                    f"Backup file size mismatch: {record.relative_path}"
                )

            actual_hash = self._sha256_file(source)

            if actual_hash != record.sha256:
                raise BackupIntegrityError(
                    f"Backup file hash mismatch: {record.relative_path}"
                )

    def _resolve_backup_file(
        self,
        backup_id: str,
        record: BackupFileRecord,
    ) -> Path:
        if not record.backup_relative_path:
            raise InvalidBackupError(
                "Backup manifest is missing backup file path for: "
                f"{record.relative_path}"
            )

        backup_directory = self._backup_directory(backup_id)
        source = (
            backup_directory / record.backup_relative_path
        ).resolve()

        self._assert_inside_directory(source, backup_directory)

        if not source.is_file():
            raise BackupNotFoundError(
                f"Stored backup file is missing: {record.relative_path}"
            )

        if source.is_symlink():
            raise UnsafePathError(
                f"Stored backup file cannot be a symbolic link: "
                f"{record.relative_path}"
            )

        return source

    def _save_manifest(self, manifest: BackupManifest) -> None:
        manifest_path = (
            self._backup_directory(manifest.backup_id)
            / MANIFEST_FILENAME
        )
        self._write_json_atomic(
            manifest_path,
            self._manifest_to_dict(manifest),
        )

    def _manifest_to_dict(
        self,
        manifest: BackupManifest,
    ) -> dict[str, Any]:
        return asdict(manifest)

    def _manifest_from_dict(
        self,
        payload: Mapping[str, Any],
    ) -> BackupManifest:
        try:
            raw_files = payload["files"]

            if not isinstance(raw_files, list):
                raise TypeError("Manifest files must be a list.")

            records = [
                BackupFileRecord(
                    relative_path=str(item["relative_path"]),
                    existed=bool(item["existed"]),
                    is_file=bool(item["is_file"]),
                    size_bytes=int(item["size_bytes"]),
                    sha256=(
                        str(item["sha256"])
                        if item.get("sha256") is not None
                        else None
                    ),
                    backup_relative_path=(
                        str(item["backup_relative_path"])
                        if item.get("backup_relative_path") is not None
                        else None
                    ),
                )
                for item in raw_files
            ]

            manifest = BackupManifest(
                schema_version=int(payload["schema_version"]),
                backup_id=self._validate_backup_id(
                    str(payload["backup_id"])
                ),
                repository_root=str(payload["repository_root"]),
                created_at=str(payload["created_at"]),
                reason=str(payload["reason"]),
                status=str(payload["status"]),
                files=records,
                metadata=dict(payload.get("metadata") or {}),
                rollback_count=int(payload.get("rollback_count", 0)),
                last_rollback_at=(
                    str(payload["last_rollback_at"])
                    if payload.get("last_rollback_at") is not None
                    else None
                ),
                last_rollback_safety_backup_id=(
                    str(payload["last_rollback_safety_backup_id"])
                    if payload.get(
                        "last_rollback_safety_backup_id"
                    ) is not None
                    else None
                ),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
        ) as exc:
            raise InvalidBackupError(
                "Backup manifest has an invalid structure."
            ) from exc

        if manifest.schema_version != 1:
            raise InvalidBackupError(
                "Unsupported backup manifest schema version: "
                f"{manifest.schema_version}"
            )

        seen_paths: set[str] = set()

        for record in manifest.files:
            normalized = self._normalize_relative_path(
                record.relative_path
            )

            if normalized != record.relative_path:
                raise InvalidBackupError(
                    "Backup manifest contains a non-normalized path: "
                    f"{record.relative_path}"
                )

            if normalized in seen_paths:
                raise InvalidBackupError(
                    f"Backup manifest contains duplicate path: {normalized}"
                )

            seen_paths.add(normalized)

            if record.size_bytes < 0:
                raise InvalidBackupError(
                    f"Invalid backup file size: {normalized}"
                )

            if record.existed and not record.is_file:
                raise InvalidBackupError(
                    f"Backup record is not a regular file: {normalized}"
                )

            if record.existed:
                if not record.sha256:
                    raise InvalidBackupError(
                        f"Backup hash is missing: {normalized}"
                    )

                if not re.fullmatch(
                    r"[a-f0-9]{64}",
                    record.sha256,
                ):
                    raise InvalidBackupError(
                        f"Backup hash is invalid: {normalized}"
                    )

        return manifest

    def _normalize_unique_paths(
        self,
        relative_paths: Iterable[str | Path],
    ) -> list[str]:
        normalized_paths: list[str] = []
        seen: set[str] = set()

        for value in relative_paths:
            normalized = self._normalize_relative_path(value)

            if normalized not in seen:
                seen.add(normalized)
                normalized_paths.append(normalized)

        normalized_paths.sort()
        return normalized_paths

    def _normalize_relative_path(
        self,
        value: str | Path,
    ) -> str:
        raw_value = str(value).strip().replace("\\", "/")

        if not raw_value:
            raise UnsafePathError("Repository path cannot be empty.")

        candidate = Path(raw_value)

        if candidate.is_absolute():
            raise UnsafePathError(
                f"Absolute paths are not permitted: {raw_value}"
            )

        parts = [
            part
            for part in candidate.parts
            if part not in {"", "."}
        ]

        if not parts:
            raise UnsafePathError("Repository path cannot be empty.")

        if any(part == ".." for part in parts):
            raise UnsafePathError(
                f"Path traversal is not permitted: {raw_value}"
            )

        normalized = Path(*parts).as_posix()

        self._assert_not_protected(normalized)
        return normalized

    def _resolve_repository_path(
        self,
        relative_path: str | Path,
        *,
        allow_missing: bool,
        allow_backup_storage: bool,
    ) -> Path:
        normalized = self._normalize_relative_path(relative_path)
        resolved = (self._repository_root / normalized).resolve()

        self._assert_inside_repository(resolved)

        if (
            not allow_backup_storage
            and self._is_inside_directory(
                resolved,
                self._backup_root,
            )
        ):
            raise ProtectedPathError(
                "Direct access to LUMINA backup storage is forbidden."
            )

        if not allow_missing and not resolved.exists():
            raise FileNotFoundError(normalized)

        return resolved

    def _assert_not_protected(self, relative_path: str) -> None:
        path = Path(relative_path)
        parts = [part.casefold() for part in path.parts]

        if any(
            part in self._protected_path_names
            for part in parts
        ):
            raise ProtectedPathError(
                f"Protected path cannot be modified: {relative_path}"
            )

        filename = path.name

        for pattern in self._protected_file_patterns:
            if pattern.fullmatch(filename):
                raise ProtectedPathError(
                    f"Protected file cannot be modified: {relative_path}"
                )

    def _assert_inside_repository(self, path: Path) -> None:
        self._assert_inside_directory(
            path.resolve(),
            self._repository_root,
        )

    def _assert_inside_backup_root(self, path: Path) -> None:
        self._assert_inside_directory(
            path.resolve(),
            self._backup_root,
        )

    @staticmethod
    def _assert_inside_directory(
        path: Path,
        parent: Path,
    ) -> None:
        resolved_path = path.resolve()
        resolved_parent = parent.resolve()

        try:
            resolved_path.relative_to(resolved_parent)
        except ValueError as exc:
            raise UnsafePathError(
                f"Path is outside the allowed directory: {resolved_path}"
            ) from exc

    @staticmethod
    def _is_inside_directory(
        path: Path,
        parent: Path,
    ) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    def _backup_directory(self, backup_id: str) -> Path:
        validated_backup_id = self._validate_backup_id(backup_id)
        directory = (self._backup_root / validated_backup_id).resolve()
        self._assert_inside_backup_root(directory)
        return directory

    @staticmethod
    def _validate_backup_id(backup_id: str) -> str:
        normalized = backup_id.strip()

        if not BACKUP_ID_PATTERN.fullmatch(normalized):
            raise InvalidBackupError(
                f"Invalid backup id: {backup_id}"
            )

        return normalized

    @staticmethod
    def _generate_backup_id() -> str:
        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        random_suffix = uuid.uuid4().hex[:12]
        return f"{timestamp}-{random_suffix}"

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file_handle:
            for chunk in iter(
                lambda: file_handle.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _sha256_text(content: str) -> str:
        return hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _normalize_text(content: str) -> str:
        if not isinstance(content, str):
            raise TypeError("Diff content must be a string.")

        if not content:
            return ""

        normalized = content.replace("\r\n", "\n").replace(
            "\r",
            "\n",
        )

        if not normalized.endswith("\n"):
            normalized += "\n"

        return normalized

    @staticmethod
    def _normalize_metadata(
        metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if metadata is None:
            return {}

        normalized = dict(metadata)

        try:
            json.dumps(normalized, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Backup metadata must be JSON serializable."
            ) from exc

        return normalized

    @staticmethod
    def _copy_file_atomic(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(destination.parent),
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)

                with source.open("rb") as source_file:
                    shutil.copyfileobj(
                        source_file,
                        temporary_file,
                        length=1024 * 1024,
                    )

                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            shutil.copystat(
                source,
                temporary_path,
                follow_symlinks=False,
            )
            os.replace(temporary_path, destination)
            temporary_path = None

        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _write_json_atomic(
        destination: Path,
        payload: Mapping[str, Any],
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(destination.parent),
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, destination)
            temporary_path = None

        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _remove_empty_parent_directories(
        self,
        start_directory: Path,
    ) -> None:
        current = start_directory.resolve()

        while current != self._repository_root:
            if self._is_inside_directory(
                current,
                self._backup_root,
            ):
                return

            try:
                current.rmdir()
            except OSError:
                return

            current = current.parent