"""Deterministic unified-diff application for existing-repo patches.

Existing-repo edits used to require the model to return the FULL corrected file
on every change. That is token-expensive and lets an unrelated rewrite slip in
silently. This module lets the model return a small unified diff instead, which
is applied here deterministically; when a diff cannot be trusted the caller
falls back to the full-file contract.

Design rules:
* ``apply_unified_diff`` is strict. Any hunk whose context or removed lines do
  not match the original returns ``None`` — a partially-applied patch is worse
  than a rejected one.
* Parsing is tolerant of surrounding noise (``diff --git``/``---``/``+++``
  headers, blank lines between hunks) so real model output is accepted, but the
  hunk body itself must be well-formed.
* Nothing here calls a provider; it is pure string work and therefore testable
  without a live LLM.
"""
from __future__ import annotations

import difflib
import re
from typing import List, Optional, Tuple

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*\n(.*?)```", re.DOTALL)
_NO_NEWLINE_MARKER = "\\ No newline at end of file"


def looks_like_unified_diff(text: str) -> bool:
    """True when ``text`` contains at least one well-formed ``@@`` hunk header."""
    if not text:
        return False
    return any(_HUNK_HEADER_RE.match(line) for line in text.splitlines())


def _parse_hunks(diff_text: str) -> Optional[List[Tuple[Tuple[int, int], List[str]]]]:
    lines = diff_text.splitlines()
    hunks: List[Tuple[Tuple[int, int], List[str]]] = []
    i = 0
    while i < len(lines):
        match = _HUNK_HEADER_RE.match(lines[i])
        if not match:
            i += 1
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        i += 1
        body: List[str] = []
        while i < len(lines) and not _HUNK_HEADER_RE.match(lines[i]):
            body.append(lines[i])
            i += 1
        # A diff that ends with a newline yields one trailing empty element.
        while body and body[-1] == "":
            body.pop()
        hunks.append(((old_start, old_count), body))
    if not hunks:
        return None
    return hunks


def apply_unified_diff(original: str, diff_text: str) -> Optional[str]:
    """Apply ``diff_text`` to ``original``; return the new text or ``None``.

    ``None`` means the diff did not apply cleanly (bad context, bad header, or
    overlapping hunks). The caller must not write a partial result.
    """
    if original is None:
        return None
    hunks = _parse_hunks(diff_text or "")
    if not hunks:
        return None

    original_lines = original.splitlines()
    trailing_newline = original.endswith("\n")

    out: List[str] = []
    pos = 0
    for (old_start, old_count), body in hunks:
        # old_count == 0 means a pure insertion *after* line old_start.
        target = old_start if old_count == 0 else old_start - 1
        if target < pos or target > len(original_lines):
            return None
        out.extend(original_lines[pos:target])
        pos = target
        for line in body:
            if line == _NO_NEWLINE_MARKER:
                continue
            if not line:
                return None
            tag, content = line[0], line[1:]
            if tag == " ":
                if pos >= len(original_lines) or original_lines[pos] != content:
                    return None
                out.append(content)
                pos += 1
            elif tag == "-":
                if pos >= len(original_lines) or original_lines[pos] != content:
                    return None
                pos += 1
            elif tag == "+":
                out.append(content)
            else:
                return None
    out.extend(original_lines[pos:])

    result = "\n".join(out)
    if trailing_newline and result:
        result += "\n"
    return result


def _candidate_diffs(text: str) -> List[str]:
    candidates = [text or ""]
    for match in _FENCE_RE.finditer(text or ""):
        candidates.append(match.group(1))
    return candidates


def apply_model_patch(original: str, text: str) -> Optional[str]:
    """Try to apply any unified diff found in ``text`` to ``original``.

    Handles raw diffs and diffs wrapped in a single fenced code block. Returns
    ``None`` when no candidate diff applies cleanly, so the caller can fall back
    to interpreting the response as full-file contents.
    """
    for candidate in _candidate_diffs(text):
        stripped = candidate.strip("\n")
        if not looks_like_unified_diff(stripped):
            continue
        applied = apply_unified_diff(original, stripped)
        if applied is not None:
            return applied
    return None


def make_unified_diff(original: str, new: str, path: str = "file") -> str:
    """Build a unified diff (used by tests and by any future diff-emitting path)."""
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
