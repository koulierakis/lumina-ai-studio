# LUMINA OpenHands Integration Status

Implemented on the completion branch:

1. LUMINA prepares a lean disposable copy of the repository, excluding runtime/build/log/temp/coverage/virtual-environment folders and dotenv secrets.
2. Empty instructions are rejected before copy creation.
3. OpenHands autonomous work is permitted only inside the disposable copy.
4. The real repository remains untouched during AI execution.
5. Before/after file states are compared.
6. Created, modified, and deleted files return as reviewable diffs plus simple change counts; oversized diffs are shortened and excessively large change sets are rejected.
7. Temporary work is cleaned up after execution.
8. OpenHands availability and safe-mode status are reportable without a hard dependency.
9. Native Code Builder remains the default and is explicitly preserved; OpenHands is experimental and migration is parallel.
10. Approval is mandatory; any future apply path must preserve both backup and rollback capability.
11. Engine status explicitly reports OpenHands as not runtime-validated and not ready until a real runtime test succeeds.
12. OpenHands proposals are converted into the same approved patch metadata keys already consumed by the existing TaskService.
13. A shared `CodeBuilderEnginePreparationService` now selects Native or OpenHands for proposal preparation while leaving approval, backup, apply, build validation, persistence, and rollback under the existing LUMINA task lifecycle.

## Next integration boundary

Wire `CodeBuilderEnginePreparationService` into the router's preparation step and add the engine selection field to the existing Code Builder API/UI. Native must remain the default. OpenHands must remain review-only until runtime validation succeeds.

## Validation status

Isolated tests exist for the safety boundary, OpenHands proposal conversion, and the shared Native/OpenHands preparation bridge. The GitHub connector cannot execute repository tests. A real OpenHands task also requires OpenHands plus a configured model.

Current checkpoint: the engine-selection preparation bridge is implemented in code. It is NOT yet marked READY because automated tests and a real OpenHands runtime task have not yet been executed in the target runtime.
