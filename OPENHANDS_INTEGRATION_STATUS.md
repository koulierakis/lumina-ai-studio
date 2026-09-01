# LUMINA OpenHands Integration Status

Implemented on the completion branch:

1. LUMINA can prepare a disposable copy of the repository.
2. Empty instructions are rejected before copy creation.
3. OpenHands autonomous work is permitted only inside that copy.
4. The real repository remains untouched during AI execution.
5. Before/after file states are compared.
6. Created, modified, and deleted files are returned with reviewable diffs.
7. Temporary work is cleaned up after execution.
8. OpenHands availability can be checked without making it a hard LUMINA dependency.
9. Native Code Builder remains the safe default.
10. OpenHands is exposed as an experimental second engine only when available.
11. A controlled engine entry point returns a review-ready change summary for later approval UI integration.

## Next integration boundary

Connect the engine registry to the existing Code Builder API/task lifecycle and UI while preserving approval, backup, persistence, apply, rollback, and all current native behavior.

## Validation status

Isolated tests have been added for the new safety and routing pieces. They have not been executed by the GitHub connector itself. A real OpenHands runtime test also still requires an environment where OpenHands is installed/configured and a suitable model is available. Do not mark OpenHands READY until both automated tests and a real runtime task pass.
