# LUMINA OpenHands Integration Status

Current experimental path:

1. LUMINA receives an instruction.
2. `OpenHandsWorkspaceService` creates a disposable copy of the repository.
3. `OpenHandsAdapter` permits autonomous execution only in that disposable copy.
4. `OpenHandsExecutionService` snapshots the copy before and after execution.
5. It returns a reviewable list of created, modified, and deleted files with unified text diffs.
6. The disposable copy is removed after execution.
7. The real repository is not modified by this path.
8. `OpenHandsEngine` provides a small optional engine boundary and availability status.
9. `CodingEngineRegistry` keeps the current native engine available while advertising OpenHands only when it is actually installed.
10. The registry now produces a small UI-ready status payload so the existing Code Builder can later show Native/OpenHands availability without changing the current default.

## Next integration boundary

Wire the engine registry into the existing Code Builder API/task lifecycle, then expose the selection in the existing UI. Preserve approval, backup, persistence, apply, rollback, and current native behavior.

## Validation status

Static implementation and isolated tests exist. A real OpenHands runtime test still requires an environment where OpenHands is installed/configured and a suitable model is available. Do not mark the OpenHands engine READY until that real runtime test passes.
