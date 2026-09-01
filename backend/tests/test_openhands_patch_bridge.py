import hashlib

import pytest

from code_builder.openhands_adapter import OpenHandsRunResult
from code_builder.openhands_execution_service import OpenHandsExecutionResult, OpenHandsFileChange
from code_builder.openhands_patch_bridge import (
    OpenHandsPatchBridgeError,
    build_patch_request_from_openhands,
)


def successful_run():
    return OpenHandsRunResult(("openhands",), 0, (), "", "")


def test_bridge_converts_create_modify_delete_to_existing_patch_format():
    original = b"old\n"
    result = OpenHandsExecutionResult(
        run=successful_run(),
        changes=(
            OpenHandsFileChange(
                path="new.txt",
                change_type="created",
                diff="--- a/new.txt\n+++ b/new.txt\n",
                content="new\n",
            ),
            OpenHandsFileChange(
                path="edit.txt",
                change_type="modified",
                diff="--- a/edit.txt\n+++ b/edit.txt\n@@ -1 +1 @@\n-old\n+new\n",
                expected_sha256=hashlib.sha256(original).hexdigest(),
            ),
            OpenHandsFileChange(
                path="delete.txt",
                change_type="deleted",
                diff="--- a/delete.txt\n+++ b/delete.txt\n",
                expected_sha256=hashlib.sha256(b"delete me\n").hexdigest(),
            ),
        ),
    )

    request = build_patch_request_from_openhands(result, dry_run=True)

    assert request.dry_run is True
    assert request.rollback_on_failure is True
    assert [operation.operation for operation in request.operations] == [
        "create",
        "unified_diff",
        "delete",
    ]
    assert request.operations[0].content == "new\n"
    assert request.operations[1].expected_sha256 == hashlib.sha256(original).hexdigest()


def test_bridge_rejects_binary_modified_file():
    result = OpenHandsExecutionResult(
        run=successful_run(),
        changes=(
            OpenHandsFileChange(
                path="image.bin",
                change_type="modified",
                diff="[binary file changed]",
                expected_sha256="a" * 64,
            ),
        ),
    )

    with pytest.raises(OpenHandsPatchBridgeError, match="binary"):
        build_patch_request_from_openhands(result, dry_run=False)


def test_bridge_rejects_unsuccessful_or_empty_proposal():
    failed = OpenHandsExecutionResult(
        run=OpenHandsRunResult(("openhands",), 1, (), "", "failed"),
        changes=(),
    )
    with pytest.raises(OpenHandsPatchBridgeError, match="did not finish successfully"):
        build_patch_request_from_openhands(failed, dry_run=False)

    empty = OpenHandsExecutionResult(run=successful_run(), changes=())
    with pytest.raises(OpenHandsPatchBridgeError, match="no file changes"):
        build_patch_request_from_openhands(empty, dry_run=False)
