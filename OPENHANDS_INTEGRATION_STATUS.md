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
10. Approval is mandatory for OpenHands proposals and a backup is required before any future apply path.
11. Engine status explicitly reports `openhands_runtime_validated: false` and `openhands_ready: false` until real runtime proof exists.
12. OpenHands proposals report `awaiting_approval`, `review_only: true`, `applied: false`, `can_apply: false`, `source_repository_unchanged: true`, and `next_action: review_changes`.

## Next integration boundary

Connect this controlled path to the existing Code Builder API/task lifecycle and UI while preserving approval, backup, persistence, apply, rollback, and native behavior.

## Validation status

Isolated tests exist for the new safety and routing behavior but have not been executed by the GitHub connector. A real OpenHands task also requires OpenHands plus a configured model.

Current checkpoint: the first safe OpenHands proposal path is implemented in code and stops before application. It is NOT yet marked READY because runtime proof is still required.
