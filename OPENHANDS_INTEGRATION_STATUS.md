# LUMINA OpenHands Integration Status

Current experimental path:

1. LUMINA receives an instruction.
2. `OpenHandsWorkspaceService` creates a disposable copy of the repository.
3. `OpenHandsAdapter` permits autonomous execution only in that disposable copy.
4. `OpenHandsExecutionService` snapshots the copy before and after execution.
5. It returns a reviewable list of created, modified, and deleted files with unified text diffs.
6. The disposable copy is removed after execution.
7. The real repository is not modified by this path.

## Next integration boundary

Wire `OpenHandsExecutionService` into the existing Code Builder task lifecycle as an optional engine, preserving the current approval, backup, persistence, apply, rollback, and UI layers.

## Validation status

Static implementation and isolated tests exist. A real OpenHands runtime test still requires an environment where OpenHands is installed/configured and a suitable model is available. Do not mark the OpenHands engine READY until that real runtime test passes.
