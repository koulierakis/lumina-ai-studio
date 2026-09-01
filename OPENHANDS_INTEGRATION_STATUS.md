# LUMINA OpenHands Integration Status

Current experimental path:

1. LUMINA receives an instruction.
2. Empty instructions are rejected before any temporary copy is created.
3. `OpenHandsWorkspaceService` creates a disposable copy of the repository.
4. `OpenHandsAdapter` permits autonomous execution only in that disposable copy.
5. `OpenHandsExecutionService` snapshots the copy before and after execution.
6. It returns a reviewable list of created, modified, and deleted files with unified text diffs.
7. The disposable copy is removed after execution.
8. The real repository is not modified by this path.
9. `OpenHandsEngine` provides a small optional engine boundary and availability status.
10. `CodingEngineRegistry` keeps the current native engine available while advertising OpenHands only when it is actually installed.
11. The registry produces a UI-ready status payload and defaults missing engine selections to Native, protecting existing Code Builder behavior during migration.
12. OpenHands execution is routed through one controlled registry entry point. Native execution deliberately remains owned by the existing Code Builder task service and is not replaced.
13. OpenHands results include a review-ready summary of changed files and diffs, and the registry can return that summary directly for the existing LUMINA approval flow.

## Next integration boundary

Wire this controlled entry point into the existing Code Builder API/task lifecycle, then expose the selection and returned change summary in the existing UI. Preserve approval, backup, persistence, apply, rollback, and current native behavior.

## Validation status

Static implementation and isolated tests exist. A real OpenHands runtime test still requires an environment where OpenHands is installed/configured and a suitable model is available. Do not mark the OpenHands engine READY until that real runtime test passes.
