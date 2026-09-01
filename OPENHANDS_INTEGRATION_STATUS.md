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
11. OpenHands proposals are converted into the same approved patch metadata keys already consumed by the existing TaskService.
12. A shared `CodeBuilderEnginePreparationService` selects Native or OpenHands for proposal preparation while leaving approval, backup, apply, build validation, persistence, and rollback under the existing LUMINA task lifecycle.
13. A minimal `router_engine_bridge.py` now contains the exact small hooks needed by `router.py`: read the requested engine from task metadata, route only the preparation stage, and attach approved operations back to the existing execution request.
14. Native remains the default when no engine is supplied, so existing Code Builder behavior is preserved.

## Next integration boundary

Apply these small bridge calls inside `router.py` and expose `coding_engine` through the existing API/UI. Keep OpenHands review-only until runtime validation succeeds.

## Validation status

Isolated tests exist for the safety boundary, OpenHands proposal conversion, shared preparation service, and minimal router bridge. The GitHub connector cannot execute repository tests. A real OpenHands task also requires OpenHands plus a configured model.

Current checkpoint: the router integration has been reduced to a small, testable change rather than a rewrite of the existing Code Builder lifecycle. It is NOT yet marked READY because the actual `router.py` wiring and real runtime proof still remain.
