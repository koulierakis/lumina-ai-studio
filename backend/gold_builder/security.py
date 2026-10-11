"""Security helpers: canonical path resolution + sandboxed environment.

All file I/O and all child-process launches must go through these helpers.

- `safe_resolve(root, rel_path)` returns an absolute Path guaranteed to
  live inside `root`. Rejects `..`, absolute paths, backslash-escape,
  URL-encoded traversal, and symlink escape.
- `sandbox_env(extra)` returns a minimal environment mapping for child
  processes. No engine/provider secrets are ever passed through.
- `looks_like_secret(text)` returns True if the given text contains what
  looks like an API key or other secret. Used at export time to refuse
  packaging anything that might leak credentials.
"""
from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import Iterable, List, Mapping, Optional


# ---------------------- path safety ----------------------

class UnsafePathError(ValueError):
    """Raised when a caller supplies a path that would escape the sandbox."""


def _decode_all(rel: str) -> str:
    """Decode URL-encoded segments up to a few passes to defeat double-encoding."""
    prev = rel
    for _ in range(3):
        decoded = urllib.parse.unquote(prev)
        if decoded == prev:
            return decoded
        prev = decoded
    return prev


def safe_resolve(root: Path, rel_path: str) -> Path:
    """Resolve `rel_path` inside `root`. Raise `UnsafePathError` on escape."""
    if rel_path is None:
        raise UnsafePathError("path is required")

    # normalise separators + decode common escapes
    candidate = _decode_all(str(rel_path)).replace("\\", "/")
    candidate = candidate.strip()

    if not candidate:
        raise UnsafePathError("empty path")

    # NUL bytes are always malicious
    if "\0" in candidate:
        raise UnsafePathError("null byte in path")

    # reject absolute paths outright (Unix + Windows drive letter)
    if candidate.startswith("/") or candidate.startswith("\\"):
        raise UnsafePathError(f"absolute path not allowed: {rel_path!r}")
    if re.match(r"^[a-zA-Z]:[\\/]", candidate):
        raise UnsafePathError(f"absolute path not allowed: {rel_path!r}")

    # reject any traversal component
    parts = [p for p in candidate.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UnsafePathError(f"path traversal not allowed: {rel_path!r}")

    root_resolved = root.resolve()
    target = (root / "/".join(parts)).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as e:
        raise UnsafePathError(
            f"path escapes root: {rel_path!r} → {target}"
        ) from e

    # symlink-escape check on any existing ancestor
    node: Optional[Path] = target
    while node is not None and node != root_resolved:
        if node.is_symlink():
            real = node.resolve()
            try:
                real.relative_to(root_resolved)
            except ValueError as e:
                raise UnsafePathError(
                    f"symlink escapes root: {node} → {real}"
                ) from e
        if node.parent == node:
            break
        node = node.parent

    return target


def is_github_remote(value: str) -> bool:
    """Return whether a remote URL targets GitHub's exact hostname."""
    candidate = value.strip()
    try:
        if candidate.lower().startswith("git@"):
            hostname = candidate[4:].partition(":")[0]
        else:
            hostname = urllib.parse.urlsplit(candidate).hostname or ""
    except ValueError:
        return False
    return hostname.casefold() in {"github.com", "www.github.com"}


# ---------------------- child-process environment ----------------------

# Explicit allowlist of environment variables that child processes may see.
# Anything not in this set is stripped before spawning.
_ALLOWED_ENV_VARS = frozenset({
    "PATH", "HOME", "USERPROFILE", "TMPDIR", "TMP", "TEMP",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "PORT", "HOST",
    "NODE_ENV", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
    "VIRTUAL_ENV", "SHELL", "USER", "LOGNAME",
    "PWD", "OLDPWD",
    "GIT_TERMINAL_PROMPT",
    # Playwright browser discovery for the parent process only — we still
    # strip it for generated apps by NOT adding it here.
})

# Extra vars that generated apps sometimes need (frontend build tools):
_ALLOWED_ENV_PREFIXES = ("NPM_", "YARN_", "NPM_CONFIG_",)


def _key_is_allowed(key: str) -> bool:
    if key in _ALLOWED_ENV_VARS:
        return True
    for prefix in _ALLOWED_ENV_PREFIXES:
        if key.startswith(prefix):
            return True
    return False


def sandbox_env(extra: Optional[Mapping[str, str]] = None) -> dict:
    """Return a *fresh* environment dict for a child process.

    Only variables that are explicitly on the allowlist are inherited from
    the parent. `extra` is merged in AFTER filtering — callers use it to
    inject values like PORT or NODE_ENV that the generated app needs.

    The current interpreter's venv `bin/` directory is prepended to PATH so
    generated apps can find pip-installed CLIs (uvicorn, flask, django-admin,
    …) without leaking the venv path as a credential.
    """
    import sys
    out: dict = {}
    for k, v in os.environ.items():
        if _key_is_allowed(k):
            out[k] = v
    # Prepend venv bin to PATH so tools installed via pip are discoverable
    venv_bin = os.path.dirname(sys.executable) if sys.executable else ""
    if venv_bin and venv_bin not in out.get("PATH", "").split(os.pathsep):
        out["PATH"] = venv_bin + os.pathsep + out.get("PATH", "")
    if extra:
        for k, v in extra.items():
            if not _key_is_allowed(k):
                if not (k.startswith("APP_") or k in {"PORT", "HOST", "NODE_ENV"}):
                    continue
            out[k] = str(v)
    return out


# ---------------------- secret scanner ----------------------

_SECRET_PATTERNS: List[re.Pattern] = [
    re.compile(r"sk-emergent-[A-Za-z0-9]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),           # generic OpenAI-style
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),    # Anthropic
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),        # Google
    re.compile(r"AKIA[0-9A-Z]{16}"),              # AWS access key id
    re.compile(r"ASIA[0-9A-Z]{16}"),              # AWS temp key
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),          # GitHub PAT
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), # Slack tokens
    re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"),
]

