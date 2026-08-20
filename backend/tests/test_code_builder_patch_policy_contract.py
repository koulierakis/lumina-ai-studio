from __future__ import annotations

import pytest

from code_builder.task_service import (
    TaskCancellationToken,
    TaskExecutionContext,
    TaskPatchError,
    TaskRequest,
    TaskServiceConfiguration,
    _build_patch_request_from_metadata,
)


def _context(tmp_path, *, operations, allow_create=True, allow_delete=False, excluded=()):
    request = TaskRequest(
        instruction="policy contract",
        allow_file_creation=allow_create,
        allow_file_deletion=allow_delete,
        excluded_paths=tuple(excluded),
        metadata={"patch_operations": operations},
    )
    context = TaskExecutionContext(
        request=request,
        configuration=TaskServiceConfiguration(
            repository_root=tmp_path,
            use_default_build_sequence=False,
        ),
        cancellation_token=TaskCancellationToken(task_id=request.task_id),
    )
    context.plan = {
        "files": [
            {"path": operation["path"]}
            for operation in operations
        ]
    }
    return context


def test_metadata_patch_cannot_delete_when_task_forbids_deletion(tmp_path) -> None:
    target = tmp_path / "keep.txt"
    target.write_text("keep", encoding="utf-8")
    context = _context(
        tmp_path,
        operations=[{"operation": "delete", "path": "keep.txt"}],
        allow_delete=False,
    )

    with pytest.raises(TaskPatchError, match="does not permit deleting files"):
        _build_patch_request_from_metadata(context)


def test_metadata_patch_cannot_create_when_task_forbids_creation(tmp_path) -> None:
    context = _context(
        tmp_path,
        operations=[{"operation": "create", "path": "new.txt", "content": "x"}],
        allow_create=False,
    )

    with pytest.raises(TaskPatchError, match="does not permit creating files"):
        _build_patch_request_from_metadata(context)


def test_metadata_patch_cannot_touch_excluded_path(tmp_path) -> None:
    (tmp_path / "protected").mkdir()
    context = _context(
        tmp_path,
        operations=[{"operation": "create", "path": "protected/new.txt", "content": "x"}],
        excluded=("protected",),
    )

    with pytest.raises(TaskPatchError, match="excluded path"):
        _build_patch_request_from_metadata(context)


def test_allowed_metadata_create_is_preserved(tmp_path) -> None:
    context = _context(
        tmp_path,
        operations=[{"operation": "create", "path": "new.txt", "content": "x"}],
        allow_create=True,
    )

    payload = _build_patch_request_from_metadata(context)
    assert payload is not None
    assert payload.operations[0].path == "new.txt"
