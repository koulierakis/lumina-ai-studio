"""Structured AI patch generation for LUMINA Code Builder.

This module adds the missing bridge between an approved implementation plan
and PatchService's deterministic validation/application engine. The model never
writes files directly: it may only propose a small, schema-constrained patch
which PatchService dry-runs before TaskService can apply it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final
from urllib.parse import urlparse

from .patch_service import (
    PatchRequestPayload,
    PatchService,
    PatchServiceError,
    ProposedPatchOperation,
)

DEFAULT_MODEL: Final[str] = "qwen2.5-coder:7b"
DEFAULT_OLLAMA_URL: Final[str] = "http://127.0.0.1:11434"
MAX_CONTEXT_FILES: Final[int] = 12
MAX_FILE_CHARACTERS: Final[int] = 40_000
MAX_TOTAL_CONTEXT_CHARACTERS: Final[int] = 180_000
MAX_OPERATIONS: Final[int] = 50
MAX_RESPONSE_CHARACTERS: Final[int] = 1_000_000
ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "create",
        "replace_file",
        "replace_text",
        "unified_diff",
        "delete",
        "rename",
    }
)
_PATH_KEYS: Final[frozenset[str]] = frozenset(
    {
        "path",
        "file",
        "file_path",
        "filepath",
        "relative_path",
        "previous_path",
        "target_path",
        "source_path",
        "destination_path",
        "new_path",
    }
)

# Small local models often emit synonymous operation names. Mapping them to
# the canonical operation keeps identical semantics without expanding what the
# patch engine executes: every mapped operation is still validated exactly like
# its canonical form (allow-listed path, existence rules, dry-run).
_OPERATION_ALIASES: Final[dict[str, str]] = {
    "add": "create",
    "add_file": "create",
    "new": "create",
    "new_file": "create",
    "create_file": "create",
    "overwrite": "replace_file",
    "overwrite_file": "replace_file",
    "replace": "replace_file",
    "update_file": "replace_file",
    "modify_file": "replace_file",
    "edit_file": "replace_file",
    "delete_file": "delete",
    "remove": "delete",
    "remove_file": "delete",
    "erase": "delete",
    "rename_file": "rename",
    "move": "rename",
    "move_file": "rename",
}
_WRITE_STYLE_ALIASES: Final[frozenset[str]] = frozenset(
    {"write", "write_file", "save", "save_file", "set_file"}
)


@dataclass(frozen=True, slots=True)
class _PlanOperations:
    """Operations explicitly authorized by the approved plan."""

    create_paths: frozenset[str] = frozenset()
    update_paths: frozenset[str] = frozenset()
    delete_paths: frozenset[str] = frozenset()
    rename_destinations: dict[str, str] = field(default_factory=dict)


def _canonicalize_operation(raw_operation: Any, *, path_exists: bool) -> str:
    """Map common small-model operation variants without widening file scope.

    The returned operation is still subjected to the approved-path allowlist and
    all deterministic existence/content/hash checks. Write-style aliases are
    resolved from repository state: creating a missing approved file or replacing
    an existing approved file.
    """

    operation = str(raw_operation or "").strip().casefold().replace("-", "_").replace(" ", "_")
    operation = _OPERATION_ALIASES.get(operation, operation)
    if operation in _WRITE_STYLE_ALIASES:
        return "replace_file" if path_exists else "create"
    return operation


class AIPatchGenerationError(RuntimeError):
    """Raised when a safe structured patch cannot be generated."""


def _dump(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:
            try:
                return model_dump(exclude_none=True)
            except TypeError:
                return model_dump()
    if isinstance(value, Mapping):
        return {str(key): _dump(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_dump(item) for item in value]
    return value


def _lf_normalized(text: str) -> str:
    """Normalize any line-ending style to LF for deterministic matching."""

    return text.replace("\r\n", "\n").replace("\r", "\n")


def _file_style_text(text: str, *, crlf_file: bool) -> str:
    """Map LF-normalized text back to the file's actual line endings.

    PatchService counts search occurrences against the raw file bytes. On
    Windows fixture and repository files commonly use CRLF, while small local
    models emit LF text. Converting the proposed search/replacement text to
    the file's own newline style keeps the deterministic engine consistent
    with what the model actually meant.
    """

    normalized = _lf_normalized(text)
    if crlf_file and "\n" in normalized:
        return normalized.replace("\n", "\r\n")
    return normalized


def _normalize_relative_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\\", "/")
    if not text or "\x00" in text:
        return None
    if text.startswith("/") or ":" in text.split("/", 1)[0]:
        return None
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()

def _coerce_repository_relative_path(raw: Any, root: Path) -> str | None:
    """Normalize a model-provided path without widening the approved scope.

    Small local models sometimes echo the repository root from the analysis
    context and emit an absolute path even though the approved plan carries
    repository-relative paths. An absolute path is accepted only when it
    resolves inside the repository root, and the result must still pass the
    approved-paths allowlist afterwards. Everything else stays refused.
    """

    normalized = _normalize_relative_path(raw)
    if normalized is not None:
        return normalized
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or "\x00" in text:
        return None
    candidate = Path(text)
    if not candidate.is_absolute():
        return None
    try:
        resolved = candidate.resolve(strict=False)
        relative = resolved.relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    return _normalize_relative_path(relative)


def _collect_plan_paths(plan: Any) -> tuple[str, ...]:
    collected: list[str] = []
    seen: set[str] = set()

    # Track list-valued boundary keys so nested mappings inside "files" and
    # "steps" are walked with their item key. The planning service's models.py
    # file changes carry their location under "relative_path" while plan steps
    # use "file_paths"; without the boundary the step lists would surface bare
    # step titles as fake paths and real file locations would be missed.
    _FILE_LIST_KEYS: Final[frozenset[str]] = frozenset(
        {"files", "file_paths", "filechanges", "changes", "steps"}
    )

    def visit(value: Any, key: str | None = None) -> None:
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                normalized_key = str(child_key).casefold()
                if normalized_key in _PATH_KEYS:
                    if isinstance(child_value, Sequence) and not isinstance(
                        child_value, (str, bytes, bytearray)
                    ):
                        for item in child_value:
                            add(item)
                    else:
                        add(child_value)
                elif normalized_key in _FILE_LIST_KEYS:
                    if isinstance(child_value, Sequence) and not isinstance(
                        child_value, (str, bytes, bytearray)
                    ):
                        for item in child_value:
                            if isinstance(item, str):
                                add(item)
                            else:
                                visit(item, normalized_key)
                    else:
                        visit(child_value, normalized_key)
                else:
                    visit(child_value, normalized_key)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                visit(item, key)

    def add(raw: Any) -> None:
        normalized = _normalize_relative_path(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            collected.append(normalized)

    visit(_dump(plan))
    return tuple(collected)


_PLAN_OPERATION_ALIASES: Final[dict[str, str]] = {
    "add": "create",
    "new": "create",
    "create_file": "create",
    "create_directory": "create",
    "create-directory": "create",
    "modify": "update",
    "edit": "update",
    "change": "update",
    "replace": "update",
    "patch": "update",
    "refactor": "update",
    "remove": "delete",
    "delete_file": "delete",
    "move": "rename",
    "rename_file": "rename",
}


def _normalize_plan_operation(raw_operation: Any) -> str:
    operation = str(raw_operation or "").strip().casefold()
    operation = operation.replace("-", "_").replace(" ", "_")
    return _PLAN_OPERATION_ALIASES.get(operation, operation)


def _collect_plan_operations(plan: Any) -> _PlanOperations:
    """Extract the exact operations the approved plan authorizes.

    Handles both the domain ChangePlan shape (``changes[].change_type`` +
    ``relative_path``/``previous_path``) and the GeneratedChangePlan shape
    (``files[].operation`` + ``path``/``destination_path``). Deletes and
    renames are authorized only when the plan names them explicitly.
    """

    dumped = _dump(plan)
    if not isinstance(dumped, Mapping):
        return _PlanOperations()
    raw_changes = dumped.get("changes")
    if not isinstance(raw_changes, Sequence) or isinstance(
        raw_changes,
        (str, bytes, bytearray),
    ):
        raw_changes = dumped.get("files")
    if not isinstance(raw_changes, Sequence) or isinstance(
        raw_changes,
        (str, bytes, bytearray),
    ):
        return _PlanOperations()

    creates: set[str] = set()
    updates: set[str] = set()
    deletes: set[str] = set()
    renames: dict[str, str] = {}

    for change in raw_changes:
        if not isinstance(change, Mapping):
            continue
        operation = _normalize_plan_operation(
            change.get("change_type")
            or change.get("operation")
            or change.get("type")
            or change.get("action")
        )
        raw_path = change.get("relative_path") or change.get("path") or change.get("file_path") or change.get("target_path")
        normalized_path = _normalize_relative_path(raw_path)
        if normalized_path is None:
            continue
        if operation == "create":
            creates.add(normalized_path)
        elif operation == "update":
            updates.add(normalized_path)
        elif operation == "delete":
            deletes.add(normalized_path)
        elif operation == "rename":
            raw_destination = change.get("destination_path") or change.get("new_path")
            if raw_destination is not None:
                normalized_destination = _normalize_relative_path(raw_destination)
                if normalized_destination is not None and normalized_destination != normalized_path:
                    renames[normalized_path] = normalized_destination
                    continue
            raw_previous = change.get("previous_path") or change.get("source_path")
            if raw_previous is not None:
                # Domain ChangePlan renames: previous_path is the source and
                # relative_path is the destination.
                normalized_previous = _normalize_relative_path(raw_previous)
                if normalized_previous is not None and normalized_previous != normalized_path:
                    renames[normalized_previous] = normalized_path
                    continue
            updates.add(normalized_path)

    return _PlanOperations(
        create_paths=frozenset(creates),
        update_paths=frozenset(updates),
        delete_paths=frozenset(deletes),
        rename_destinations=renames,
    )


def _collect_required_plan_paths(plan: Any) -> tuple[str, ...]:
    """Every file the approved plan requires the patch to cover.

    Deletes and renames are required coverage as well: a plan that marks a
    file for deletion must not silently become an edit of that file, and a
    rename must cover both the source and its approved destination.
    """

    operations = _collect_plan_operations(plan)
    result: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        if path and path not in seen:
            seen.add(path)
            result.append(path)

    for path in operations.create_paths:
        add(path)
    for path in operations.update_paths:
        add(path)
    for path in operations.delete_paths:
        add(path)
    for source, destination in operations.rename_destinations.items():
        add(source)
        add(destination)

    return tuple(result)


def _ensure_required_plan_coverage(
    patch: PatchRequestPayload,
    required_paths: Sequence[str],
) -> None:
    if not required_paths:
        return
    operation_paths = {
        operation.path for operation in patch.operations
    } | {
        operation.destination_path
        for operation in patch.operations
        if operation.destination_path
    }
    missing = [path for path in required_paths if path not in operation_paths]
    if missing:
        raise AIPatchGenerationError(
            "AI patch is incomplete; required planned files are missing: "
            + ", ".join(missing)
        )


def _task_paths(task: Any) -> tuple[str, ...]:
    values = getattr(task, "target_paths", ()) or ()
    result: list[str] = []
    for value in values:
        normalized = _normalize_relative_path(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


def _safe_repository_path(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AIPatchGenerationError(
            f"AI patch path escapes the repository: {relative_path}"
        ) from exc
    return candidate


def _build_file_context(root: Path, paths: Sequence[str]) -> tuple[str, dict[str, str]]:
    chunks: list[str] = []
    hashes: dict[str, str] = {}
    total = 0

    for relative_path in paths[:MAX_CONTEXT_FILES]:
        absolute_path = _safe_repository_path(root, relative_path)
        if absolute_path.exists() and absolute_path.is_file():
            try:
                raw = absolute_path.read_bytes()
                text = raw.decode("utf-8-sig")
            except (OSError, UnicodeDecodeError):
                chunks.append(f"FILE: {relative_path}\n[unavailable as UTF-8 text]")
                continue
            hashes[relative_path] = hashlib.sha256(raw).hexdigest()
            excerpt = text[:MAX_FILE_CHARACTERS]
            chunk = f"FILE: {relative_path}\n---\n{excerpt}\n---"
        elif not absolute_path.exists():
            chunk = f"FILE: {relative_path}\n[does not exist; may only be created if the approved plan permits it]"
        else:
            continue

        if total + len(chunk) > MAX_TOTAL_CONTEXT_CHARACTERS:
            break
        chunks.append(chunk)
        total += len(chunk)

    if not chunks:
        raise AIPatchGenerationError(
            "The approved plan did not provide readable file targets for patch generation."
        )
    return "\n\n".join(chunks), hashes


def _schema() -> dict[str, Any]:
    operation_properties: dict[str, Any] = {
        "operation": {"type": "string", "enum": sorted(ALLOWED_OPERATIONS)},
        "path": {"type": "string", "minLength": 1, "maxLength": 1024},
        "destination_path": {"type": ["string", "null"]},
        "content": {"type": ["string", "null"]},
        "search_text": {"type": ["string", "null"]},
        "replacement_text": {"type": ["string", "null"]},
        "unified_diff": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["operations"],
        "properties": {
            "operations": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_OPERATIONS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "operation",
                        "path",
                        "content",
                        "search_text",
                        "replacement_text",
                        "unified_diff",
                        "description",
                    ],
                    "properties": operation_properties,
                },
            },
            "description": {"type": ["string", "null"]},
        },
    }


def _error_chain_detail(error: BaseException) -> str:
    """Join an exception with its causes into one diagnostic string.

    PatchService raises a shallow ``PatchTransactionError`` whose underlying
    validation failure is chained as the cause. Preserving the chain gives
    the model (and the task error) the precise deterministic rejection
    reason instead of a generic wrapper message.
    """

    parts: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).strip()
        detail = (
            f"{type(current).__name__}: {message}"
            if message
            else type(current).__name__
        )
        if detail not in parts:
            parts.append(detail)
        current = current.__cause__
    return " -> ".join(parts)


def _extract_json_object(text: str) -> Any:
    """Deterministically extract one JSON object from a model response.

    Small local models occasionally wrap structured output in markdown fences
    or append short commentary even with ``format`` enabled. The extraction is
    strictly syntactic: the parsed object must still pass the schema-constrained
    patch validation and every allowlist afterwards.
    """

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z0-9_+-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            pass

    start = stripped.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(stripped)):
            character = stripped[index]
            if in_string:
                if escape:
                    escape = False
                elif character == "\\":
                    escape = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : index + 1])
                    except (json.JSONDecodeError, TypeError):
                        break

    raise ValueError("no JSON object found")


def _resolve_base_url(ollama_service: Any) -> str:
    wrapped = getattr(ollama_service, "wrapped_service", ollama_service)
    configuration = getattr(wrapped, "configuration", None)
    configured = getattr(configuration, "base_url", None)
    raw = os.environ.get("OLLAMA_HOST") or configured or DEFAULT_OLLAMA_URL
    base_url = str(raw).strip().rstrip("/")
    if "://" not in base_url:
        base_url = f"http://{base_url}"
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AIPatchGenerationError("The configured Ollama address is invalid.")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AIPatchGenerationError(
            "AI patch generation only permits the local Ollama service."
        )
    return base_url


def _resolve_model(ollama_service: Any) -> str:
    model = getattr(ollama_service, "model", None)
    return str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _check_cancel(cancellation_token: Any) -> None:
    if cancellation_token is None:
        return
    raiser = getattr(cancellation_token, "raise_if_cancelled", None)
    if callable(raiser):
        raiser()


def _request_structured_patch(
    *,
    ollama_service: Any,
    prompt: str,
    timeout_seconds: float,
    cancellation_token: Any,
) -> dict[str, Any]:
    _check_cancel(cancellation_token)
    payload = {
        "model": _resolve_model(ollama_service),
        "prompt": prompt,
        "stream": False,
        "format": _schema(),
        "options": {"temperature": 0, "num_predict": 4096},
        "keep_alive": "5m",
    }
    request = urllib.request.Request(
        f"{_resolve_base_url(ollama_service)}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout_seconds))) as response:
            body = response.read(MAX_RESPONSE_CHARACTERS + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4000).decode("utf-8", errors="replace")
        raise AIPatchGenerationError(
            f"Ollama rejected patch generation with HTTP {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIPatchGenerationError(f"Ollama patch generation failed: {exc}") from exc

    _check_cancel(cancellation_token)
    if len(body) > MAX_RESPONSE_CHARACTERS:
        raise AIPatchGenerationError("Ollama patch response exceeded the safe size limit.")
    try:
        envelope = json.loads(body.decode("utf-8"))
        generated = envelope["response"]
        result = _extract_json_object(generated)
    except (UnicodeDecodeError, KeyError, TypeError) as exc:
        raise AIPatchGenerationError("Ollama returned an invalid structured patch response.") from exc
    except ValueError as exc:
        raise AIPatchGenerationError("Ollama returned an invalid structured patch response.") from exc
    if not isinstance(result, dict):
        raise AIPatchGenerationError("Ollama patch response must be a JSON object.")
    return result


def _check_patch_operation_conflicts(
    operation: str,
    path: str,
    *,
    destination: str | None,
    seen_paths: dict[str, str],
    seen_destinations: set[str],
) -> None:
    """Reject duplicate or contradictory operations on the same path.

    Mirrors PatchService.normalize_operations: every path may be claimed at
    most once, rename destinations may not collide with another patch target,
    and two renames cannot share a destination. Catching this at generation
    time yields precise repair feedback instead of a generic dry-run failure.
    """

    if path in seen_paths:
        raise AIPatchGenerationError(
            f"AI patch contains conflicting operations for path {path!r}: "
            f"{seen_paths[path]} and {operation}."
        )
    seen_paths[path] = operation

    if operation == "rename" and destination is not None:
        if destination in seen_paths:
            raise AIPatchGenerationError(
                f"AI patch rename destination {destination!r} is also a "
                "patch target; refusing ambiguous rename."
            )
        if destination in seen_destinations:
            raise AIPatchGenerationError(
                f"AI patch contains two renames to the same destination "
                f"{destination!r}."
            )
        seen_destinations.add(destination)


def _to_patch_request(
    data: Mapping[str, Any],
    *,
    allowed_paths: frozenset[str],
    root: Path,
    hashes: Mapping[str, str],
    allow_file_creation: bool,
    allow_file_deletion: bool = False,
    plan_operations: _PlanOperations | None = None,
) -> PatchRequestPayload:
    plan_operations = plan_operations or _PlanOperations()
    raw_operations = data.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        raise AIPatchGenerationError("AI returned no patch operations.")
    if len(raw_operations) > MAX_OPERATIONS:
        raise AIPatchGenerationError("AI returned too many patch operations.")

    operations: list[ProposedPatchOperation] = []
    seen_paths: dict[str, str] = {}
    seen_destinations: set[str] = set()
    for raw in raw_operations:
        if not isinstance(raw, Mapping):
            raise AIPatchGenerationError("AI returned a malformed patch operation.")
        raw_operation = raw.get("operation")
        raw_path = raw.get("path")
        path = _coerce_repository_relative_path(raw_path, root)
        if path is None and isinstance(raw_path, str) and raw_path.startswith("/"):
            approved_root_relative = _normalize_relative_path(raw_path.lstrip("/"))
            if approved_root_relative in allowed_paths:
                path = approved_root_relative
        if path is None:
            raise AIPatchGenerationError(
                f"AI returned an unsupported or unsafe patch path {raw_path!r} "
                f"for operation {raw_operation!r}."
            )
        absolute_path = _safe_repository_path(root, path)
        operation = _canonicalize_operation(
            raw_operation,
            path_exists=absolute_path.exists(),
        )
        if operation not in ALLOWED_OPERATIONS:
            raise AIPatchGenerationError(
                f"AI returned unsupported patch operation {raw_operation!r} "
                f"for approved path {path!r}. Allowed operations are: "
                + ", ".join(sorted(ALLOWED_OPERATIONS))
            )
        if path not in allowed_paths:
            raise AIPatchGenerationError(
                f"AI attempted to change a file outside the approved plan: {path}"
            )

        destination: str | None = None
        if operation == "rename":
            raw_destination = raw.get("destination_path") or raw.get("new_path")
            destination = _coerce_repository_relative_path(
                raw_destination,
                root,
            )
            if destination is None:
                raise AIPatchGenerationError(
                    f"AI returned an unsupported or unsafe rename destination "
                    f"{raw_destination!r} for operation {raw_operation!r}."
                )
            planned_destination = plan_operations.rename_destinations.get(path)
            if planned_destination is None:
                raise AIPatchGenerationError(
                    f"AI attempted to rename a file not marked for rename in "
                    f"the approved plan: {path}"
                )
            if destination != planned_destination:
                raise AIPatchGenerationError(
                    f"AI rename destination {destination!r} does not match "
                    f"the approved plan destination {planned_destination!r} "
                    f"for {path}."
                )
            if not absolute_path.is_file():
                raise AIPatchGenerationError(
                    f"AI tried to rename a missing file: {path}"
                )
            destination_path = _safe_repository_path(root, destination)
            if destination_path.exists():
                raise AIPatchGenerationError(
                    f"AI rename destination already exists: {destination}"
                )
            _check_patch_operation_conflicts(
                operation,
                path,
                destination=destination,
                seen_paths=seen_paths,
                seen_destinations=seen_destinations,
            )
            operations.append(
                ProposedPatchOperation(
                    operation="rename",
                    path=path,
                    destination_path=destination,
                    description=raw.get("description"),
                )
            )
            continue

        if operation == "delete":
            if path not in plan_operations.delete_paths:
                raise AIPatchGenerationError(
                    f"AI attempted to delete a file not marked for deletion in "
                    f"the approved plan: {path}"
                )
            if not allow_file_deletion:
                raise AIPatchGenerationError(
                    "This task does not allow deleting files."
                )
            if not absolute_path.is_file():
                raise AIPatchGenerationError(
                    f"AI tried to delete a missing file: {path}"
                )
            _check_patch_operation_conflicts(
                operation,
                path,
                destination=None,
                seen_paths=seen_paths,
                seen_destinations=seen_destinations,
            )
            operations.append(
                ProposedPatchOperation(
                    operation="delete",
                    path=path,
                    description=raw.get("description"),
                )
            )
            continue

        _check_patch_operation_conflicts(
            operation,
            path,
            destination=None,
            seen_paths=seen_paths,
            seen_destinations=seen_destinations,
        )

        if operation == "create":
            if not allow_file_creation:
                raise AIPatchGenerationError("This task does not allow creating files.")
            if absolute_path.exists():
                raise AIPatchGenerationError(f"AI tried to create an existing file: {path}")
            content = raw.get("content")
            if not isinstance(content, str):
                raise AIPatchGenerationError(f"Create operation is missing content: {path}")
            operations.append(
                ProposedPatchOperation(operation="create", path=path, content=content, description=raw.get("description"))
            )
            continue

        if not absolute_path.is_file():
            raise AIPatchGenerationError(f"AI tried to edit a missing file: {path}")
        expected_hash = hashes.get(path)
        if expected_hash is None:
            expected_hash = hashlib.sha256(absolute_path.read_bytes()).hexdigest()

        if operation == "replace_file":
            content = raw.get("content")
            if not isinstance(content, str):
                raise AIPatchGenerationError(f"replace_file is missing content: {path}")
            operations.append(
                ProposedPatchOperation(
                    operation="replace_file",
                    path=path,
                    content=content,
                    expected_sha256=expected_hash,
                    description=raw.get("description"),
                )
            )
        elif operation == "replace_text":
            search_text = raw.get("search_text")
            replacement_text = raw.get("replacement_text")
            if not isinstance(search_text, str) or not search_text:
                raise AIPatchGenerationError(f"replace_text is missing search_text: {path}")
            if not isinstance(replacement_text, str):
                raise AIPatchGenerationError(f"replace_text is missing replacement_text: {path}")
            # PatchService counts search occurrences against the raw file
            # bytes (no universal-newline translation). Models emit LF text
            # even when the file uses CRLF, so normalize both sides to LF
            # for matching and then map the proposed text back to the file's
            # own line endings before the deterministic engine validates it.
            raw_source_bytes = absolute_path.read_bytes()
            try:
                raw_source_text = raw_source_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise AIPatchGenerationError(
                    f"AI search target is not valid UTF-8 text: {path}"
                )
            crlf_file = "\r\n" in raw_source_text
            source_text = _lf_normalized(raw_source_text)
            occurrences = source_text.count(
                _lf_normalized(search_text)
            )
            if occurrences < 1:
                raise AIPatchGenerationError(
                    f"AI search text was not found in {path}"
                )
            operations.append(
                ProposedPatchOperation(
                    operation="replace_text",
                    path=path,
                    search_text=_file_style_text(
                        search_text,
                        crlf_file=crlf_file,
                    ),
                    replacement_text=_file_style_text(
                        replacement_text,
                        crlf_file=crlf_file,
                    ),
                    expected_occurrences=occurrences,
                    expected_sha256=expected_hash,
                    description=raw.get("description"),
                )
            )
        else:
            unified_diff = raw.get("unified_diff")
            if not isinstance(unified_diff, str) or not unified_diff.strip():
                raise AIPatchGenerationError(f"unified_diff is missing diff text: {path}")
            operations.append(
                ProposedPatchOperation(
                    operation="unified_diff",
                    path=path,
                    unified_diff=unified_diff,
                    expected_sha256=expected_hash,
                    description=raw.get("description"),
                )
            )

    return PatchRequestPayload(
        operations=operations,
        rollback_on_failure=True,
        description=(str(data.get("description")) if data.get("description") is not None else "AI-generated patch from approved LUMINA plan"),
    )


def generate_patch(
    self: PatchService,
    task: Any = None,
    analysis: Any = None,
    plan: Any = None,
    ollama_service: Any = None,
    repository_root: Any = None,
    timeout_seconds: float = 300.0,
    cancellation_token: Any = None,
    instruction: str | None = None,
    target_paths: Sequence[str] | None = None,
    allow_file_creation: bool | None = None,
    allow_file_deletion: bool | None = None,
    model_service: Any = None,
    request: Any = None,
    implementation_plan: Any = None,
    analysis_result: Any = None,
    **_: Any,
) -> PatchRequestPayload:
    """Generate, constrain, and dry-run one patch for an approved plan."""

    task = task or request
    plan = plan or implementation_plan
    analysis = analysis or analysis_result
    ollama_service = ollama_service or model_service
    if ollama_service is None:
        raise AIPatchGenerationError("No local AI model service is available for patch generation.")

    if instruction is None and task is not None:
        instruction = getattr(task, "instruction", None)
    instruction = str(instruction or "").strip()
    if not instruction:
        raise AIPatchGenerationError("Patch generation requires a user instruction.")

    root_value = repository_root or getattr(self, "repository_root", None) or getattr(self, "_repository_root", None)
    if root_value is None:
        configuration = getattr(self, "configuration", None)
        root_value = getattr(configuration, "repository_root", None)
    root = Path(root_value).resolve() if root_value is not None else None
    if root is None or not root.is_dir():
        raise AIPatchGenerationError("Patch generation could not resolve the repository root.")

    approved_paths = list(_collect_plan_paths(plan))
    for value in target_paths or _task_paths(task):
        normalized = _normalize_relative_path(value)
        if normalized and normalized not in approved_paths:
            approved_paths.append(normalized)
    if not approved_paths:
        raise AIPatchGenerationError(
            "The approved implementation plan contains no explicit file paths; refusing unconstrained AI edits."
        )

    allowed_paths = frozenset(approved_paths)
    plan_operations = _collect_plan_operations(plan)
    required_paths = _collect_required_plan_paths(plan)
    file_context, hashes = _build_file_context(root, approved_paths)
    creation_allowed = bool(
        allow_file_creation
        if allow_file_creation is not None
        else getattr(task, "allow_file_creation", True)
    )
    deletion_allowed = bool(
        allow_file_deletion
        if allow_file_deletion is not None
        else getattr(task, "allow_file_deletion", False)
    )

    operation_guidance = (
        "Use ONLY these operations: create, replace_file, replace_text, "
        "unified_diff, delete, rename.\n"
        "Use delete ONLY for a file the approved plan marks for deletion.\n"
        "Use rename ONLY for a file the approved plan marks for rename, and "
        "set destination_path to the approved destination exactly.\n"
    )
    if not deletion_allowed:
        operation_guidance += "This task does not allow deleting files; never emit delete.\n"

    prompt = (
        "You are the code-change generator for LUMINA Code Builder.\n"
        "Return ONLY the JSON object required by the supplied JSON Schema.\n"
        "You are proposing changes, not writing files.\n"
        + operation_guidance
        + "Change ONLY files in APPROVED PATHS. Never invent another path.\n"
        "You MUST include at least one patch operation for EVERY REQUIRED PATH.\n"
        "Prefer replace_text for small precise edits and replace_file only when necessary.\n"
        "For replace_text, copy search_text EXACTLY from CURRENT FILE CONTENT.\n"
        "Do not use markdown fences. Do not include commentary outside JSON.\n\n"
        f"USER INSTRUCTION:\n{instruction}\n\n"
        f"APPROVED PATHS:\n" + "\n".join(f"- {path}" for path in approved_paths) + "\n\n"
        "REQUIRED PATHS (all must be covered):\n" + ("\n".join(f"- {path}" for path in required_paths) or "- none") + "\n\n"
        f"APPROVED PLAN:\n{json.dumps(_dump(plan), ensure_ascii=False, default=str)[:60_000]}\n\n"
        f"REPOSITORY ANALYSIS SUMMARY:\n{json.dumps(_dump(analysis), ensure_ascii=False, default=str)[:30_000]}\n\n"
        f"CURRENT FILE CONTENT:\n{file_context}\n"
    )

    _check_cancel(cancellation_token)
    first = _request_structured_patch(
        ollama_service=ollama_service,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        cancellation_token=cancellation_token,
    )

    validation_error: str | None = None
    patch: PatchRequestPayload | None = None
    try:
        patch = _to_patch_request(
            first,
            allowed_paths=allowed_paths,
            root=root,
            hashes=hashes,
            allow_file_creation=creation_allowed,
            allow_file_deletion=deletion_allowed,
            plan_operations=plan_operations,
        )
        _ensure_required_plan_coverage(patch, required_paths)
        validation = self.apply_patch(patch, dry_run=True)
        if validation.successful:
            return patch
        validation_error = validation.error or "Unknown validation failure"
    except AIPatchGenerationError as exc:
        # A structurally invalid first response consumes the same single
        # bounded repair attempt as a dry-run validation failure.
        validation_error = str(exc)
    except PatchServiceError as exc:
        # PatchService dry-runs by raising on invalid operations instead of
        # returning a failed result. Route those deterministic rejections
        # into the same single bounded repair attempt so real-model output
        # is repaired instead of escaping the loop.
        validation_error = _error_chain_detail(exc)

    # One bounded repair attempt. The model receives the deterministic
    # rejection reason but still cannot write or expand its approved path
    # scope.
    repair_prompt = (
        prompt
        + "\n\nYOUR PREVIOUS PATCH FAILED THE DETERMINISTIC DRY-RUN VALIDATOR.\n"
        + f"VALIDATION ERROR:\n{validation_error}\n"
        + "Return one corrected JSON patch. Do not expand the approved paths."
    )
    repaired = _request_structured_patch(
        ollama_service=ollama_service,
        prompt=repair_prompt,
        timeout_seconds=timeout_seconds,
        cancellation_token=cancellation_token,
    )
    patch = _to_patch_request(
        repaired,
        allowed_paths=allowed_paths,
        root=root,
        hashes=hashes,
        allow_file_creation=creation_allowed,
        allow_file_deletion=deletion_allowed,
        plan_operations=plan_operations,
    )
    _ensure_required_plan_coverage(patch, required_paths)
    try:
        validation = self.apply_patch(patch, dry_run=True)
        repair_failed = not validation.successful
        repair_error = (
            validation.error
            if not validation.successful
            else None
        )
    except PatchServiceError as exc:
        repair_failed = True
        repair_error = _error_chain_detail(exc)
    if repair_failed:
        raise AIPatchGenerationError(
            "AI patch failed deterministic dry-run validation after one "
            f"repair attempt: {repair_error}"
        )
    return patch


def install_ai_patch_generation() -> None:
    """Install the generator as the PatchService generation hook.

    TaskService already looks for ``generate_patch`` on PatchService. Keeping
    deterministic application in PatchService and generation here makes this a
    narrow compatibility bridge while preserving the existing task pipeline.
    """

    if getattr(PatchService, "_lumina_ai_patch_generation_installed", False):
        return
    setattr(PatchService, "generate_patch", generate_patch)
    setattr(PatchService, "_lumina_ai_patch_generation_installed", True)


__all__ = [
    "AIPatchGenerationError",
    "generate_patch",
    "install_ai_patch_generation",
]
