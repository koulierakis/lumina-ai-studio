# LUMINA OpenHands Integration Status

Implemented on the completion branch:

1. LUMINA prepares a disposable copy of the repository.
2. Empty instructions are rejected before copy creation.
3. Runtime folders and dotenv secret files are excluded.
4. OpenHands autonomous work is permitted only inside the disposable copy.
5. The real repository remains untouched during AI execution.
6. Before/after file states are compared.
7. Created, modified, and deleted files return as reviewable diffs; oversized diffs are shortened.
8. Temporary work is cleaned up after execution.
9. OpenHands availability and safe-mode status are reportable without a hard dependency.
10. Native Code Builder remains the default.
11. OpenHands is an experimental second engine only when available.
12. The controlled engine entry point returns review-ready changes.
13. OpenHands results are explicitly marked as safe-mode, approval-required, and not applied.

## Next integration boundary

Connect this controlled path to the existing Code Builder API/task lifecycle and UI while preserving approval, backup, persistence, apply, rollback, and native behavior.

## Validation status

Isolated tests exist for sandbox isolation, secret exclusion, cleanup, engine selection, safe-mode status, review summaries, approval marking, unapplied proposals, empty tasks, and oversized diffs. The GitHub connector cannot execute repository tests. A real OpenHands task also requires OpenHands plus a configured model.

Current checkpoint: the first safe OpenHands proposal path is implemented in code. It is NOT yet marked READY because runtime proof is still required.
