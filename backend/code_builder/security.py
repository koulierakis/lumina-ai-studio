"""Security utilities for the LUMINA Code Builder.

This module protects the LUMINA repository from unsafe filesystem access
and dangerous command execution.

Security responsibilities include:

- Preventing path traversal outside the configured repository root.
- Resolving Windows and POSIX paths safely with pathlib.Path.resolve().
- Detecting symlink-based repository escapes.
- Blocking access to secrets, credentials, operating-system files,
  generated dependencies, backups, and other sensitive resources.
- Validating repository-relative file paths.
- Providing structured security decisions and explicit exceptions.
- Sanitizing terminal commands before they are passed to a subprocess.

The command-sanitization implementation continues in the second half
of this file.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Iterable, Sequence


class SecurityError(RuntimeError):
    """Base exception for Code Builder security violations."""


class UnsafePathError(SecurityError):
    """Raised when a path is unsafe or escapes the repository root."""


class BlockedFileError(SecurityError):
    """Raised when access to a protected file or directory is denied."""


class UnsafeCommandError(SecurityError):
    """Raised when a terminal command fails security validation."""


class BlockReason(str, Enum):
    """Reason why a file or path was blocked."""

    ALLOWED = "allowed"
    EMPTY_PATH = "empty_path"
    NULL_BYTE = "null_byte"
    ABSOLUTE_PATH = "absolute_path"
    PATH_TRAVERSAL = "path_traversal"
    OUTSIDE_REPOSITORY = "outside_repository"
    SYMLINK_ESCAPE = "symlink_escape"
    SENSITIVE_FILE = "sensitive_file"
    SENSITIVE_DIRECTORY = "sensitive_directory"
    SYSTEM_PATH = "system_path"
    CREDENTIAL_FILE = "credential_file"
    PRIVATE_KEY = "private_key"
    CERTIFICATE = "certificate"
    ENVIRONMENT_FILE = "environment_file"
    BACKUP_DIRECTORY = "backup_directory"
    DEPENDENCY_DIRECTORY = "dependency_directory"
    VERSION_CONTROL_DIRECTORY = "version_control_directory"
    BUILD_ARTIFACT = "build_artifact"
    BINARY_FILE = "binary_file"
    DEVICE_PATH = "device_path"
    RESERVED_WINDOWS_NAME = "reserved_windows_name"
    INVALID_PATH = "invalid_path"


@dataclass(frozen=True, slots=True)
class PathSecurityDecision:
    """Structured result of a path-security evaluation."""

    allowed: bool
    reason: BlockReason
    message: str
    requested_path: str
    resolved_path: Path | None
    repository_root: Path | None

    def raise_forbidden(self) -> None:
        """Raise the appropriate exception when the decision is denied."""

        if self.allowed:
            return

        if self.reason in {
            BlockReason.SENSITIVE_FILE,
            BlockReason.SENSITIVE_DIRECTORY,
            BlockReason.CREDENTIAL_FILE,
            BlockReason.PRIVATE_KEY,
            BlockReason.CERTIFICATE,
            BlockReason.ENVIRONMENT_FILE,
            BlockReason.BACKUP_DIRECTORY,
            BlockReason.DEPENDENCY_DIRECTORY,
            BlockReason.VERSION_CONTROL_DIRECTORY,
            BlockReason.BUILD_ARTIFACT,
            BlockReason.BINARY_FILE,
            BlockReason.SYSTEM_PATH,
        }:
            raise BlockedFileError(self.message)

        raise UnsafePathError(self.message)


_WINDOWS_RESERVED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CLOCK$",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)

_BLOCKED_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        ".idea",
        ".vscode",
        ".vs",
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".config",
        ".docker",
        ".kube",
        ".npm",
        ".yarn",
        ".pnpm-store",
        ".lumina",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".coverage",
        "node_modules",
        "bower_components",
        "vendor",
        "venv",
        ".venv",
        "env",
        ".env",
        "site-packages",
        "dist",
        "build",
        "out",
        "target",
        "coverage",
        "htmlcov",
        ".next",
        ".nuxt",
        ".parcel-cache",
        ".cache",
        "backups",
        "backup",
        ".backups",
        "secrets",
        "credentials",
        "certificates",
        "private",
    }
)

_VERSION_CONTROL_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
    }
)

_DEPENDENCY_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        "node_modules",
        "bower_components",
        "vendor",
        "venv",
        ".venv",
        "env",
        "site-packages",
        ".pnpm-store",
    }
)

_BACKUP_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".lumina",
        "backups",
        "backup",
        ".backups",
    }
)

_BUILD_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        "dist",
        "build",
        "out",
        "target",
        "coverage",
        "htmlcov",
        ".next",
        ".nuxt",
        ".parcel-cache",
    }
)

_BLOCKED_EXACT_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
        ".env.staging",
        ".env.example.local",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "authorized_keys",
        "known_hosts",
        "credentials",
        "credentials.json",
        "service-account.json",
        "service_account.json",
        "client_secret.json",
        "client_secrets.json",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "secrets.toml",
        "token.json",
        "tokens.json",
        "passwd",
        "shadow",
        "group",
        "sudoers",
        "sam",
        "system",
        "security",
        "ntuser.dat",
        "boot.ini",
        "pagefile.sys",
        "hiberfil.sys",
        "swapfile.sys",
    }
)

_BLOCKED_FILE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".pem",
        ".key",
        ".pkey",
        ".ppk",
        ".pkcs8",
        ".p12",
        ".pfx",
        ".jks",
        ".keystore",
        ".der",
        ".crt",
        ".cer",
        ".csr",
        ".asc",
        ".gpg",
        ".kdbx",
        ".sqlite-shm",
        ".sqlite-wal",
        ".dll",
        ".sys",
        ".drv",
        ".exe",
        ".com",
        ".scr",
        ".msi",
        ".msp",
        ".cab",
        ".dmp",
        ".core",
        ".pyc",
        ".pyo",
        ".pyd",
        ".class",
        ".o",
        ".obj",
        ".so",
        ".dylib",
        ".a",
        ".lib",
    }
)

_CREDENTIAL_NAME_FRAGMENTS: Final[tuple[str, ...]] = (
    "credential",
    "credentials",
    "client_secret",
    "client-secret",
    "service_account",
    "service-account",
    "private_key",
    "private-key",
    "access_token",
    "access-token",
    "refresh_token",
    "refresh-token",
    "api_key",
    "api-key",
    "apikey",
    "auth_token",
    "auth-token",
    "secret_key",
    "secret-key",
    "wallet_seed",
    "wallet-seed",
    "mnemonic",
)

_SYSTEM_PATH_PREFIXES_WINDOWS: Final[tuple[str, ...]] = (
    "c:/windows",
    "c:/program files",
    "c:/program files (x86)",
    "c:/programdata",
    "c:/system volume information",
    "c:/$recycle.bin",
)

_SYSTEM_PATH_PREFIXES_POSIX: Final[tuple[str, ...]] = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib32",
    "/lib64",
    "/proc",
    "/root",
    "/run",
    "/sbin",
    "/sys",
    "/usr",
    "/var",
)

_ENV_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\.env(?:\..+)?$",
    flags=re.IGNORECASE,
)

_DRIVE_RELATIVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z]:[^\\/]",
)

_WINDOWS_DEVICE_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:\\\\[.?]\\|//[.?]/)",
    flags=re.IGNORECASE,
)


def _normalize_for_comparison(path: Path) -> str:
    """Return a normalized path string suitable for secure comparison."""

    normalized = os.path.normcase(str(path.resolve(strict=False)))
    return normalized.replace("\\", "/")


def _is_relative_to(candidate: Path, parent: Path) -> bool:
    """Return whether candidate is located inside parent."""

    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _contains_null_byte(value: str) -> bool:
    """Return whether a string contains a null byte."""

    return "\x00" in value


def _looks_like_windows_device_path(value: str) -> bool:
    """Detect Windows device and extended namespace paths."""

    normalized = value.strip().replace("\\", "/")
    return bool(_WINDOWS_DEVICE_PATH_PATTERN.match(normalized))


def _has_windows_reserved_component(path: Path) -> bool:
    """Detect Windows reserved device names in any path component."""

    for part in path.parts:
        cleaned = part.rstrip(" .")
        stem = cleaned.split(".", maxsplit=1)[0].upper()

        if stem in _WINDOWS_RESERVED_NAMES:
            return True

    return False


def _is_system_path(path: Path) -> bool:
    """Return whether a resolved path points to an OS-controlled location."""

    normalized = _normalize_for_comparison(path)

    if os.name == "nt":
        return any(
            normalized == prefix or normalized.startswith(f"{prefix}/")
            for prefix in _SYSTEM_PATH_PREFIXES_WINDOWS
        )

    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _SYSTEM_PATH_PREFIXES_POSIX
    )


def _classify_blocked_directory(parts: Iterable[str]) -> BlockReason | None:
    """Classify a blocked directory found in a path."""

    lowered = {part.casefold() for part in parts}

    if lowered.intersection(
        name.casefold() for name in _VERSION_CONTROL_DIRECTORIES
    ):
        return BlockReason.VERSION_CONTROL_DIRECTORY

    if lowered.intersection(
        name.casefold() for name in _DEPENDENCY_DIRECTORIES
    ):
        return BlockReason.DEPENDENCY_DIRECTORY

    if lowered.intersection(
        name.casefold() for name in _BACKUP_DIRECTORIES
    ):
        return BlockReason.BACKUP_DIRECTORY

    if lowered.intersection(
        name.casefold() for name in _BUILD_DIRECTORIES
    ):
        return BlockReason.BUILD_ARTIFACT

    if lowered.intersection(
        name.casefold() for name in _BLOCKED_DIRECTORY_NAMES
    ):
        return BlockReason.SENSITIVE_DIRECTORY

    return None


def _classify_blocked_file(path: Path) -> BlockReason | None:
    """Classify a file that must not be modified by the Code Builder."""

    file_name = path.name.casefold()
    suffix = path.suffix.casefold()

    if _ENV_FILE_PATTERN.fullmatch(path.name):
        return BlockReason.ENVIRONMENT_FILE

    if file_name in {
        name.casefold() for name in _BLOCKED_EXACT_FILE_NAMES
    }:
        if file_name in {
            "id_rsa",
            "id_dsa",
            "id_ecdsa",
            "id_ed25519",
        }:
            return BlockReason.PRIVATE_KEY

        return BlockReason.SENSITIVE_FILE

    if suffix in _BLOCKED_FILE_SUFFIXES:
        if suffix in {
            ".pem",
            ".key",
            ".pkey",
            ".ppk",
            ".pkcs8",
        }:
            return BlockReason.PRIVATE_KEY

        if suffix in {
            ".p12",
            ".pfx",
            ".jks",
            ".keystore",
            ".der",
            ".crt",
            ".cer",
            ".csr",
        }:
            return BlockReason.CERTIFICATE

        return BlockReason.BINARY_FILE

    if any(fragment in file_name for fragment in _CREDENTIAL_NAME_FRAGMENTS):
        return BlockReason.CREDENTIAL_FILE

    return None


def _resolve_repository_root(repository_root: str | Path) -> Path:
    """Resolve and validate the repository root."""

    raw_root = str(repository_root).strip()

    if not raw_root:
        raise UnsafePathError("The repository root cannot be empty.")

    if _contains_null_byte(raw_root):
        raise UnsafePathError(
            "The repository root contains an invalid null byte."
        )

    if _looks_like_windows_device_path(raw_root):
        raise UnsafePathError(
            "Windows device namespace paths are not permitted."
        )

    root = Path(raw_root).expanduser().resolve(strict=False)

    if _has_windows_reserved_component(root):
        raise UnsafePathError(
            f"The repository root contains a reserved Windows name: {root}"
        )

    if _is_system_path(root):
        raise UnsafePathError(
            f"The repository root cannot be an operating-system path: {root}"
        )

    return root


def _resolve_candidate_path(
    repository_root: Path,
    requested_path: str | Path,
    *,
    allow_absolute: bool,
) -> Path:
    """Resolve a requested path against the repository root."""

    raw_path = str(requested_path).strip()

    if not raw_path:
        raise UnsafePathError("The requested path cannot be empty.")

    if _contains_null_byte(raw_path):
        raise UnsafePathError(
            "The requested path contains an invalid null byte."
        )

    if _looks_like_windows_device_path(raw_path):
        raise UnsafePathError(
            "Windows device namespace paths are not permitted."
        )

    if _DRIVE_RELATIVE_PATTERN.match(raw_path):
        raise UnsafePathError(
            "Drive-relative Windows paths are not permitted."
        )

    candidate_input = Path(raw_path).expanduser()

    if candidate_input.is_absolute():
        if not allow_absolute:
            raise UnsafePathError(
                "Absolute paths are not permitted for this operation."
            )

        candidate = candidate_input.resolve(strict=False)
    else:
        candidate = (repository_root / candidate_input).resolve(strict=False)

    if _has_windows_reserved_component(candidate):
        raise UnsafePathError(
            f"The requested path contains a reserved Windows name: "
            f"{requested_path}"
        )

    return candidate


def evaluate_safe_path(
    repository_root: str | Path,
    requested_path: str | Path,
    *,
    allow_absolute: bool = False,
    require_exists: bool = False,
    allow_repository_root: bool = False,
    check_blocked: bool = True,
) -> PathSecurityDecision:
    """Evaluate whether a path is safe for repository access.

    The requested path is resolved with ``Path.resolve(strict=False)``.
    The resulting path must remain inside the resolved repository root.

    Args:
        repository_root:
            Absolute or relative path to the LUMINA repository root.
        requested_path:
            Repository-relative path, or an absolute path when
            ``allow_absolute`` is enabled.
        allow_absolute:
            Whether an absolute requested path may be accepted.
        require_exists:
            Whether the resolved target must already exist.
        allow_repository_root:
            Whether the repository root itself is a permitted target.
        check_blocked:
            Whether sensitive-file and sensitive-directory policies apply.

    Returns:
        A structured security decision. This function does not raise for a
        normal denial, but invalid repository-root configuration may raise.
    """

    requested_text = str(requested_path)
    root: Path | None = None
    candidate: Path | None = None

    try:
        root = _resolve_repository_root(repository_root)

        if not requested_text.strip():
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.EMPTY_PATH,
                message="The requested path cannot be empty.",
                requested_path=requested_text,
                resolved_path=None,
                repository_root=root,
            )

        if _contains_null_byte(requested_text):
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.NULL_BYTE,
                message="The requested path contains a null byte.",
                requested_path=requested_text,
                resolved_path=None,
                repository_root=root,
            )

        if _looks_like_windows_device_path(requested_text):
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.DEVICE_PATH,
                message="Windows device namespace paths are forbidden.",
                requested_path=requested_text,
                resolved_path=None,
                repository_root=root,
            )

        raw_candidate = Path(requested_text).expanduser()

        if raw_candidate.is_absolute() and not allow_absolute:
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.ABSOLUTE_PATH,
                message=(
                    "Absolute paths are forbidden. Use a path relative "
                    "to the LUMINA repository."
                ),
                requested_path=requested_text,
                resolved_path=None,
                repository_root=root,
            )

        normalized_parts = Path(
            requested_text.replace("\\", "/")
        ).parts

        if ".." in normalized_parts:
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.PATH_TRAVERSAL,
                message=(
                    "Parent-directory traversal components are forbidden."
                ),
                requested_path=requested_text,
                resolved_path=None,
                repository_root=root,
            )

        candidate = _resolve_candidate_path(
            root,
            requested_path,
            allow_absolute=allow_absolute,
        )

        if candidate == root and not allow_repository_root:
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.INVALID_PATH,
                message=(
                    "The repository root itself is not a permitted "
                    "file-operation target."
                ),
                requested_path=requested_text,
                resolved_path=candidate,
                repository_root=root,
            )

        if not _is_relative_to(candidate, root):
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.OUTSIDE_REPOSITORY,
                message=(
                    f"The resolved path escapes the LUMINA repository: "
                    f"{candidate}"
                ),
                requested_path=requested_text,
                resolved_path=candidate,
                repository_root=root,
            )

        if _is_system_path(candidate):
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.SYSTEM_PATH,
                message=(
                    f"Operating-system paths cannot be accessed: "
                    f"{candidate}"
                ),
                requested_path=requested_text,
                resolved_path=candidate,
                repository_root=root,
            )

        if require_exists and not candidate.exists():
            return PathSecurityDecision(
                allowed=False,
                reason=BlockReason.INVALID_PATH,
                message=f"The requested path does not exist: {candidate}",
                requested_path=requested_text,
                resolved_path=candidate,
                repository_root=root,
            )

        if check_blocked:
            relative_candidate = candidate.relative_to(root)

            directory_reason = _classify_blocked_directory(
                relative_candidate.parts[:-1]
            )

            if directory_reason is not None:
                return PathSecurityDecision(
                    allowed=False,
                    reason=directory_reason,
                    message=(
                        "The requested path is located inside a protected "
                        f"directory: {relative_candidate.as_posix()}"
                    ),
                    requested_path=requested_text,
                    resolved_path=candidate,
                    repository_root=root,
                )

            file_reason = _classify_blocked_file(relative_candidate)

            if file_reason is not None:
                return PathSecurityDecision(
                    allowed=False,
                    reason=file_reason,
                    message=(
                        "The requested file is protected and cannot be "
                        f"modified: {relative_candidate.as_posix()}"
                    ),
                    requested_path=requested_text,
                    resolved_path=candidate,
                    repository_root=root,
                )

        return PathSecurityDecision(
            allowed=True,
            reason=BlockReason.ALLOWED,
            message="The requested path is safe.",
            requested_path=requested_text,
            resolved_path=candidate,
            repository_root=root,
        )

    except (OSError, RuntimeError, ValueError) as exc:
        return PathSecurityDecision(
            allowed=False,
            reason=BlockReason.INVALID_PATH,
            message=f"Path validation failed: {exc}",
            requested_path=requested_text,
            resolved_path=candidate,
            repository_root=root,
        )


def validate_safe_path(
    repository_root: str | Path,
    requested_path: str | Path,
    *,
    allow_absolute: bool = False,
    require_exists: bool = False,
    allow_repository_root: bool = False,
    check_blocked: bool = True,
) -> Path:
    """Validate and return a securely resolved repository path.

    This is the primary filesystem-security function for the Code Builder.
    It raises an explicit security exception when the path is denied.

    Returns:
        The fully resolved safe path.

    Raises:
        UnsafePathError:
            If the path is invalid, traverses outside the repository,
            targets the repository root unexpectedly, or uses an unsafe
            Windows path form.
        BlockedFileError:
            If the path targets a protected file or directory.
    """

    decision = evaluate_safe_path(
        repository_root=repository_root,
        requested_path=requested_path,
        allow_absolute=allow_absolute,
        require_exists=require_exists,
        allow_repository_root=allow_repository_root,
        check_blocked=check_blocked,
    )

    decision.raise_forbidden()

    if decision.resolved_path is None:
        raise UnsafePathError(
            "Path validation succeeded without producing a resolved path."
        )

    return decision.resolved_path


def is_file_blocked(
    repository_root: str | Path,
    requested_path: str | Path,
    *,
    allow_absolute: bool = False,
) -> bool:
    """Return whether a file is blocked by the security policy.

    Unsafe paths, repository escapes, sensitive files, protected
    directories, system paths, and malformed paths are all treated as
    blocked.
    """

    decision = evaluate_safe_path(
        repository_root=repository_root,
        requested_path=requested_path,
        allow_absolute=allow_absolute,
        require_exists=False,
        allow_repository_root=False,
        check_blocked=True,
    )

    return not decision.allowed


def get_block_reason(
    repository_root: str | Path,
    requested_path: str | Path,
    *,
    allow_absolute: bool = False,
) -> PathSecurityDecision:
    """Return the complete security decision for a requested path."""

    return evaluate_safe_path(
        repository_root=repository_root,
        requested_path=requested_path,
        allow_absolute=allow_absolute,
        require_exists=False,
        allow_repository_root=False,
        check_blocked=True,
    )


def validate_safe_paths(
    repository_root: str | Path,
    requested_paths: Iterable[str | Path],
    *,
    allow_absolute: bool = False,
    require_exists: bool = False,
    check_blocked: bool = True,
) -> tuple[Path, ...]:
    """Validate multiple repository paths and return resolved unique paths."""

    resolved_paths: list[Path] = []
    seen: set[str] = set()

    for requested_path in requested_paths:
        resolved = validate_safe_path(
            repository_root=repository_root,
            requested_path=requested_path,
            allow_absolute=allow_absolute,
            require_exists=require_exists,
            allow_repository_root=False,
            check_blocked=check_blocked,
        )

        comparison_key = _normalize_for_comparison(resolved)

        if comparison_key not in seen:
            seen.add(comparison_key)
            resolved_paths.append(resolved)

    return tuple(resolved_paths)
class CommandBlockReason(str, Enum):
    """Reason why a terminal command was rejected."""

    ALLOWED = "allowed"
    EMPTY_COMMAND = "empty_command"
    COMMAND_TOO_LONG = "command_too_long"
    NULL_BYTE = "null_byte"
    MULTILINE_COMMAND = "multiline_command"
    SHELL_OPERATOR = "shell_operator"
    SHELL_EXPANSION = "shell_expansion"
    UNSAFE_EXECUTABLE = "unsafe_executable"
    EXECUTABLE_PATH = "executable_path"
    UNSAFE_ARGUMENT = "unsafe_argument"
    UNSAFE_SUBCOMMAND = "unsafe_subcommand"
    ENVIRONMENT_ASSIGNMENT = "environment_assignment"
    TOO_MANY_ARGUMENTS = "too_many_arguments"
    PARSE_ERROR = "parse_error"


@dataclass(frozen=True, slots=True)
class CommandSecurityDecision:
    """Structured result of terminal-command security validation."""

    allowed: bool
    reason: CommandBlockReason
    message: str
    original_command: str
    arguments: tuple[str, ...] = ()

    def raise_forbidden(self) -> None:
        """Raise UnsafeCommandError if the command was rejected."""

        if not self.allowed:
            raise UnsafeCommandError(self.message)


_DEFAULT_ALLOWED_EXECUTABLES: Final[frozenset[str]] = frozenset(
    {
        "python",
        "python.exe",
        "python3",
        "python3.exe",
        "py",
        "py.exe",
        "pytest",
        "pytest.exe",
        "node",
        "node.exe",
        "npm",
        "npm.cmd",
        "npm.exe",
        "npx",
        "npx.cmd",
        "npx.exe",
        "git",
        "git.exe",
    }
)

_BLOCKED_EXECUTABLES: Final[frozenset[str]] = frozenset(
    {
        "bash",
        "bash.exe",
        "sh",
        "sh.exe",
        "zsh",
        "zsh.exe",
        "fish",
        "fish.exe",
        "cmd",
        "cmd.exe",
        "command.com",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "wscript",
        "wscript.exe",
        "cscript",
        "cscript.exe",
        "mshta",
        "mshta.exe",
        "rundll32",
        "rundll32.exe",
        "reg",
        "reg.exe",
        "regedit",
        "regedit.exe",
        "sc",
        "sc.exe",
        "net",
        "net.exe",
        "net1",
        "net1.exe",
        "wmic",
        "wmic.exe",
        "diskpart",
        "diskpart.exe",
        "format",
        "format.com",
        "shutdown",
        "shutdown.exe",
        "taskkill",
        "taskkill.exe",
        "del",
        "erase",
        "rd",
        "rmdir",
        "rm",
        "mv",
        "cp",
        "chmod",
        "chown",
        "sudo",
        "su",
        "curl",
        "curl.exe",
        "wget",
        "wget.exe",
        "ftp",
        "ftp.exe",
        "ssh",
        "ssh.exe",
        "scp",
        "scp.exe",
        "sftp",
        "sftp.exe",
        "certutil",
        "certutil.exe",
        "bitsadmin",
        "bitsadmin.exe",
        "msiexec",
        "msiexec.exe",
    }
)

_BLOCKED_GIT_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {
        "add",
        "am",
        "apply",
        "bisect",
        "branch",
        "checkout",
        "cherry-pick",
        "clean",
        "clone",
        "commit",
        "config",
        "fetch",
        "gc",
        "init",
        "merge",
        "mv",
        "pull",
        "push",
        "rebase",
        "remote",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "submodule",
        "switch",
        "tag",
        "worktree",
    }
)

_ALLOWED_GIT_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {
        "diff",
        "grep",
        "log",
        "ls-files",
        "rev-parse",
        "show",
        "status",
    }
)

_ALLOWED_NPM_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {
        "run",
        "test",
    }
)

_ALLOWED_NPM_SCRIPTS: Final[frozenset[str]] = frozenset(
    {
        "build",
        "test",
        "lint",
        "typecheck",
        "type-check",
        "check",
    }
)

_ALLOWED_NPX_PACKAGES: Final[frozenset[str]] = frozenset(
    {
        "eslint",
        "jest",
        "prettier",
        "tsc",
        "vite",
        "vitest",
    }
)

_BLOCKED_PYTHON_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "-c",
        "-mhttp.server",
    }
)

_BLOCKED_ARGUMENTS_EXACT: Final[frozenset[str]] = frozenset(
    {
        "/c",
        "/k",
        "-command",
        "-encodedcommand",
        "-enc",
        "-executionpolicy",
        "-file",
        "--%",
    }
)

_BLOCKED_ARGUMENT_FRAGMENTS: Final[tuple[str, ...]] = (
    "invoke-expression",
    "invoke-webrequest",
    "invoke-restmethod",
    "downloadstring",
    "downloadfile",
    "start-process",
    "new-object net.webclient",
    "system.net.webclient",
    "system.net.http",
    "system.diagnostics.process",
    "os.system(",
    "subprocess.",
    "shutil.rmtree(",
    "pathlib.path.unlink(",
    ".unlink(",
    ".rmdir(",
    "remove-item",
    "set-content",
    "add-content",
    "out-file",
    "format-volume",
    "clear-disk",
    "remove-partition",
    "stop-computer",
)

_ENVIRONMENT_ASSIGNMENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*=.*$"
)

_URL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9+.-]*://",
    flags=re.IGNORECASE,
)

_EXECUTABLE_PATH_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\\/]"
)

_SHELL_EXPANSION_PATTERNS: Final[tuple[str, ...]] = (
    "$(",
    "${",
    "@(",
    "<(",
    ">(",
    "%comspec%",
    "%cmdcmdline%",
    "%path%",
    "%systemroot%",
    "%windir%",
    "%userprofile%",
)

_DANGEROUS_SHELL_CHARACTERS: Final[frozenset[str]] = frozenset(
    {
        "&",
        "|",
        ";",
        ">",
        "<",
        "`",
        "\r",
        "\n",
        "\x1a",
    }
)


def _command_to_text(command: str | Sequence[str]) -> str:
    """Convert a command representation to a diagnostic string."""

    if isinstance(command, str):
        return command

    return " ".join(str(argument) for argument in command)


def _strip_matching_quotes(value: str) -> str:
    """Remove one matching pair of surrounding single or double quotes."""

    if len(value) >= 2:
        if value[0] == value[-1] and value[0] in {"'", '"'}:
            return value[1:-1]

    return value


def _split_windows_compatible_command(command: str) -> tuple[str, ...]:
    """Split a command string while preserving Windows backslashes.

    ``shlex`` in non-POSIX mode preserves Windows path separators and
    quoted paths. Surrounding quotes are removed from each resulting token.
    """

    lexer = shlex.shlex(command, posix=False)
    lexer.whitespace_split = True
    lexer.commenters = ""

    arguments = tuple(
        _strip_matching_quotes(token)
        for token in lexer
    )

    return arguments


def _contains_unquoted_shell_operator(command: str) -> bool:
    """Detect shell control operators outside quoted string sections."""

    quote: str | None = None
    escaped = False

    for character in command:
        if escaped:
            escaped = False
            continue

        if character == "\\" and quote == '"':
            escaped = True
            continue

        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None

            continue

        if quote is None and character in _DANGEROUS_SHELL_CHARACTERS:
            return True

        if quote is None and character == "^":
            return True

    return False


def _contains_shell_expansion(command: str) -> bool:
    """Detect common shell, environment, and PowerShell expansions."""

    lowered = command.casefold()

    if any(pattern.casefold() in lowered for pattern in _SHELL_EXPANSION_PATTERNS):
        return True

    if re.search(r"%[A-Za-z_][A-Za-z0-9_]*%", command):
        return True

    if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*", command):
        return True

    return False


def _normalize_executable_name(value: str) -> str:
    """Normalize an executable token for allowlist comparison."""

    return Path(value).name.casefold().strip()


def _contains_executable_path(value: str) -> bool:
    """Return whether an executable token includes a directory path."""

    return bool(_EXECUTABLE_PATH_SEPARATOR_PATTERN.search(value))


def _validate_argument_text(argument: str) -> str | None:
    """Return an error message when an individual argument is unsafe."""

    if _contains_null_byte(argument):
        return "A command argument contains a null byte."

    if "\r" in argument or "\n" in argument:
        return "Multiline command arguments are not permitted."

    lowered = argument.casefold().strip()

    if lowered in _BLOCKED_ARGUMENTS_EXACT:
        return f"The terminal argument is blocked: {argument}"

    if any(fragment in lowered for fragment in _BLOCKED_ARGUMENT_FRAGMENTS):
        return f"The terminal argument contains blocked content: {argument}"

    if _URL_PATTERN.match(argument):
        return (
            "Network URLs are not permitted in Code Builder "
            f"validation commands: {argument}"
        )

    return None


def _validate_python_command(arguments: tuple[str, ...]) -> str | None:
    """Validate Python and pytest command arguments."""

    lowered_arguments = tuple(argument.casefold() for argument in arguments[1:])

    for argument in lowered_arguments:
        compact = argument.replace(" ", "")

        if compact in _BLOCKED_PYTHON_OPTIONS:
            return f"The Python option is blocked: {argument}"

        if argument == "-c":
            return "Inline Python execution with -c is not permitted."

        if argument == "-m":
            continue

        if argument.startswith("-m"):
            module_name = argument[2:].lstrip("= ")

            if module_name and module_name not in {
                "pytest",
                "compileall",
            }:
                return (
                    "Only the pytest and compileall Python modules may "
                    "be executed by the Code Builder."
                )

    if "-m" in lowered_arguments:
        module_index = lowered_arguments.index("-m")

        if module_index + 1 >= len(lowered_arguments):
            return "The Python -m option requires a module name."

        module_name = lowered_arguments[module_index + 1]

        if module_name not in {"pytest", "compileall"}:
            return (
                "Only python -m pytest and python -m compileall "
                "are permitted."
            )

    return None


def _validate_npm_command(arguments: tuple[str, ...]) -> str | None:
    """Validate npm commands against approved read/build operations."""

    if len(arguments) < 2:
        return "npm requires an approved subcommand."

    subcommand = arguments[1].casefold()

    if subcommand not in _ALLOWED_NPM_SUBCOMMANDS:
        return f"The npm subcommand is not permitted: {arguments[1]}"

    if subcommand == "run":
        if len(arguments) < 3:
            return "npm run requires an approved script name."

        script_name = arguments[2].casefold()

        if script_name not in _ALLOWED_NPM_SCRIPTS:
            return f"The npm script is not permitted: {arguments[2]}"

    return None


def _validate_npx_command(arguments: tuple[str, ...]) -> str | None:
    """Validate npx package execution against a strict allowlist."""

    if len(arguments) < 2:
        return "npx requires an approved package command."

    package_index = 1

    while package_index < len(arguments):
        current = arguments[package_index]

        if current.startswith("-"):
            if current.casefold() in {
                "--no-install",
                "--yes",
                "-y",
            }:
                package_index += 1
                continue

            return f"The npx option is not permitted: {current}"

        break

    if package_index >= len(arguments):
        return "npx requires an approved package command."

    package_name = arguments[package_index].casefold()

    if package_name not in _ALLOWED_NPX_PACKAGES:
        return f"The npx package is not permitted: {package_name}"

    return None


def _validate_git_command(arguments: tuple[str, ...]) -> str | None:
    """Allow only read-only Git inspection commands."""

    if len(arguments) < 2:
        return "git requires an approved read-only subcommand."

    subcommand_index = 1

    while subcommand_index < len(arguments):
        argument = arguments[subcommand_index]

        if argument.startswith("-"):
            if argument.casefold() in {
                "--no-pager",
                "--version",
            }:
                subcommand_index += 1
                continue

            return f"The global Git option is not permitted: {argument}"

        break

    if subcommand_index >= len(arguments):
        if "--version" in {
            argument.casefold() for argument in arguments[1:]
        }:
            return None

        return "git requires an approved read-only subcommand."

    subcommand = arguments[subcommand_index].casefold()

    if subcommand in _BLOCKED_GIT_SUBCOMMANDS:
        return f"The modifying Git subcommand is blocked: {subcommand}"

    if subcommand not in _ALLOWED_GIT_SUBCOMMANDS:
        return f"The Git subcommand is not permitted: {subcommand}"

    if subcommand == "diff":
        blocked_diff_options = {
            "--no-index",
            "--output",
            "--output-indicator-new",
            "--output-indicator-old",
            "--output-indicator-context",
        }

        for argument in arguments[subcommand_index + 1:]:
            lowered = argument.casefold()

            if (
                lowered in blocked_diff_options
                or any(
                    lowered.startswith(f"{option}=")
                    for option in blocked_diff_options
                )
            ):
                return f"The Git diff option is blocked: {argument}"

    return None


def _validate_node_command(arguments: tuple[str, ...]) -> str | None:
    """Prevent inline JavaScript and unsafe Node.js options."""

    blocked_options = {
        "-e",
        "--eval",
        "-p",
        "--print",
        "--inspect",
        "--inspect-brk",
        "--require",
        "-r",
    }

    for argument in arguments[1:]:
        lowered = argument.casefold()

        if lowered in blocked_options:
            return f"The Node.js option is blocked: {argument}"

        if any(
            lowered.startswith(f"{option}=")
            for option in blocked_options
        ):
            return f"The Node.js option is blocked: {argument}"

    return None


def _validate_executable_policy(
    arguments: tuple[str, ...],
) -> str | None:
    """Run executable-specific command policy validation."""

    executable = _normalize_executable_name(arguments[0])

    if executable in {
        "python",
        "python.exe",
        "python3",
        "python3.exe",
        "py",
        "py.exe",
        "pytest",
        "pytest.exe",
    }:
        return _validate_python_command(arguments)

    if executable in {
        "npm",
        "npm.cmd",
        "npm.exe",
    }:
        return _validate_npm_command(arguments)

    if executable in {
        "npx",
        "npx.cmd",
        "npx.exe",
    }:
        return _validate_npx_command(arguments)

    if executable in {
        "git",
        "git.exe",
    }:
        return _validate_git_command(arguments)

    if executable in {
        "node",
        "node.exe",
    }:
        return _validate_node_command(arguments)

    return None


def evaluate_input_command(
    command: str | Sequence[str],
    *,
    allowed_executables: Iterable[str] | None = None,
    maximum_length: int = 8_192,
    maximum_arguments: int = 128,
) -> CommandSecurityDecision:
    """Evaluate a terminal command without executing it.

    Security assumptions:

    - The sanitized result must be executed with ``shell=False``.
    - The returned argument tuple must be passed directly to subprocess.
    - The caller must not join the arguments back into a shell string.
    - Executable paths are rejected; only approved executable names are
      accepted.
    - Shell chaining, redirection, substitutions, environment expansion,
      multiline input, network URLs, and known dangerous arguments are
      rejected.

    Args:
        command:
            Command string or pre-tokenized command argument sequence.
        allowed_executables:
            Optional executable allowlist. It can only narrow or explicitly
            replace the default allowlist for the current caller.
        maximum_length:
            Maximum total command text length.
        maximum_arguments:
            Maximum number of command arguments.

    Returns:
        A structured command-security decision.
    """

    original_command = _command_to_text(command)

    if not original_command.strip():
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.EMPTY_COMMAND,
            message="The terminal command cannot be empty.",
            original_command=original_command,
        )

    if len(original_command) > maximum_length:
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.COMMAND_TOO_LONG,
            message=(
                "The terminal command exceeds the maximum permitted "
                f"length of {maximum_length} characters."
            ),
            original_command=original_command,
        )

    if _contains_null_byte(original_command):
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.NULL_BYTE,
            message="The terminal command contains a null byte.",
            original_command=original_command,
        )

    if "\r" in original_command or "\n" in original_command:
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.MULTILINE_COMMAND,
            message="Multiline terminal commands are not permitted.",
            original_command=original_command,
        )

    if isinstance(command, str):
        if _contains_unquoted_shell_operator(command):
            return CommandSecurityDecision(
                allowed=False,
                reason=CommandBlockReason.SHELL_OPERATOR,
                message=(
                    "Shell chaining, redirection, pipes, and control "
                    "operators are not permitted."
                ),
                original_command=original_command,
            )

        if _contains_shell_expansion(command):
            return CommandSecurityDecision(
                allowed=False,
                reason=CommandBlockReason.SHELL_EXPANSION,
                message=(
                    "Shell variables, command substitutions, and "
                    "environment expansions are not permitted."
                ),
                original_command=original_command,
            )

        try:
            arguments = _split_windows_compatible_command(command)
        except (ValueError, RuntimeError) as exc:
            return CommandSecurityDecision(
                allowed=False,
                reason=CommandBlockReason.PARSE_ERROR,
                message=f"The terminal command could not be parsed: {exc}",
                original_command=original_command,
            )
    else:
        try:
            arguments = tuple(str(argument) for argument in command)
        except TypeError as exc:
            return CommandSecurityDecision(
                allowed=False,
                reason=CommandBlockReason.PARSE_ERROR,
                message=f"The terminal command is invalid: {exc}",
                original_command=original_command,
            )

    if not arguments or not arguments[0].strip():
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.EMPTY_COMMAND,
            message="The terminal command does not contain an executable.",
            original_command=original_command,
        )

    if len(arguments) > maximum_arguments:
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.TOO_MANY_ARGUMENTS,
            message=(
                "The terminal command exceeds the maximum permitted "
                f"argument count of {maximum_arguments}."
            ),
            original_command=original_command,
            arguments=arguments,
        )

    executable_token = arguments[0].strip()
    executable_name = _normalize_executable_name(executable_token)

    if _contains_executable_path(executable_token):
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.EXECUTABLE_PATH,
            message=(
                "Executable paths are not permitted. Use an approved "
                f"executable name only: {executable_token}"
            ),
            original_command=original_command,
            arguments=arguments,
        )

    if executable_name in _BLOCKED_EXECUTABLES:
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.UNSAFE_EXECUTABLE,
            message=f"The terminal executable is explicitly blocked: "
            f"{executable_token}",
            original_command=original_command,
            arguments=arguments,
        )

    if allowed_executables is None:
        normalized_allowlist = _DEFAULT_ALLOWED_EXECUTABLES
    else:
        normalized_allowlist = frozenset(
            _normalize_executable_name(value)
            for value in allowed_executables
            if str(value).strip()
        )

    if executable_name not in normalized_allowlist:
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.UNSAFE_EXECUTABLE,
            message=(
                "The terminal executable is not in the approved "
                f"allowlist: {executable_token}"
            ),
            original_command=original_command,
            arguments=arguments,
        )

    for index, argument in enumerate(arguments):
        if not argument:
            continue

        if index == 0:
            continue

        if _ENVIRONMENT_ASSIGNMENT_PATTERN.fullmatch(argument):
            return CommandSecurityDecision(
                allowed=False,
                reason=CommandBlockReason.ENVIRONMENT_ASSIGNMENT,
                message=(
                    "Inline environment-variable assignments are not "
                    f"permitted: {argument}"
                ),
                original_command=original_command,
                arguments=arguments,
            )

        error_message = _validate_argument_text(argument)

        if error_message is not None:
            return CommandSecurityDecision(
                allowed=False,
                reason=CommandBlockReason.UNSAFE_ARGUMENT,
                message=error_message,
                original_command=original_command,
                arguments=arguments,
            )

    policy_error = _validate_executable_policy(arguments)

    if policy_error is not None:
        return CommandSecurityDecision(
            allowed=False,
            reason=CommandBlockReason.UNSAFE_SUBCOMMAND,
            message=policy_error,
            original_command=original_command,
            arguments=arguments,
        )

    return CommandSecurityDecision(
        allowed=True,
        reason=CommandBlockReason.ALLOWED,
        message=(
            "The terminal command passed security validation. Execute "
            "the returned argument tuple with shell=False."
        ),
        original_command=original_command,
        arguments=arguments,
    )


def sanitize_input_command(
    command: str | Sequence[str],
    *,
    allowed_executables: Iterable[str] | None = None,
    maximum_length: int = 8_192,
    maximum_arguments: int = 128,
) -> tuple[str, ...]:
    """Validate and return a safe subprocess argument tuple.

    The returned tuple is suitable for:

    ``subprocess.run(arguments, shell=False, ...)``

    It must never be joined into a string and passed to ``shell=True``.

    Args:
        command:
            A command string or an existing argument sequence.
        allowed_executables:
            Optional executable allowlist.
        maximum_length:
            Maximum accepted command length.
        maximum_arguments:
            Maximum accepted argument count.

    Returns:
        A validated immutable tuple of command arguments.

    Raises:
        UnsafeCommandError:
            If the command violates any security rule.
    """

    decision = evaluate_input_command(
        command=command,
        allowed_executables=allowed_executables,
        maximum_length=maximum_length,
        maximum_arguments=maximum_arguments,
    )

    decision.raise_forbidden()

    if not decision.arguments:
        raise UnsafeCommandError(
            "Command validation succeeded without producing arguments."
        )

    return decision.arguments


def validate_command_working_directory(
    repository_root: str | Path,
    working_directory: str | Path = ".",
) -> Path:
    """Validate a subprocess working directory inside the repository.

    The directory must exist, must be a directory, and must remain inside
    the resolved LUMINA repository root.
    """

    resolved_directory = validate_safe_path(
        repository_root=repository_root,
        requested_path=working_directory,
        allow_absolute=False,
        require_exists=True,
        allow_repository_root=True,
        check_blocked=True,
    )

    if not resolved_directory.is_dir():
        raise UnsafePathError(
            "The command working directory is not a directory: "
            f"{resolved_directory}"
        )

    return resolved_directory


def prepare_safe_subprocess(
    repository_root: str | Path,
    command: str | Sequence[str],
    *,
    working_directory: str | Path = ".",
    allowed_executables: Iterable[str] | None = None,
    maximum_length: int = 8_192,
    maximum_arguments: int = 128,
) -> tuple[tuple[str, ...], Path]:
    """Prepare validated arguments and working directory for subprocess.

    This helper does not execute anything. It returns:

    1. A sanitized argument tuple.
    2. A securely resolved working directory.

    The caller must execute the arguments with ``shell=False``.
    """

    arguments = sanitize_input_command(
        command=command,
        allowed_executables=allowed_executables,
        maximum_length=maximum_length,
        maximum_arguments=maximum_arguments,
    )

    resolved_working_directory = validate_command_working_directory(
        repository_root=repository_root,
        working_directory=working_directory,
    )

    return arguments, resolved_working_directory


__all__ = [
    "BlockReason",
    "BlockedFileError",
    "CommandBlockReason",
    "CommandSecurityDecision",
    "PathSecurityDecision",
    "SecurityError",
    "UnsafeCommandError",
    "UnsafePathError",
    "evaluate_input_command",
    "evaluate_safe_path",
    "get_block_reason",
    "is_file_blocked",
    "prepare_safe_subprocess",
    "sanitize_input_command",
    "validate_command_working_directory",
    "validate_safe_path",
    "validate_safe_paths",
]