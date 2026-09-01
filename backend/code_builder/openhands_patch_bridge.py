"""Convert approved OpenHands proposals into the existing LUMINA PatchService format."""
from __future__ import annotations

from .openhands_execution_service import OpenHandsExecutionResult
from .patch_service import PatchRequestPayload, ProposedPatchOperation


class OpenHandsPatchBridgeError(RuntimeError):
    """Raised when an OpenHands proposal cannot be converted safely."""


def build_patch_request_from_openhands(
    result: OpenHandsExecutionResult,
    *,
    dry_run: bool,
) -> PatchRequestPayload:
    if not result.run.successful:
        raise OpenHandsPatchBridgeError(
            "OpenHands did not finish successfully, so its changes cannot be prepared for approval."
        )
    if not result.changes:
        raise OpenHandsPatchBridgeError(
            "OpenHands produced no file changes to approve."
        )

    operations: list[ProposedPatchOperation] = []

    for change in result.changes:
        if change.change_type == "created":
            if change.content is None:
                raise OpenHandsPatchBridgeError(
                    f"Created file {change.path!r} is not UTF-8 text and cannot be applied safely."
                )
            operations.append(
                ProposedPatchOperation(
                    operation="create",
                    path=change.path,
                    content=change.content,
                    description="OpenHands proposed file creation.",
                )
            )
            continue

        if change.change_type == "deleted":
            if change.expected_sha256 is None:
                raise OpenHandsPatchBridgeError(
                    f"Deleted file {change.path!r} is missing its original content hash."
                )
            operations.append(
                ProposedPatchOperation(
                    operation="delete",
                    path=change.path,
                    expected_sha256=change.expected_sha256,
                    description="OpenHands proposed file deletion.",
                )
            )
            continue

        if change.change_type == "modified":
            if change.diff == "[binary file changed]":
                raise OpenHandsPatchBridgeError(
                    f"Modified file {change.path!r} is binary and cannot be applied through the safe text patch path."
                )
            if change.expected_sha256 is None:
                raise OpenHandsPatchBridgeError(
                    f"Modified file {change.path!r} is missing its original content hash."
                )
            operations.append(
                ProposedPatchOperation(
                    operation="unified_diff",
                    path=change.path,
                    unified_diff=change.diff,
                    expected_sha256=change.expected_sha256,
                    description="OpenHands proposed text modification.",
                )
            )
            continue

        raise OpenHandsPatchBridgeError(
            f"Unsupported OpenHands change type: {change.change_type!r}."
        )

    return PatchRequestPayload(
        operations=operations,
        dry_run=dry_run,
        rollback_on_failure=True,
        description="Approved OpenHands proposal converted for LUMINA PatchService.",
    )
