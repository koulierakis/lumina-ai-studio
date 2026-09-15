"""Repository scanning and indexing services for LUMINA Code Builder.

This module provides safe, deterministic repository inspection.

Responsibilities include:

- Resolving and validating the repository root.
- Recursively scanning directories and files.
- Respecting configured exclusion rules.
- Detecting file types and architectural roles.
- Reading text files safely with UTF-8-first decoding.
- Detecting binary files.
- Calculating SHA-256 file hashes.
- Counting lines without corrupting Windows text files.
- Extracting basic Python and JavaScript/TypeScript symbols.
- Extracting imports and dependency references.
- Producing data compatible with the Pydantic models in models.py.
- Building a repository map that can later be persisted as JSON.

The JSON index persistence, repository tree generation, framework detection,
and public analysis methods continue in Part 2 of this file.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Iterable, Iterator, Sequence
from uuid import UUID, uuid4

from .models import (
    CodebaseAnalysis,
    CodebaseAnalysisRequest,
    CodeSymbol,
    FileContent,
    FileMetadata,
    FileRole,
    FileType,
    ImportReference,
    RepositoryConfiguration,
    RepositoryStatistics,
    RepositoryTreeNode,
    RepositoryTreeResponse,
    SourceLocation,
)
from .security import (
    BlockedFileError,
    UnsafePathError,
    evaluate_safe_path,
    validate_safe_path,
)


class RepositoryServiceError(RuntimeError):
    """Base exception for repository service failures."""


class RepositoryNotFoundError(RepositoryServiceError):
    """Raised when the configured repository root does not exist."""


class RepositoryAccessError(RepositoryServiceError):
    """Raised when repository files cannot be accessed safely."""


class RepositoryIndexError(RepositoryServiceError):
    """Raised when repository index persistence fails."""


class UnsupportedFileEncodingError(RepositoryServiceError):
    """Raised when a text file cannot be decoded safely."""


UTC = UTC

DEFAULT_INDEX_DIRECTORY: Final[str] = ".lumina"
DEFAULT_INDEX_FILE_NAME: Final[str] = "code_builder_repository_index.json"

TEXT_SAMPLE_SIZE: Final[int] = 8_192
HASH_CHUNK_SIZE: Final[int] = 1024 * 1024
DEFAULT_READ_LIMIT_BYTES: Final[int] = 10_000_000

LIKELY_BINARY_BYTES: Final[bytes] = bytes(
    [
        0x00,
        0x01,
        0x02,
        0x03,
        0x04,
        0x05,
        0x06,
        0x07,
        0x08,
        0x0B,
        0x0C,
        0x0E,
        0x0F,
        0x10,
        0x11,
        0x12,
        0x13,
        0x14,
        0x15,
        0x16,
        0x17,
        0x18,
        0x19,
        0x1A,
        0x1B,
        0x1C,
        0x1D,
        0x1E,
        0x1F,
    ]
)

FILE_TYPE_BY_SUFFIX: Final[dict[str, FileType]] = {
    ".py": FileType.PYTHON,
    ".pyi": FileType.PYTHON,
    ".ts": FileType.TYPESCRIPT,
    ".mts": FileType.TYPESCRIPT,
    ".cts": FileType.TYPESCRIPT,
    ".js": FileType.JAVASCRIPT,
    ".mjs": FileType.JAVASCRIPT,
    ".cjs": FileType.JAVASCRIPT,
    ".jsx": FileType.JSX,
    ".tsx": FileType.TSX,
    ".json": FileType.JSON,
    ".jsonc": FileType.JSON,
    ".yaml": FileType.YAML,
    ".yml": FileType.YAML,
    ".toml": FileType.TOML,
    ".md": FileType.MARKDOWN,
    ".mdx": FileType.MARKDOWN,
    ".html": FileType.HTML,
    ".htm": FileType.HTML,
    ".css": FileType.CSS,
    ".scss": FileType.SCSS,
    ".sass": FileType.SCSS,
    ".sh": FileType.SHELL,
    ".bash": FileType.SHELL,
    ".zsh": FileType.SHELL,
    ".ps1": FileType.POWERSHELL,
    ".psm1": FileType.POWERSHELL,
    ".psd1": FileType.POWERSHELL,
    ".sql": FileType.SQL,
    ".txt": FileType.TEXT,
    ".ini": FileType.TEXT,
    ".cfg": FileType.TEXT,
    ".conf": FileType.TEXT,
    ".properties": FileType.TEXT,
    ".csv": FileType.TEXT,
    ".xml": FileType.TEXT,
    ".graphql": FileType.TEXT,
    ".gql": FileType.TEXT,
    ".dockerfile": FileType.TEXT,
}

LANGUAGE_BY_FILE_TYPE: Final[dict[FileType, str]] = {
    FileType.PYTHON: "Python",
    FileType.TYPESCRIPT: "TypeScript",
    FileType.JAVASCRIPT: "JavaScript",
    FileType.JSX: "JavaScript JSX",
    FileType.TSX: "TypeScript TSX",
    FileType.JSON: "JSON",
    FileType.YAML: "YAML",
    FileType.TOML: "TOML",
    FileType.MARKDOWN: "Markdown",
    FileType.HTML: "HTML",
    FileType.CSS: "CSS",
    FileType.SCSS: "SCSS",
    FileType.SHELL: "Shell",
    FileType.POWERSHELL: "PowerShell",
    FileType.SQL: "SQL",
    FileType.TEXT: "Text",
}

KNOWN_TEXT_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "dockerfile",
        "makefile",
        "procfile",
        "license",
        "licence",
        "readme",
        "changelog",
        "authors",
        "contributors",
        "notice",
        "manifest.in",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "pipfile",
        "pipfile.lock",
        "poetry.lock",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "tox.ini",
        "pytest.ini",
        "mypy.ini",
        "ruff.toml",
        "tsconfig.json",
        "vite.config.js",
        "vite.config.ts",
        "webpack.config.js",
        "webpack.config.ts",
        ".gitignore",
        ".dockerignore",
        ".editorconfig",
        ".prettierrc",
        ".prettierignore",
        ".eslintignore",
    }
)

BINARY_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".7z",
        ".a",
        ".avi",
        ".bin",
        ".bmp",
        ".bz2",
        ".class",
        ".com",
        ".db",
        ".dll",
        ".dmg",
        ".doc",
        ".docx",
        ".dylib",
        ".eot",
        ".exe",
        ".flac",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".lib",
        ".lockb",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".msi",
        ".o",
        ".obj",
        ".ogg",
        ".otf",
        ".pdf",
        ".pkl",
        ".png",
        ".pyc",
        ".pyd",
        ".rar",
        ".so",
        ".sqlite",
        ".sqlite3",
        ".tar",
        ".tif",
        ".tiff",
        ".ttf",
        ".wav",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".xz",
        ".zip",
    }
)

GENERATED_FILE_PATTERNS: Final[tuple[str, ...]] = (
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.bundle.js",
    "*.bundle.css",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.generated.*",
    "*.gen.*",
    "openapi.json",
    "openapi.yaml",
)

TEST_FILE_PATTERNS: Final[tuple[str, ...]] = (
    "test_*.py",
    "*_test.py",
    "*.test.js",
    "*.test.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.js",
    "*.spec.jsx",
    "*.spec.ts",
    "*.spec.tsx",
)

CONFIG_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "setup.py",
        "setup.cfg",
        "tox.ini",
        "pytest.ini",
        "mypy.ini",
        "ruff.toml",
        "tsconfig.json",
        "jsconfig.json",
        "vite.config.js",
        "vite.config.ts",
        "webpack.config.js",
        "webpack.config.ts",
        "babel.config.js",
        "babel.config.json",
        "eslint.config.js",
        "eslint.config.mjs",
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.json",
        ".prettierrc",
        ".prettierrc.json",
        ".editorconfig",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
    }
)

DOCUMENTATION_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".md",
        ".mdx",
        ".rst",
        ".txt",
    }
)

ASSET_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".bmp",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".mp3",
        ".wav",
        ".ogg",
        ".mp4",
        ".webm",
    }
)

PYTHON_ENCODING_COOKIE_PATTERN: Final[re.Pattern[bytes]] = re.compile(
    br"coding[:=]\s*([-\w.]+)"
)

JS_IMPORT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    (?:
        import
        \s+
        (?:
            (?P<bindings>[\s\S]*?)
            \s+from\s+
        )?
        ["']
        (?P<module>[^"']+)
        ["']
    )
    |
    (?:
        require
        \s*\(
        \s*["']
        (?P<require_module>[^"']+)
        ["']
        \s*\)
    )
    |
    (?:
        import
        \s*\(
        \s*["']
        (?P<dynamic_module>[^"']+)
        ["']
        \s*\)
    )
    """,
    flags=re.MULTILINE | re.VERBOSE,
)

JS_EXPORT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    ^\s*
    export
    \s+
    (?:
        default
        \s+
    )?
    (?:
        async
        \s+
    )?
    (?P<kind>class|function|const|let|var|interface|type|enum)
    \s+
    (?P<name>[A-Za-z_$][A-Za-z0-9_$]*)
    """,
    flags=re.MULTILINE | re.VERBOSE,
)

JS_DECLARATION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    ^\s*
    (?:
        export
        \s+
        (?:
            default
            \s+
        )?
    )?
    (?:
        async
        \s+
    )?
    (?P<kind>class|function|const|let|var|interface|type|enum)
    \s+
    (?P<name>[A-Za-z_$][A-Za-z0-9_$]*)
    """,
    flags=re.MULTILINE | re.VERBOSE,
)