# Substrings inside a matched token that mark it as an obvious placeholder,
# example, or test fixture — the scanner should NOT flag these as leaks.
_PLACEHOLDER_MARKERS = (
    "xxxx", "XXXX", "example", "EXAMPLE",
    "your-key", "your_key", "YOUR_KEY",
    "changeme", "CHANGEME",
    "dummy", "DUMMY", "fake", "FAKE",
    "placeholder", "PLACEHOLDER",
    "should-not-leak", "should_not_leak",
    "sample", "SAMPLE",
)


def _is_placeholder(matched: str) -> bool:
    return any(marker in matched for marker in _PLACEHOLDER_MARKERS)

# Files we always refuse to package
_ALWAYS_STRIP_NAMES = frozenset({
    ".env", ".env.local", ".env.production", ".env.staging",
    ".env.development", ".env.dev", ".env.prod",
    "credentials", "secrets.json", "id_rsa", "id_ed25519",
})


def is_secretful_filename(name: str) -> bool:
    base = os.path.basename(name)
    if base in _ALWAYS_STRIP_NAMES:
        return True
    if base.startswith(".env.") and base != ".env.example":
        return True
    if base == ".env":
        return True
    return False


def looks_like_secret(text: str) -> Optional[str]:
    """Return the first matched (non-placeholder) token, or None."""
    if not text:
        return None
    for pat in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            token = m.group(0)
            if _is_placeholder(token):
                continue
            return token[:16] + "…"  # short redacted marker
    return None


def scan_paths_for_secrets(files: Iterable[Path]) -> List[str]:
    """Return list of "path: <redacted marker>" for files containing secrets."""
    hits: List[str] = []
    for p in files:
        try:
            if p.stat().st_size > 512 * 1024:
                continue
            data = p.read_bytes()
            if b"\0" in data[:512]:
                continue
            text = data.decode("utf-8", errors="ignore")
        except OSError:
            continue
        hit = looks_like_secret(text)
        if hit:
            hits.append(f"{p}: {hit}")
    return hits


class SecretDetectedError(RuntimeError):
    """Raised by exporter when a would-be-packaged file contains secrets."""