REACT_COMPONENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    ^\s*
    (?:
        export
        \s+
        (?:
            default
            \s+
        )?
    )?
    (?:
        const
        \s+
        (?P<const_name>[A-Z][A-Za-z0-9_$]*)
        \s*=
        \s*
        (?:
            React\.
        )?
        (?:
            memo
            \s*\(
        )?
        (?:
            async
            \s+
        )?
        \(?
        [^=\n]*
        \)?
        \s*
        =>
    )
    |
    (?:
        function
        \s+
        (?P<function_name>[A-Z][A-Za-z0-9_$]*)
        \s*\(
    )
    """,
    flags=re.MULTILINE | re.VERBOSE,
)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(UTC)


def _normalize_relative_path(path: Path) -> str:
    """Return a repository-relative path with POSIX separators."""

    return path.as_posix()


def _safe_stat(path: Path) -> os.stat_result | None:
    """Return file metadata or None when the file cannot be inspected."""

    try:
        return path.stat()
    except (OSError, PermissionError):
        return None


def _matches_any_pattern(value: str, patterns: Iterable[str]) -> bool:
    """Return whether a value matches at least one case-insensitive pattern."""

    lowered = value.casefold()

    return any(
        fnmatch.fnmatch(lowered, pattern.casefold())
        for pattern in patterns
    )


def _deduplicate_preserve_order(values: Iterable[str]) -> list[str]:
    """Remove duplicates while preserving original ordering."""

    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)

    return result


class RepositoryService:
    """Safe repository scanner and index builder.

    The service is initialized with a repository configuration and then used
    to scan, inspect, read, and index files under that repository root.

    The instance does not execute repository code.
    """

    def __init__(
        self,
        configuration: RepositoryConfiguration,
        *,
        index_directory_name: str = DEFAULT_INDEX_DIRECTORY,
        index_file_name: str = DEFAULT_INDEX_FILE_NAME,
    ) -> None:
        """Initialize the repository service.

        Args:
            configuration:
                Repository scan configuration defined in models.py.
            index_directory_name:
                Internal directory used for the generated JSON index.
            index_file_name:
                JSON index filename.

        Raises:
            RepositoryNotFoundError:
                If the configured repository does not exist.
            RepositoryAccessError:
                If the repository root cannot be safely resolved.
        """

        self.configuration = configuration

        try:
            self.repository_root = Path(
                configuration.repository_root
            ).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RepositoryAccessError(
                f"Failed to resolve repository root: {exc}"
            ) from exc

        if not self.repository_root.exists():
            raise RepositoryNotFoundError(
                f"Repository root does not exist: {self.repository_root}"
            )

        if not self.repository_root.is_dir():
            raise RepositoryAccessError(
                f"Repository root is not a directory: {self.repository_root}"
            )

        self.index_directory_name = index_directory_name.strip()
        self.index_file_name = index_file_name.strip()

        if not self.index_directory_name:
            raise RepositoryIndexError(
                "The repository index directory name cannot be empty."
            )

        if not self.index_file_name:
            raise RepositoryIndexError(
                "The repository index filename cannot be empty."
            )

        if Path(self.index_directory_name).is_absolute():
            raise RepositoryIndexError(
                "The repository index directory must be relative."
            )

        if Path(self.index_file_name).is_absolute():
            raise RepositoryIndexError(
                "The repository index filename must be relative."
            )

        self.index_directory = (
            self.repository_root / self.index_directory_name
        ).resolve(strict=False)

        self.index_path = (
            self.index_directory / self.index_file_name
        ).resolve(strict=False)

        try:
            self.index_directory.relative_to(self.repository_root)
            self.index_path.relative_to(self.repository_root)
        except ValueError as exc:
            raise RepositoryIndexError(
                "The repository index path escapes the repository root."
            ) from exc

        self._warnings: list[str] = []
        self._errors: list[str] = []

    @classmethod
    def from_request(
        cls,
        request: CodebaseAnalysisRequest,
    ) -> RepositoryService:
        """Create a repository service from an analysis request."""

        return cls(configuration=request.configuration)

    @property
    def warnings(self) -> list[str]:
        """Return a copy of accumulated non-fatal warnings."""

        return list(self._warnings)

    @property
    def errors(self) -> list[str]:
        """Return a copy of accumulated scan errors."""

        return list(self._errors)

    def clear_messages(self) -> None:
        """Clear accumulated warnings and errors."""

        self._warnings.clear()
        self._errors.clear()

    def _relative_path(self, path: Path) -> Path:
        """Return path relative to the repository root."""

        resolved = path.resolve(strict=False)

        try:
            return resolved.relative_to(self.repository_root)
        except ValueError as exc:
            raise RepositoryAccessError(
                f"Path is outside the repository: {resolved}"
            ) from exc

    def _relative_path_string(self, path: Path) -> str:
        """Return normalized repository-relative path string."""

        return _normalize_relative_path(self._relative_path(path))

    def _is_hidden_path(self, relative_path: Path) -> bool:
        """Return whether any component of a relative path is hidden."""

        return any(
            part.startswith(".") and part not in {".", ".."}
            for part in relative_path.parts
        )

    def _is_excluded_directory(self, relative_path: Path) -> bool:
        """Return whether a directory must be excluded from scanning."""

        if not relative_path.parts:
            return False

        directory_name = relative_path.name
        relative_text = _normalize_relative_path(relative_path)

        excluded_names = {
            value.casefold()
            for value in self.configuration.excluded_directories
        }

        if directory_name.casefold() in excluded_names:
            return True

        for configured_value in self.configuration.excluded_directories:
            normalized = configured_value.replace("\\", "/").strip("/")

            if not normalized:
                continue

            if fnmatch.fnmatch(
                relative_text.casefold(),
                normalized.casefold(),
            ):
                return True

        if (
            not self.configuration.include_hidden_files
            and self._is_hidden_path(relative_path)
        ):
            return True

        return False

    def _is_excluded_file(self, relative_path: Path) -> bool:
        """Return whether a file matches configured exclusion rules."""

        relative_text = _normalize_relative_path(relative_path)
        file_name = relative_path.name

        if (
            not self.configuration.include_hidden_files
            and self._is_hidden_path(relative_path)
        ):
            return True

        for pattern in self.configuration.excluded_file_patterns:
            normalized_pattern = pattern.replace("\\", "/")

            if fnmatch.fnmatch(
                file_name.casefold(),
                normalized_pattern.casefold(),
            ):
                return True

            if fnmatch.fnmatch(
                relative_text.casefold(),
                normalized_pattern.casefold(),
            ):
                return True

        return False

    def _is_index_artifact(self, path: Path) -> bool:
        """Return whether a path is the generated repository index."""

        try:
            return (
                path.resolve(strict=False)
                == self.index_path.resolve(strict=False)
            )
        except (OSError, RuntimeError):
            return False

    def _is_safe_scan_target(self, path: Path) -> bool:
        """Return whether a discovered path remains inside the repository.

        Scanning allows reading ordinary repository files while still
        preventing path escapes. The blocked-file policy is intentionally
        checked separately so metadata can mark protected files without
        reading their contents.
        """

        try:
            relative_path = self._relative_path(path)
        except RepositoryAccessError:
            return False

        decision = evaluate_safe_path(
            repository_root=self.repository_root,
            requested_path=relative_path,
            allow_absolute=False,
            require_exists=False,
            allow_repository_root=False,
            check_blocked=False,
        )

        return decision.allowed

    def iter_repository_files(self) -> Iterator[Path]:
        """Yield repository files in deterministic path order.

        Directory symlinks are not followed unless explicitly enabled.
        Files that escape the repository through symlinks are always skipped.
        """

        follow_symlinks = self.configuration.follow_symlinks

        for current_root, directory_names, file_names in os.walk(
            self.repository_root,
            topdown=True,
            followlinks=follow_symlinks,
        ):
            current_path = Path(current_root)

            safe_directories: list[str] = []

            for directory_name in sorted(
                directory_names,
                key=str.casefold,
            ):
                directory_path = current_path / directory_name

                try:
                    relative_directory = self._relative_path(
                        directory_path
                    )
                except RepositoryAccessError:
                    self._warnings.append(
                        "Skipped directory outside repository: "
                        f"{directory_path}"
                    )
                    continue

                if self._is_excluded_directory(relative_directory):
                    continue

                if directory_path.is_symlink() and not follow_symlinks:
                    self._warnings.append(
                        "Skipped directory symlink: "
                        f"{relative_directory.as_posix()}"
                    )
                    continue

                if not self._is_safe_scan_target(directory_path):
                    self._warnings.append(
                        "Skipped unsafe directory path: "
                        f"{relative_directory.as_posix()}"
                    )
                    continue

                safe_directories.append(directory_name)

            directory_names[:] = safe_directories

            for file_name in sorted(file_names, key=str.casefold):
                file_path = current_path / file_name

                try:
                    relative_file = self._relative_path(file_path)
                except RepositoryAccessError:
                    self._warnings.append(
                        f"Skipped file outside repository: {file_path}"
                    )
                    continue

                if self._is_excluded_file(relative_file):
                    continue

                if self._is_index_artifact(file_path):
                    continue

                if file_path.is_symlink():
                    if not follow_symlinks:
                        self._warnings.append(
                            "Skipped file symlink: "
                            f"{relative_file.as_posix()}"
                        )
                        continue

                    try:
                        resolved_target = file_path.resolve(strict=True)
                        resolved_target.relative_to(self.repository_root)
                    except (OSError, RuntimeError, ValueError):
                        self._warnings.append(
                            "Skipped symlink escaping repository: "
                            f"{relative_file.as_posix()}"
                        )
                        continue

                if not self._is_safe_scan_target(file_path):
                    self._warnings.append(
                        "Skipped unsafe file path: "
                        f"{relative_file.as_posix()}"
                    )
                    continue

                if not file_path.is_file():
                    continue

                yield file_path

    def detect_file_type(self, path: Path) -> FileType:
        """Detect a repository file type from its name and suffix."""

        file_name = path.name.casefold()
        suffix = path.suffix.casefold()

        if file_name == "dockerfile" or file_name.startswith("dockerfile."):
            return FileType.TEXT

        if suffix in FILE_TYPE_BY_SUFFIX:
            return FILE_TYPE_BY_SUFFIX[suffix]

        if file_name in KNOWN_TEXT_FILE_NAMES:
            return FileType.TEXT

        if suffix in BINARY_SUFFIXES:
            return FileType.BINARY

        return FileType.UNKNOWN

    def detect_file_role(
        self,
        relative_path: Path,
        *,
        file_type: FileType,
        is_generated: bool,
        is_protected: bool,
    ) -> FileRole:
        """Classify the architectural role of a repository file."""

        file_name = relative_path.name.casefold()
        suffix = relative_path.suffix.casefold()
        lowered_parts = {part.casefold() for part in relative_path.parts}

        if is_protected:
            return FileRole.SECRET

        if is_generated:
            return FileRole.GENERATED

        if lowered_parts.intersection(
            {
                "node_modules",
                "vendor",
                "site-packages",
                "venv",
                ".venv",
            }
        ):
            return FileRole.DEPENDENCY

        if lowered_parts.intersection(
            {
                "dist",
                "build",
                "out",
                "target",
                "coverage",
                "htmlcov",
            }
        ):
            return FileRole.BUILD_ARTIFACT

        if (
            "test" in lowered_parts
            or "tests" in lowered_parts
            or "__tests__" in lowered_parts
            or _matches_any_pattern(file_name, TEST_FILE_PATTERNS)
        ):
            return FileRole.TEST

        if file_name in CONFIG_FILE_NAMES:
            return FileRole.CONFIGURATION

        if (
            suffix in DOCUMENTATION_SUFFIXES
            or "docs" in lowered_parts
            or "documentation" in lowered_parts
        ):
            return FileRole.DOCUMENTATION

        if suffix in ASSET_SUFFIXES:
            return FileRole.ASSET

        if file_type in {
            FileType.PYTHON,
            FileType.TYPESCRIPT,
            FileType.JAVASCRIPT,
            FileType.JSX,
            FileType.TSX,
            FileType.HTML,
            FileType.CSS,
            FileType.SCSS,
            FileType.SHELL,
            FileType.POWERSHELL,
            FileType.SQL,
        }:
            return FileRole.SOURCE

        return FileRole.UNKNOWN

    def is_generated_file(self, relative_path: Path) -> bool:
        """Return whether a file appears to be generated output."""

        relative_text = relative_path.as_posix()

        if _matches_any_pattern(
            relative_path.name,
            GENERATED_FILE_PATTERNS,
        ):
            return True

        generated_parts = {
            "generated",
            "gen",
            "dist",
            "build",
            "out",
            "target",
        }

        if any(
            part.casefold() in generated_parts
            for part in relative_path.parts[:-1]
        ):
            return True

        generated_markers = (
            "/generated/",
            "/__generated__/",
            "/dist/",
            "/build/",
        )

        normalized = f"/{relative_text.casefold()}/"

        return any(marker in normalized for marker in generated_markers)

    def is_binary_file(self, path: Path) -> bool:
        """Detect whether a file is binary.

        Detection uses known binary suffixes followed by a byte sample check.
        UTF-8, UTF-16, and UTF-32 BOMs are treated as text indicators.
        """

        suffix = path.suffix.casefold()

        if suffix in BINARY_SUFFIXES:
            return True

        try:
            with path.open("rb") as file_handle:
                sample = file_handle.read(TEXT_SAMPLE_SIZE)
        except (OSError, PermissionError) as exc:
            self._warnings.append(
                f"Could not inspect file type for "
                f"{self._relative_path_string(path)}: {exc}"
            )
            return True

        if not sample:
            return False

        text_boms = (
            b"\xef\xbb\xbf",
            b"\xff\xfe",
            b"\xfe\xff",
            b"\xff\xfe\x00\x00",
            b"\x00\x00\xfe\xff",
        )

        if sample.startswith(text_boms):
            return False

        if b"\x00" in sample:
            return True

        control_character_count = sum(
            byte in LIKELY_BINARY_BYTES
            for byte in sample
        )

        return (
            control_character_count / len(sample)
            > 0.10
        )

    def detect_text_encoding(
        self,
        path: Path,
        *,
        sample: bytes | None = None,
    ) -> str:
        """Detect a safe text encoding using UTF-8-first rules.

        The method supports common Windows encodings without silently
        replacing invalid bytes.

        Detection order:

        1. UTF-8 BOM
        2. UTF-32 BOM
        3. UTF-16 BOM
        4. Python source encoding cookie
        5. Strict UTF-8
        6. Windows-1252
        7. ISO-8859-1 as a final lossless fallback
        """

        if sample is None:
            try:
                with path.open("rb") as file_handle:
                    sample = file_handle.read(TEXT_SAMPLE_SIZE)
            except (OSError, PermissionError) as exc:
                raise RepositoryAccessError(
                    f"Cannot read file for encoding detection: {path}"
                ) from exc

        if sample.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"

        if sample.startswith(b"\xff\xfe\x00\x00"):
            return "utf-32-le"

        if sample.startswith(b"\x00\x00\xfe\xff"):
            return "utf-32-be"

        if sample.startswith(b"\xff\xfe"):
            return "utf-16-le"

        if sample.startswith(b"\xfe\xff"):
            return "utf-16-be"

        if path.suffix.casefold() in {".py", ".pyi"}:
            first_two_lines = b"\n".join(sample.splitlines()[:2])
            cookie_match = PYTHON_ENCODING_COOKIE_PATTERN.search(
                first_two_lines
            )

            if cookie_match:
                declared_encoding = cookie_match.group(1).decode(
                    "ascii",
                    errors="strict",
                )

                try:
                    sample.decode(declared_encoding, errors="strict")
                    return declared_encoding
                except (LookupError, UnicodeDecodeError):
                    self._warnings.append(
                        "Invalid Python encoding declaration in "
                        f"{self._relative_path_string(path)}: "
                        f"{declared_encoding}"
                    )

        try:
            sample.decode("utf-8", errors="strict")
            return "utf-8"
        except UnicodeDecodeError:
            pass

        try:
            sample.decode("cp1252", errors="strict")
            return "cp1252"
        except UnicodeDecodeError:
            return "iso-8859-1"

    def calculate_sha256(self, path: Path) -> str:
        """Calculate the SHA-256 digest of a repository file."""

        digest = hashlib.sha256()

        try:
            with path.open("rb") as file_handle:
                while True:
                    chunk = file_handle.read(HASH_CHUNK_SIZE)

                    if not chunk:
                        break

                    digest.update(chunk)
        except (OSError, PermissionError) as exc:
            raise RepositoryAccessError(
                f"Failed to calculate hash for {path}: {exc}"
            ) from exc

        return digest.hexdigest()

    def read_text_file(
        self,
        path: str | Path,
        *,
        maximum_bytes: int = DEFAULT_READ_LIMIT_BYTES,
        allow_protected: bool = False,
    ) -> FileContent:
        """Read a repository text file safely.

        Args:
            path:
                Repository-relative path or a Path under the repository.
            maximum_bytes:
                Maximum file size accepted for reading.
            allow_protected:
                Internal override for explicitly authorized protected reads.
                This should remain False for AI-generated operations.

        Returns:
            FileContent compatible with models.py.

        Raises:
            BlockedFileError:
                If the target is protected.
            RepositoryAccessError:
                If the target cannot be read.
            UnsupportedFileEncodingError:
                If decoding fails.
        """

        requested_path = Path(path)

        if requested_path.is_absolute():
            try:
                relative_path = requested_path.resolve(
                    strict=False
                ).relative_to(self.repository_root)
            except ValueError as exc:
                raise RepositoryAccessError(
                    f"File is outside the repository: {requested_path}"
                ) from exc
        else:
            relative_path = requested_path

        try:
            resolved_path = validate_safe_path(
                repository_root=self.repository_root,
                requested_path=relative_path,
                allow_absolute=False,
                require_exists=True,
                allow_repository_root=False,
                check_blocked=not allow_protected,
            )
        except (UnsafePathError, BlockedFileError):
            raise
        except Exception as exc:
            raise RepositoryAccessError(
                f"Failed to validate repository file: {relative_path}"
            ) from exc

        if not resolved_path.is_file():
            raise RepositoryAccessError(
                f"Requested path is not a file: {resolved_path}"
            )

        stat_result = _safe_stat(resolved_path)

        if stat_result is None:
            raise RepositoryAccessError(
                f"Cannot inspect repository file: {resolved_path}"
            )

        if stat_result.st_size > maximum_bytes:
            raise RepositoryAccessError(
                "File exceeds the maximum readable size of "
                f"{maximum_bytes} bytes: "
                f"{self._relative_path_string(resolved_path)}"
            )

        if self.is_binary_file(resolved_path):
            raise RepositoryAccessError(
                "Binary files cannot be read as source text: "
                f"{self._relative_path_string(resolved_path)}"
            )

        try:
            raw_content = resolved_path.read_bytes()
        except (OSError, PermissionError) as exc:
            raise RepositoryAccessError(
                f"Failed to read repository file: {resolved_path}"
            ) from exc

        encoding = (
            self.detect_text_encoding(
                resolved_path,
                sample=raw_content[:TEXT_SAMPLE_SIZE],
            )
            if self.configuration.detect_encoding
            else "utf-8"
        )

        try:
            content = raw_content.decode(
                encoding,
                errors="strict",
            )
        except (LookupError, UnicodeDecodeError) as exc:
            raise UnsupportedFileEncodingError(
                "Failed to decode repository file "
                f"{self._relative_path_string(resolved_path)} "
                f"using {encoding}: {exc}"
            ) from exc

        relative_text = self._relative_path_string(resolved_path)

        return FileContent(
            relative_path=relative_text,
            content=content,
            encoding=encoding,
            sha256=hashlib.sha256(raw_content).hexdigest(),
            line_count=self._count_text_lines(content),
            size_bytes=len(raw_content),
            loaded_at=utc_now(),
        )

    @staticmethod
    def _count_text_lines(content: str) -> int:
        """Count logical text lines consistently across Windows and POSIX."""

        if not content:
            return 0

        line_count = len(content.splitlines())

        if content.endswith(("\n", "\r")):
            return line_count

        return max(line_count, 1)

    def _is_protected_file(
        self,
        relative_path: Path,
    ) -> tuple[bool, str | None]:
        """Return protected status and a human-readable reason."""

        decision = evaluate_safe_path(
            repository_root=self.repository_root,
            requested_path=relative_path,
            allow_absolute=False,
            require_exists=False,
            allow_repository_root=False,
            check_blocked=True,
        )

        if decision.allowed:
            return False, None

        return True, decision.message

    def build_file_metadata(self, path: Path) -> FileMetadata:
        """Build metadata for one repository file."""

        relative_path = self._relative_path(path)
        relative_text = relative_path.as_posix()
        stat_result = _safe_stat(path)

        if stat_result is None:
            raise RepositoryAccessError(
                f"Cannot inspect repository file: {relative_text}"
            )

        file_type = self.detect_file_type(path)
        is_binary = (
            file_type == FileType.BINARY
            or self.is_binary_file(path)
        )
        is_generated = self.is_generated_file(relative_path)
        is_protected, protection_reason = self._is_protected_file(
            relative_path
        )

        encoding: str | None = None
        line_count: int | None = None
        digest: str | None = None

        if self.configuration.calculate_hashes:
            try:
                digest = self.calculate_sha256(path)
            except RepositoryAccessError as exc:
                self._warnings.append(str(exc))

        if not is_binary and not is_protected:
            if stat_result.st_size <= self.configuration.maximum_file_size_bytes:
                try:
                    raw_content = path.read_bytes()

                    encoding = (
                        self.detect_text_encoding(
                            path,
                            sample=raw_content[:TEXT_SAMPLE_SIZE],
                        )
                        if self.configuration.detect_encoding
                        else "utf-8"
                    )

                    decoded = raw_content.decode(
                        encoding,
                        errors="strict",
                    )
                    line_count = self._count_text_lines(decoded)
                except (
                    OSError,
                    PermissionError,
                    LookupError,
                    UnicodeDecodeError,
                ) as exc:
                    self._warnings.append(
                        "Could not decode file for metadata: "
                        f"{relative_text}: {exc}"
                    )
            else:
                self._warnings.append(
                    "Skipped text decoding because file exceeds configured "
                    f"limit: {relative_text}"
                )

        role = self.detect_file_role(
            relative_path,
            file_type=file_type,
            is_generated=is_generated,
            is_protected=is_protected,
        )

        modified_at = datetime.fromtimestamp(
            stat_result.st_mtime,
            tz=UTC,
        )

        return FileMetadata(
            relative_path=relative_text,
            file_name=path.name,
            extension=path.suffix.casefold(),
            file_type=file_type,
            role=role,
            size_bytes=stat_result.st_size,
            line_count=line_count,
            sha256=digest,
            encoding=encoding,
            is_binary=is_binary,
            is_symlink=path.is_symlink(),
            is_generated=is_generated,
            is_protected=is_protected,
            protection_reason=protection_reason,
            modified_at=modified_at,
            language=LANGUAGE_BY_FILE_TYPE.get(file_type),
        )

    def extract_python_symbols(
        self,
        relative_path: str,
        content: str,
    ) -> list[CodeSymbol]:
        """Extract Python symbols using the standard-library AST."""

        try:
            syntax_tree = ast.parse(
                content,
                filename=relative_path,
            )
        except SyntaxError as exc:
            self._warnings.append(
                f"Python syntax could not be parsed in "
                f"{relative_path}: {exc}"
            )
            return []

        symbols: list[CodeSymbol] = []

        def decorators_for(
            node: ast.FunctionDef
            | ast.AsyncFunctionDef
            | ast.ClassDef,
        ) -> list[str]:
            values: list[str] = []

            for decorator in node.decorator_list:
                try:
                    values.append(ast.unparse(decorator))
                except (AttributeError, ValueError):
                    values.append(
                        decorator.__class__.__name__
                    )

            return values

        def function_signature(
            node: ast.FunctionDef | ast.AsyncFunctionDef,
        ) -> str | None:
            try:
                prefix = "async def" if isinstance(
                    node,
                    ast.AsyncFunctionDef,
                ) else "def"

                arguments = ast.unparse(node.args)
                return_annotation = (
                    f" -> {ast.unparse(node.returns)}"
                    if node.returns is not None
                    else ""
                )

                return (
                    f"{prefix} {node.name}({arguments})"
                    f"{return_annotation}"
                )
            except (AttributeError, ValueError):
                return None

        def visit_body(
            body: Sequence[ast.stmt],
            parent_names: tuple[str, ...] = (),
        ) -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qualified_name = ".".join(
                        (*parent_names, node.name)
                    )

                    symbols.append(
                        CodeSymbol(
                            name=node.name,
                            qualified_name=qualified_name,
                            symbol_type="class",
                            location=SourceLocation(
                                relative_path=relative_path,
                                start_line=node.lineno,
                                end_line=getattr(
                                    node,
                                    "end_lineno",
                                    node.lineno,
                                ),
                                start_column=node.col_offset + 1,
                                end_column=(
                                    getattr(
                                        node,
                                        "end_col_offset",
                                        node.col_offset,
                                    )
                                    + 1
                                ),
                            ),
                            signature=f"class {node.name}",
                            docstring=ast.get_docstring(
                                node,
                                clean=False,
                            ),
                            decorators=decorators_for(node),
                            dependencies=[],
                            exported=not node.name.startswith("_"),
                        )
                    )

                    visit_body(
                        node.body,
                        (*parent_names, node.name),
                    )

                elif isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    qualified_name = ".".join(
                        (*parent_names, node.name)
                    )

                    symbol_type = (
                        "method"
                        if parent_names
                        else "function"
                    )

                    symbols.append(
                        CodeSymbol(
                            name=node.name,
                            qualified_name=qualified_name,
                            symbol_type=symbol_type,
                            location=SourceLocation(
                                relative_path=relative_path,
                                start_line=node.lineno,
                                end_line=getattr(
                                    node,
                                    "end_lineno",
                                    node.lineno,
                                ),
                                start_column=node.col_offset + 1,
                                end_column=(
                                    getattr(
                                        node,
                                        "end_col_offset",
                                        node.col_offset,
                                    )
                                    + 1
                                ),
                            ),
                            signature=function_signature(node),
                            docstring=ast.get_docstring(
                                node,
                                clean=False,
                            ),
                            decorators=decorators_for(node),
                            dependencies=[],
                            exported=not node.name.startswith("_"),
                        )
                    )

                    visit_body(
                        node.body,
                        (*parent_names, node.name),
                    )

                elif isinstance(
                    node,
                    (ast.Assign, ast.AnnAssign),
                ) and not parent_names:
                    target_names: list[str] = []

                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                target_names.append(target.id)
                    elif isinstance(node.target, ast.Name):
                        target_names.append(node.target.id)

                    for target_name in target_names:
                        is_constant = (
                            target_name.upper() == target_name
                            and any(
                                character.isalpha()
                                for character in target_name
                            )
                        )

                        symbols.append(
                            CodeSymbol(
                                name=target_name,
                                qualified_name=target_name,
                                symbol_type=(
                                    "constant"
                                    if is_constant
                                    else "variable"
                                ),
                                location=SourceLocation(
                                    relative_path=relative_path,
                                    start_line=node.lineno,
                                    end_line=getattr(
                                        node,
                                        "end_lineno",
                                        node.lineno,
                                    ),
                                    start_column=node.col_offset + 1,
                                    end_column=(
                                        getattr(
                                            node,
                                            "end_col_offset",
                                            node.col_offset,
                                        )
                                        + 1
                                    ),
                                ),
                                signature=None,
                                docstring=None,
                                decorators=[],
                                dependencies=[],
                                exported=not target_name.startswith("_"),
                            )
                        )

        visit_body(syntax_tree.body)

        return symbols

    def extract_python_imports(
        self,
        relative_path: str,
        content: str,
    ) -> list[ImportReference]:
        """Extract Python import statements using AST parsing."""

        try:
            syntax_tree = ast.parse(
                content,
                filename=relative_path,
            )
        except SyntaxError:
            return []

        imports: list[ImportReference] = []

        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ImportReference(
                            source_path=relative_path,
                            module=alias.name,
                            imported_names=[],
                            alias=alias.asname,
                            line_number=node.lineno,
                            is_relative=False,
                            resolved_path=None,
                        )
                    )

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                relative_prefix = "." * node.level
                full_module = f"{relative_prefix}{module_name}"

                imports.append(
                    ImportReference(
                        source_path=relative_path,
                        module=full_module or relative_prefix,
                        imported_names=[
                            alias.name
                            for alias in node.names
                        ],
                        alias=None,
                        line_number=node.lineno,
                        is_relative=node.level > 0,
                        resolved_path=None,
                    )
                )

        return imports

    def extract_javascript_symbols(
        self,
        relative_path: str,
        content: str,
    ) -> list[CodeSymbol]:
        """Extract basic JavaScript and TypeScript symbols.

        This lightweight parser avoids introducing a Node parser dependency.
        It intentionally indexes top-level declarations and React component
        candidates rather than attempting a full JavaScript AST parse.
        """

        symbols: list[CodeSymbol] = []
        seen: set[tuple[str, int]] = set()

        exported_names = {
            match.group("name")
            for match in JS_EXPORT_PATTERN.finditer(content)
            if match.group("name")
        }

        for match in JS_DECLARATION_PATTERN.finditer(content):
            kind = match.group("kind")
            name = match.group("name")

            if not kind or not name:
                continue

            line_number = content.count(
                "\n",
                0,
                match.start(),
            ) + 1

            key = (name, line_number)

            if key in seen:
                continue

            seen.add(key)

            symbol_type_map = {
                "class": "class",
                "function": "function",
                "const": "constant",
                "let": "variable",
                "var": "variable",
                "interface": "interface",
                "type": "type",
                "enum": "enum",
            }

            symbols.append(
                CodeSymbol(
                    name=name,
                    qualified_name=name,
                    symbol_type=symbol_type_map.get(
                        kind,
                        "unknown",
                    ),
                    location=SourceLocation(
                        relative_path=relative_path,
                        start_line=line_number,
                        end_line=line_number,
                    ),
                    signature=match.group(0).strip(),
                    docstring=None,
                    decorators=[],
                    dependencies=[],
                    exported=name in exported_names,
                )
            )

        if relative_path.casefold().endswith(
            (".jsx", ".tsx")
        ):
            for match in REACT_COMPONENT_PATTERN.finditer(content):
                component_name = (
                    match.group("const_name")
                    or match.group("function_name")
                )

                if not component_name:
                    continue

                line_number = content.count(
                    "\n",
                    0,
                    match.start(),
                ) + 1

                key = (component_name, line_number)

                if key in seen:
                    continue

                seen.add(key)

                symbols.append(
                    CodeSymbol(
                        name=component_name,
                        qualified_name=component_name,
                        symbol_type="component",
                        location=SourceLocation(
                            relative_path=relative_path,
                            start_line=line_number,
                            end_line=line_number,
                        ),
                        signature=match.group(0).strip(),
                        docstring=None,
                        decorators=[],
                        dependencies=[],
                        exported=(
                            component_name in exported_names
                            or "export" in match.group(0)
                        ),
                    )
                )

        return symbols

    def extract_javascript_imports(
        self,
        relative_path: str,
        content: str,
    ) -> list[ImportReference]:
        """Extract JavaScript and TypeScript import references."""

        imports: list[ImportReference] = []

        for match in JS_IMPORT_PATTERN.finditer(content):
            module_name = (
                match.group("module")
                or match.group("require_module")
                or match.group("dynamic_module")
            )

            if not module_name:
                continue

            bindings = match.group("bindings") or ""
            imported_names = [
                value.strip()
                for value in re.split(r"[,{}\s]+", bindings)
                if value.strip()
                and value.strip() not in {"*", "as"}
            ]

            line_number = content.count(
                "\n",
                0,
                match.start(),
            ) + 1

            imports.append(
                ImportReference(
                    source_path=relative_path,
                    module=module_name,
                    imported_names=_deduplicate_preserve_order(
                        imported_names
                    ),
                    alias=None,
                    line_number=line_number,
                    is_relative=module_name.startswith("."),
                    resolved_path=None,
                )
            )

        return imports

    def extract_file_analysis(
        self,
        metadata: FileMetadata,
        path: Path,
    ) -> tuple[list[CodeSymbol], list[ImportReference]]:
        """Extract symbols and imports from a supported source file."""

        if metadata.is_binary or metadata.is_protected:
            return [], []

        if metadata.size_bytes > self.configuration.maximum_file_size_bytes:
            return [], []

        if not (
            self.configuration.extract_symbols
            or self.configuration.extract_imports
        ):
            return [], []

        try:
            file_content = self.read_text_file(
                path,
                maximum_bytes=self.configuration.maximum_file_size_bytes,
                allow_protected=False,
            )
        except (
            RepositoryAccessError,
            UnsupportedFileEncodingError,
            UnsafePathError,
            BlockedFileError,
        ) as exc:
            self._warnings.append(str(exc))
            return [], []

        symbols: list[CodeSymbol] = []
        imports: list[ImportReference] = []

        if metadata.file_type == FileType.PYTHON:
            if self.configuration.extract_symbols:
                symbols = self.extract_python_symbols(
                    metadata.relative_path,
                    file_content.content,
                )

            if self.configuration.extract_imports:
                imports = self.extract_python_imports(
                    metadata.relative_path,
                    file_content.content,
                )

        elif metadata.file_type in {
            FileType.JAVASCRIPT,
            FileType.TYPESCRIPT,
            FileType.JSX,
            FileType.TSX,
        }:
            if self.configuration.extract_symbols:
                symbols = self.extract_javascript_symbols(
                    metadata.relative_path,
                    file_content.content,
                )

            if self.configuration.extract_imports:
                imports = self.extract_javascript_imports(
                    metadata.relative_path,
                    file_content.content,
                )

        return symbols, imports
    def resolve_local_imports(
        self,
        imports: Sequence[ImportReference],
        available_files: Sequence[FileMetadata],
    ) -> list[ImportReference]:
        """Resolve local Python and JavaScript imports to repository files.

        Resolution is best-effort and never imports or executes repository
        code. Unresolved external dependencies retain ``resolved_path=None``.
        """

        available_paths = {
            metadata.relative_path.casefold(): metadata.relative_path
            for metadata in available_files
        }

        resolved_imports: list[ImportReference] = []

        for import_reference in imports:
            resolved_path: str | None = None
            source_path = Path(import_reference.source_path)
            source_directory = source_path.parent
            module_name = import_reference.module

            if import_reference.source_path.casefold().endswith(
                (".py", ".pyi")
            ):
                resolved_path = self._resolve_python_import_path(
                    source_directory=source_directory,
                    module_name=module_name,
                    available_paths=available_paths,
                )

            elif import_reference.source_path.casefold().endswith(
                (
                    ".js",
                    ".jsx",
                    ".mjs",
                    ".cjs",
                    ".ts",
                    ".tsx",
                    ".mts",
                    ".cts",
                )
            ):
                resolved_path = self._resolve_javascript_import_path(
                    source_directory=source_directory,
                    module_name=module_name,
                    available_paths=available_paths,
                )

            resolved_imports.append(
                import_reference.model_copy(
                    update={"resolved_path": resolved_path}
                )
            )

        return resolved_imports

    def _resolve_python_import_path(
        self,
        *,
        source_directory: Path,
        module_name: str,
        available_paths: dict[str, str],
    ) -> str | None:
        """Resolve a Python import to a repository-relative source file."""

        if not module_name:
            return None

        leading_dots = len(module_name) - len(
            module_name.lstrip(".")
        )
        clean_module = module_name.lstrip(".")

        if leading_dots > 0:
            base_directory = source_directory

            for _ in range(max(leading_dots - 1, 0)):
                base_directory = base_directory.parent
        else:
            base_directory = Path()

        module_parts = [
            part
            for part in clean_module.split(".")
            if part
        ]

        candidate_base = base_directory.joinpath(*module_parts)

        candidates = [
            candidate_base.with_suffix(".py"),
            candidate_base.with_suffix(".pyi"),
            candidate_base / "__init__.py",
            candidate_base / "__init__.pyi",
        ]

        for candidate in candidates:
            normalized = candidate.as_posix().lstrip("./")
            match = available_paths.get(normalized.casefold())

            if match is not None:
                return match

        return None

    def _resolve_javascript_import_path(
        self,
        *,
        source_directory: Path,
        module_name: str,
        available_paths: dict[str, str],
    ) -> str | None:
        """Resolve a relative JavaScript or TypeScript module import."""

        if not module_name.startswith("."):
            return None

        candidate_base = (
            source_directory / module_name
        )

        suffixes = (
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".mts",
            ".cts",
            ".mjs",
            ".cjs",
            ".json",
        )

        candidates: list[Path] = []

        if candidate_base.suffix:
            candidates.append(candidate_base)
        else:
            candidates.extend(
                candidate_base.with_suffix(suffix)
                for suffix in suffixes
            )

            candidates.extend(
                candidate_base / f"index{suffix}"
                for suffix in suffixes
            )

        for candidate in candidates:
            normalized = candidate.as_posix()

            while normalized.startswith("./"):
                normalized = normalized[2:]

            match = available_paths.get(normalized.casefold())

            if match is not None:
                return match

        return None

    def build_statistics(
        self,
        files: Sequence[FileMetadata],
        *,
        skipped_files: int = 0,
    ) -> RepositoryStatistics:
        """Build aggregate repository statistics."""

        file_type_counter: Counter[str] = Counter()
        file_role_counter: Counter[str] = Counter()
        extension_counter: Counter[str] = Counter()

        total_size_bytes = 0
        total_lines = 0
        protected_files = 0
        binary_files = 0
        indexed_files = 0

        for metadata in files:
            file_type_counter[metadata.file_type.value] += 1
            file_role_counter[metadata.role.value] += 1

            extension_key = metadata.extension or "[no extension]"
            extension_counter[extension_key] += 1

            total_size_bytes += metadata.size_bytes
            total_lines += metadata.line_count or 0

            if metadata.is_protected:
                protected_files += 1

            if metadata.is_binary:
                binary_files += 1

            if not metadata.is_binary and not metadata.is_protected:
                indexed_files += 1

        return RepositoryStatistics(
            total_files=len(files),
            indexed_files=indexed_files,
            skipped_files=max(skipped_files, 0),
            protected_files=protected_files,
            binary_files=binary_files,
            total_size_bytes=total_size_bytes,
            total_lines=total_lines,
            files_by_type=dict(
                sorted(file_type_counter.items())
            ),
            files_by_role=dict(
                sorted(file_role_counter.items())
            ),
            files_by_extension=dict(
                sorted(extension_counter.items())
            ),
        )

    def build_repository_tree(
        self,
        files: Sequence[FileMetadata],
    ) -> RepositoryTreeResponse:
        """Build a nested repository tree for the frontend."""

        root_name = self.repository_root.name or str(
            self.repository_root
        )

        root_node = RepositoryTreeNode(
            name=root_name,
            relative_path="",
            node_type="directory",
            children=[],
            metadata=None,
            expanded=True,
        )

        directory_nodes: dict[str, RepositoryTreeNode] = {
            "": root_node
        }

        for metadata in sorted(
            files,
            key=lambda item: item.relative_path.casefold(),
        ):
            relative_path = Path(metadata.relative_path)
            current_parent = root_node
            accumulated_parts: list[str] = []

            for directory_part in relative_path.parts[:-1]:
                accumulated_parts.append(directory_part)
                directory_key = Path(
                    *accumulated_parts
                ).as_posix()

                if directory_key not in directory_nodes:
                    directory_node = RepositoryTreeNode(
                        name=directory_part,
                        relative_path=directory_key,
                        node_type="directory",
                        children=[],
                        metadata=None,
                        expanded=False,
                    )

                    current_parent.children.append(
                        directory_node
                    )
                    directory_nodes[directory_key] = (
                        directory_node
                    )

                current_parent = directory_nodes[directory_key]

            file_node = RepositoryTreeNode(
                name=relative_path.name,
                relative_path=metadata.relative_path,
                node_type="file",
                children=[],
                metadata=metadata,
                expanded=False,
            )

            current_parent.children.append(file_node)

        self._sort_tree_nodes(root_node)

        total_nodes = 1 + sum(
            1 + len(Path(metadata.relative_path).parents) - 1
            for metadata in files
        )

        unique_directory_paths = {
            Path(metadata.relative_path).parent.as_posix()
            for metadata in files
            if Path(metadata.relative_path).parent.as_posix() != "."
        }

        total_nodes = (
            1
            + len(unique_directory_paths)
            + len(files)
        )

        return RepositoryTreeResponse(
            repository_root=str(self.repository_root),
            generated_at=utc_now(),
            root=root_node,
            total_nodes=total_nodes,
        )

    def _sort_tree_nodes(
        self,
        node: RepositoryTreeNode,
    ) -> None:
        """Sort a repository tree recursively.

        Directories are displayed before files. Names are compared
        case-insensitively for deterministic Windows behavior.
        """

        node.children.sort(
            key=lambda child: (
                0 if child.node_type == "directory" else 1,
                child.name.casefold(),
            )
        )

        for child in node.children:
            if child.node_type == "directory":
                self._sort_tree_nodes(child)

    def detect_repository_environment(
        self,
        files: Sequence[FileMetadata],
    ) -> dict[str, Any]:
        """Detect frameworks, package managers, tests, and commands."""

        available_paths = {
            metadata.relative_path.casefold()
            for metadata in files
        }

        available_names = {
            metadata.file_name.casefold()
            for metadata in files
        }

        backend_detected = False
        frontend_detected = False
        backend_framework: str | None = None
        frontend_framework: str | None = None
        package_managers: list[str] = []
        test_frameworks: list[str] = []
        build_commands: list[str] = []
        test_commands: list[str] = []

        if "requirements.txt" in available_names:
            package_managers.append("pip")

        if "pyproject.toml" in available_names:
            package_managers.append("pip/pyproject")

        if "poetry.lock" in available_names:
            package_managers.append("Poetry")

        if "pipfile" in available_names:
            package_managers.append("Pipenv")

        if "package-lock.json" in available_names:
            package_managers.append("npm")

        if "yarn.lock" in available_names:
            package_managers.append("Yarn")

        if "pnpm-lock.yaml" in available_names:
            package_managers.append("pnpm")

        python_files = [
            metadata
            for metadata in files
            if metadata.file_type == FileType.PYTHON
            and not metadata.is_protected
            and not metadata.is_binary
        ]

        javascript_files = [
            metadata
            for metadata in files
            if metadata.file_type
            in {
                FileType.JAVASCRIPT,
                FileType.TYPESCRIPT,
                FileType.JSX,
                FileType.TSX,
            }
            and not metadata.is_protected
            and not metadata.is_binary
        ]

        if python_files:
            backend_detected = True

        if javascript_files or "package.json" in available_names:
            frontend_detected = True

        backend_framework = self._detect_python_framework(
            python_files
        )
        frontend_framework = self._detect_frontend_framework(
            available_paths=available_paths,
            available_names=available_names,
            source_files=javascript_files,
        )

        if backend_framework is not None:
            backend_detected = True

        if frontend_framework is not None:
            frontend_detected = True

        if (
            "pytest.ini" in available_names
            or "conftest.py" in available_names
            or any(
                _matches_any_pattern(
                    metadata.file_name,
                    ("test_*.py", "*_test.py"),
                )
                for metadata in python_files
            )
        ):
            test_frameworks.append("pytest")
            test_commands.append("python -m pytest")

        package_json = self._load_package_json_safely()

        if package_json is not None:
            scripts = package_json.get("scripts", {})

            if isinstance(scripts, dict):
                if "test" in scripts:
                    test_commands.append("npm test")

                if "build" in scripts:
                    build_commands.append("npm run build")

                if "lint" in scripts:
                    build_commands.append("npm run lint")

                if "typecheck" in scripts:
                    build_commands.append(
                        "npm run typecheck"
                    )
                elif "type-check" in scripts:
                    build_commands.append(
                        "npm run type-check"
                    )

            dependencies: dict[str, Any] = {}

            for section_name in (
                "dependencies",
                "devDependencies",
            ):
                section = package_json.get(section_name, {})

                if isinstance(section, dict):
                    dependencies.update(section)

            dependency_names = {
                name.casefold()
                for name in dependencies
            }

            if "jest" in dependency_names:
                test_frameworks.append("Jest")

            if "vitest" in dependency_names:
                test_frameworks.append("Vitest")

            if (
                "@testing-library/react"
                in dependency_names
            ):
                test_frameworks.append(
                    "React Testing Library"
                )

        return {
            "backend_detected": backend_detected,
            "frontend_detected": frontend_detected,
            "backend_framework": backend_framework,
            "frontend_framework": frontend_framework,
            "package_managers": _deduplicate_preserve_order(
                package_managers
            ),
            "test_frameworks": _deduplicate_preserve_order(
                test_frameworks
            ),
            "build_commands": _deduplicate_preserve_order(
                build_commands
            ),
            "test_commands": _deduplicate_preserve_order(
                test_commands
            ),
        }

    def _detect_python_framework(
        self,
        files: Sequence[FileMetadata],
    ) -> str | None:
        """Detect common Python backend frameworks from source imports."""

        framework_patterns = (
            ("FastAPI", ("from fastapi", "import fastapi")),
            ("Django", ("from django", "import django")),
            ("Flask", ("from flask", "import flask")),
            (
                "Starlette",
                ("from starlette", "import starlette"),
            ),
            (
                "Sanic",
                ("from sanic", "import sanic"),
            ),
            (
                "Tornado",
                ("from tornado", "import tornado"),
            ),
        )

        maximum_files_to_inspect = 250
        inspected_files = 0

        for metadata in files:
            if inspected_files >= maximum_files_to_inspect:
                break

            if (
                metadata.size_bytes
                > self.configuration.maximum_file_size_bytes
            ):
                continue

            try:
                content = self.read_text_file(
                    metadata.relative_path,
                    maximum_bytes=(
                        self.configuration.maximum_file_size_bytes
                    ),
                ).content.casefold()
            except (
                RepositoryServiceError,
                UnsafePathError,
                BlockedFileError,
            ):
                continue

            inspected_files += 1

            for framework_name, patterns in framework_patterns:
                if any(
                    pattern.casefold() in content
                    for pattern in patterns
                ):
                    return framework_name

        return None

    def _detect_frontend_framework(
        self,
        *,
        available_paths: set[str],
        available_names: set[str],
        source_files: Sequence[FileMetadata],
    ) -> str | None:
        """Detect common JavaScript and TypeScript frontend frameworks."""

        package_json = self._load_package_json_safely()

        if package_json is not None:
            dependencies: dict[str, Any] = {}

            for section_name in (
                "dependencies",
                "devDependencies",
            ):
                section = package_json.get(section_name, {})

                if isinstance(section, dict):
                    dependencies.update(section)

            dependency_names = {
                name.casefold()
                for name in dependencies
            }

            if "next" in dependency_names:
                return "Next.js"

            if "react" in dependency_names:
                if "vite" in dependency_names:
                    return "React with Vite"

                return "React"

            if "vue" in dependency_names:
                if "nuxt" in dependency_names:
                    return "Nuxt"

                return "Vue"

            if "@angular/core" in dependency_names:
                return "Angular"

            if "svelte" in dependency_names:
                if "@sveltejs/kit" in dependency_names:
                    return "SvelteKit"

                return "Svelte"

        if (
            "vite.config.ts" in available_names
            or "vite.config.js" in available_names
        ):
            return "Vite"

        if "next.config.js" in available_names:
            return "Next.js"

        if any(
            path.endswith((".jsx", ".tsx"))
            for path in available_paths
        ):
            return "React-compatible frontend"

        maximum_files_to_inspect = 150
        inspected_files = 0

        for metadata in source_files:
            if inspected_files >= maximum_files_to_inspect:
                break

            if metadata.size_bytes > 500_000:
                continue

            try:
                content = self.read_text_file(
                    metadata.relative_path,
                    maximum_bytes=500_000,
                ).content.casefold()
            except (
                RepositoryServiceError,
                UnsafePathError,
                BlockedFileError,
            ):
                continue

            inspected_files += 1

            if (
                "from 'react'" in content
                or 'from "react"' in content
                or "react.createelement" in content
            ):
                return "React"

            if (
                "from 'vue'" in content
                or 'from "vue"' in content
            ):
                return "Vue"

        return None

    def _find_metadata_by_name(
        self,
        files: Sequence[FileMetadata],
        file_name: str,
    ) -> FileMetadata | None:
        """Find the shortest matching repository file by filename."""

        matches = [
            metadata
            for metadata in files
            if metadata.file_name.casefold()
            == file_name.casefold()
        ]

        if not matches:
            return None

        return min(
            matches,
            key=lambda metadata: (
                len(Path(metadata.relative_path).parts),
                metadata.relative_path.casefold(),
            ),
        )

    def _load_package_json_safely(
        self,
    ) -> dict[str, Any] | None:
        """Load the most relevant package.json without executing scripts."""

        candidates = [
            Path("frontend") / "package.json",
            Path("package.json"),
        ]

        discovered_candidates = sorted(
            (
                path
                for path in self.repository_root.rglob(
                    "package.json"
                )
                if "node_modules" not in {
                    part.casefold()
                    for part in path.parts
                }
            ),
            key=lambda path: (
                len(path.parts),
                str(path).casefold(),
            ),
        )

        for discovered in discovered_candidates:
            try:
                relative = discovered.relative_to(
                    self.repository_root
                )
            except ValueError:
                continue

            if relative not in candidates:
                candidates.append(relative)

        for candidate in candidates:
            try:
                file_content = self.read_text_file(
                    candidate,
                    maximum_bytes=2_000_000,
                )
            except (
                RepositoryServiceError,
                UnsafePathError,
                BlockedFileError,
            ):
                continue

            try:
                parsed = json.loads(file_content.content)
            except json.JSONDecodeError as exc:
                self._warnings.append(
                    f"Invalid package.json at "
                    f"{candidate.as_posix()}: {exc}"
                )
                continue

            if isinstance(parsed, dict):
                return parsed

        return None

    def scan_repository(
        self,
    ) -> tuple[
        list[FileMetadata],
        list[CodeSymbol],
        list[ImportReference],
        int,
    ]:
        """Scan repository files and extract metadata and code analysis."""

        files: list[FileMetadata] = []
        symbols: list[CodeSymbol] = []
        imports: list[ImportReference] = []
        skipped_files = 0

        for path in self.iter_repository_files():
            try:
                metadata = self.build_file_metadata(path)
                files.append(metadata)

                file_symbols, file_imports = (
                    self.extract_file_analysis(
                        metadata,
                        path,
                    )
                )

                symbols.extend(file_symbols)
                imports.extend(file_imports)

            except (
                RepositoryAccessError,
                OSError,
                PermissionError,
            ) as exc:
                skipped_files += 1

                try:
                    relative_text = (
                        self._relative_path_string(path)
                    )
                except RepositoryServiceError:
                    relative_text = str(path)

                self._errors.append(
                    f"Failed to index {relative_text}: {exc}"
                )

        files.sort(
            key=lambda metadata: (
                metadata.relative_path.casefold()
            )
        )

        symbols.sort(
            key=lambda symbol: (
                symbol.location.relative_path.casefold(),
                symbol.location.start_line,
                symbol.name.casefold(),
            )
        )

        resolved_imports = self.resolve_local_imports(
            imports,
            files,
        )

        resolved_imports.sort(
            key=lambda import_reference: (
                import_reference.source_path.casefold(),
                import_reference.line_number,
                import_reference.module.casefold(),
            )
        )

        return (
            files,
            symbols,
            resolved_imports,
            skipped_files,
        )

    def analyze_repository(
        self,
        *,
        analysis_id: UUID | None = None,
    ) -> CodebaseAnalysis:
        """Perform a complete repository analysis."""

        self.clear_messages()

        started_at = utc_now()
        monotonic_start = time.monotonic()

        files, symbols, imports, skipped_files = (
            self.scan_repository()
        )

        statistics = self.build_statistics(
            files,
            skipped_files=skipped_files,
        )

        environment = self.detect_repository_environment(
            files
        )

        completed_at = utc_now()
        duration_seconds = max(
            time.monotonic() - monotonic_start,
            0.0,
        )

        repository_name = (
            self.repository_root.name
            or self.repository_root.anchor
            or "repository"
        )

        return CodebaseAnalysis(
            analysis_id=analysis_id or uuid4(),
            repository_root=str(self.repository_root),
            repository_name=repository_name,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            statistics=statistics,
            files=files,
            symbols=symbols,
            imports=imports,
            backend_detected=environment[
                "backend_detected"
            ],
            frontend_detected=environment[
                "frontend_detected"
            ],
            backend_framework=environment[
                "backend_framework"
            ],
            frontend_framework=environment[
                "frontend_framework"
            ],
            package_managers=environment[
                "package_managers"
            ],
            test_frameworks=environment[
                "test_frameworks"
            ],
            build_commands=environment[
                "build_commands"
            ],
            test_commands=environment[
                "test_commands"
            ],
            warnings=self.warnings,
            errors=self.errors,
        )

    def create_repository_map(
        self,
        analysis: CodebaseAnalysis,
    ) -> dict[str, Any]:
        """Create the JSON-serializable repository map/index."""

        tree = self.build_repository_tree(
            analysis.files
        )

        file_entries = [
            {
                "path": metadata.relative_path,
                "name": metadata.file_name,
                "extension": metadata.extension,
                "type": metadata.file_type.value,
                "role": metadata.role.value,
                "language": metadata.language,
                "size_bytes": metadata.size_bytes,
                "line_count": metadata.line_count,
                "sha256": metadata.sha256,
                "encoding": metadata.encoding,
                "binary": metadata.is_binary,
                "generated": metadata.is_generated,
                "protected": metadata.is_protected,
                "protection_reason": (
                    metadata.protection_reason
                ),
                "modified_at": (
                    metadata.modified_at.isoformat()
                    if metadata.modified_at is not None
                    else None
                ),
            }
            for metadata in analysis.files
        ]

        symbol_entries = [
            symbol.model_dump(
                mode="json",
                exclude_none=True,
            )
            for symbol in analysis.symbols
        ]

        import_entries = [
            import_reference.model_dump(
                mode="json",
                exclude_none=True,
            )
            for import_reference in analysis.imports
        ]

        return {
            "schema_version": 1,
            "generator": "LUMINA Code Builder",
            "analysis_id": str(analysis.analysis_id),
            "repository": {
                "root": analysis.repository_root,
                "name": analysis.repository_name,
            },
            "generated_at": utc_now().isoformat(),
            "analysis": {
                "started_at": (
                    analysis.started_at.isoformat()
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "duration_seconds": (
                    analysis.duration_seconds
                ),
            },
            "environment": {
                "backend_detected": (
                    analysis.backend_detected
                ),
                "frontend_detected": (
                    analysis.frontend_detected
                ),
                "backend_framework": (
                    analysis.backend_framework
                ),
                "frontend_framework": (
                    analysis.frontend_framework
                ),
                "package_managers": (
                    analysis.package_managers
                ),
                "test_frameworks": (
                    analysis.test_frameworks
                ),
                "build_commands": (
                    analysis.build_commands
                ),
                "test_commands": (
                    analysis.test_commands
                ),
            },
            "statistics": analysis.statistics.model_dump(
                mode="json"
            ),
            "files": file_entries,
            "symbols": symbol_entries,
            "imports": import_entries,
            "tree": tree.model_dump(
                mode="json",
                exclude_none=True,
            ),
            "warnings": analysis.warnings,
            "errors": analysis.errors,
        }

    def save_repository_index(
        self,
        analysis: CodebaseAnalysis,
    ) -> Path:
        """Persist the repository map atomically as UTF-8 JSON.

        The temporary file is created in the same directory as the final
        index so ``os.replace`` remains atomic on Windows.
        """

        repository_map = self.create_repository_map(
            analysis
        )

        try:
            self.index_directory.mkdir(
                parents=True,
                exist_ok=True,
            )
        except (OSError, PermissionError) as exc:
            raise RepositoryIndexError(
                "Failed to create repository index directory: "
                f"{self.index_directory}"
            ) from exc

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                delete=False,
                dir=self.index_directory,
                prefix=f".{self.index_file_name}.",
                suffix=".tmp",
            ) as temporary_file:
                json.dump(
                    repository_map,
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=False,
                )

                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

                temporary_path = Path(
                    temporary_file.name
                )

            os.replace(
                temporary_path,
                self.index_path,
            )

        except (
            OSError,
            PermissionError,
            TypeError,
            ValueError,
        ) as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(
                        missing_ok=True
                    )
                except OSError:
                    pass

            raise RepositoryIndexError(
                f"Failed to save repository index: {exc}"
            ) from exc

        return self.index_path

    def load_repository_index(
        self,
    ) -> dict[str, Any] | None:
        """Load and validate the existing UTF-8 JSON repository index."""

        if not self.index_path.exists():
            return None

        if not self.index_path.is_file():
            raise RepositoryIndexError(
                "Repository index path is not a file: "
                f"{self.index_path}"
            )

        try:
            with self.index_path.open(
                "r",
                encoding="utf-8",
                newline=None,
            ) as index_file:
                data = json.load(index_file)
        except (
            OSError,
            PermissionError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RepositoryIndexError(
                f"Failed to load repository index: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise RepositoryIndexError(
                "Repository index root must be a JSON object."
            )

        schema_version = data.get("schema_version")

        if schema_version != 1:
            raise RepositoryIndexError(
                "Unsupported repository index schema version: "
                f"{schema_version}"
            )

        repository_data = data.get("repository")

        if not isinstance(repository_data, dict):
            raise RepositoryIndexError(
                "Repository index does not contain repository metadata."
            )

        indexed_root = repository_data.get("root")

        if not isinstance(indexed_root, str):
            raise RepositoryIndexError(
                "Repository index root is invalid."
            )

        try:
            resolved_indexed_root = Path(
                indexed_root
            ).resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RepositoryIndexError(
                "Repository index contains an invalid root path."
            ) from exc

        if (
            os.path.normcase(str(resolved_indexed_root))
            != os.path.normcase(str(self.repository_root))
        ):
            raise RepositoryIndexError(
                "Repository index belongs to a different repository."
            )

        return data

    def index_is_current(
        self,
        index_data: dict[str, Any] | None = None,
    ) -> bool:
        """Return whether the saved index still matches repository files.

        The comparison checks file paths, sizes, modification timestamps,
        and hashes when available.
        """

        if index_data is None:
            try:
                index_data = self.load_repository_index()
            except RepositoryIndexError:
                return False

        if index_data is None:
            return False

        indexed_files = index_data.get("files")

        if not isinstance(indexed_files, list):
            return False

        indexed_by_path: dict[str, dict[str, Any]] = {}

        for entry in indexed_files:
            if not isinstance(entry, dict):
                return False

            path_value = entry.get("path")

            if not isinstance(path_value, str):
                return False

            indexed_by_path[path_value.casefold()] = entry

        current_paths: set[str] = set()

        for file_path in self.iter_repository_files():
            relative_path = self._relative_path_string(
                file_path
            )
            comparison_key = relative_path.casefold()
            current_paths.add(comparison_key)

            indexed_entry = indexed_by_path.get(
                comparison_key
            )

            if indexed_entry is None:
                return False

            stat_result = _safe_stat(file_path)

            if stat_result is None:
                return False

            indexed_size = indexed_entry.get(
                "size_bytes"
            )

            if indexed_size != stat_result.st_size:
                return False

            indexed_hash = indexed_entry.get("sha256")

            if (
                self.configuration.calculate_hashes
                and isinstance(indexed_hash, str)
            ):
                try:
                    current_hash = self.calculate_sha256(
                        file_path
                    )
                except RepositoryAccessError:
                    return False

                if current_hash != indexed_hash:
                    return False

        return current_paths == set(indexed_by_path)

    def analyze_and_save(
        self,
        *,
        force_reindex: bool = False,
    ) -> tuple[CodebaseAnalysis, Path]:
        """Analyze the repository and persist a fresh JSON index.

        ``force_reindex`` is accepted for API symmetry. This method always
        performs a fresh analysis before saving.
        """

        if force_reindex:
            self.clear_messages()

        analysis = self.analyze_repository()
        index_path = self.save_repository_index(
            analysis
        )

        return analysis, index_path

    def get_or_create_index(
        self,
        *,
        force_reindex: bool = False,
    ) -> dict[str, Any]:
        """Return a current repository index, rebuilding when necessary."""

        if not force_reindex:
            try:
                existing_index = (
                    self.load_repository_index()
                )
            except RepositoryIndexError as exc:
                self._warnings.append(str(exc))
                existing_index = None

            if (
                existing_index is not None
                and self.index_is_current(
                    existing_index
                )
            ):
                return existing_index

        analysis = self.analyze_repository()
        self.save_repository_index(analysis)

        return self.create_repository_map(
            analysis
        )

    def get_repository_tree(
        self,
        *,
        force_reindex: bool = False,
    ) -> RepositoryTreeResponse:
        """Return a freshly built repository tree."""

        if force_reindex:
            analysis = self.analyze_repository()
            self.save_repository_index(analysis)
            return self.build_repository_tree(
                analysis.files
            )

        try:
            index_data = self.load_repository_index()
        except RepositoryIndexError:
            index_data = None

        if (
            index_data is None
            or not self.index_is_current(index_data)
        ):
            analysis = self.analyze_repository()
            self.save_repository_index(analysis)
            return self.build_repository_tree(
                analysis.files
            )

        analysis = self.analyze_repository()

        return self.build_repository_tree(
            analysis.files
        )

    def find_files(
        self,
        query: str,
        *,
        maximum_results: int = 100,
    ) -> list[FileMetadata]:
        """Search indexed repository files by path, name, type, or role."""

        normalized_query = query.strip().casefold()

        if not normalized_query:
            return []

        maximum_results = max(
            1,
            min(maximum_results, 1_000),
        )

        files, _, _, _ = self.scan_repository()

        scored_matches: list[
            tuple[int, str, FileMetadata]
        ] = []

        for metadata in files:
            path_value = metadata.relative_path.casefold()
            name_value = metadata.file_name.casefold()
            type_value = metadata.file_type.value.casefold()
            role_value = metadata.role.value.casefold()

            score: int | None = None

            if name_value == normalized_query:
                score = 0
            elif path_value == normalized_query:
                score = 1
            elif name_value.startswith(normalized_query):
                score = 2
            elif normalized_query in name_value:
                score = 3
            elif normalized_query in path_value:
                score = 4
            elif normalized_query == type_value:
                score = 5
            elif normalized_query == role_value:
                score = 6

            if score is not None:
                scored_matches.append(
                    (
                        score,
                        metadata.relative_path.casefold(),
                        metadata,
                    )
                )

        scored_matches.sort(
            key=lambda item: (item[0], item[1])
        )

        return [
            item[2]
            for item in scored_matches[
                :maximum_results
            ]
        ]

    def get_file_metadata(
        self,
        relative_path: str | Path,
    ) -> FileMetadata:
        """Return metadata for one safely resolved repository file."""

        resolved_path = validate_safe_path(
            repository_root=self.repository_root,
            requested_path=relative_path,
            allow_absolute=False,
            require_exists=True,
            allow_repository_root=False,
            check_blocked=False,
        )

        if not resolved_path.is_file():
            raise RepositoryAccessError(
                f"Requested path is not a file: {resolved_path}"
            )

        return self.build_file_metadata(
            resolved_path
        )


def analyze_repository(
    configuration: RepositoryConfiguration,
    *,
    save_index: bool = True,
) -> CodebaseAnalysis:
    """Convenience function for complete repository analysis."""

    service = RepositoryService(configuration)
    analysis = service.analyze_repository()

    if save_index:
        service.save_repository_index(analysis)

    return analysis


def create_repository_index(
    request: CodebaseAnalysisRequest,
) -> tuple[CodebaseAnalysis, Path]:
    """Analyze a repository request and save its JSON file map."""

    service = RepositoryService.from_request(request)

    return service.analyze_and_save(
        force_reindex=request.force_reindex
    )


def load_repository_index(
    configuration: RepositoryConfiguration,
) -> dict[str, Any] | None:
    """Convenience function for loading an existing repository index."""

    service = RepositoryService(configuration)

    return service.load_repository_index()


__all__ = [
    "DEFAULT_INDEX_DIRECTORY",
    "DEFAULT_INDEX_FILE_NAME",
    "RepositoryAccessError",
    "RepositoryIndexError",
    "RepositoryNotFoundError",
    "RepositoryService",
    "RepositoryServiceError",
    "UnsupportedFileEncodingError",
    "analyze_repository",
    "create_repository_index",
    "load_repository_index",
]
