# LUMINA OpenHands Integration Status

Implemented on the completion branch:

1. LUMINA prepares a lean disposable copy of the repository, excluding runtime/build/log/temp/coverage/virtual-environment folders and dotenv secrets.
2. Empty instructions are rejected before copy creation.
3. OpenHands autonomous work is permitted only inside the disposable copy.
4. The real repository remains untouched during AI execution.
5. Before/after file states are compared.
6. Created, modified, and deleted files return as reviewable diffs plus simple change counts; oversized diffs are shortened and excessively large change sets are rejected.
7. For safe future approval/apply, OpenHands changes now also retain the minimum data needed to recreate them through the existing LUMINA PatchService: created-file text, original-file hashes, and unified diffs.
8. A dedicated `openhands_patch_bridge.py` converts approved OpenHands proposals into the existing LUMINA patch-operation format. Binary modifications, failed OpenHands runs, empty proposals, and missing safety hashes are rejected.
9. Temporary work is cleaned up after execution.
10. OpenHands availability and safe-mode status are reportable without a hard dependency.
11. Native Code Builder remains the default and is explicitly preserved; OpenHands is experimental and migration is parallel.
12. Approval is mandatory; any future apply path must preserve both backup and rollback capability.
13. Engine status explicitly reports OpenHands as not runtime-validated and not ready.
14. OpenHands proposals report `awaiting_approval`, `review_only: true`, `applied: false`, `can_apply: false`, `source_repository_unchanged: true`, and `next_action: review_changes`.

## Next integration boundary

Connect the OpenHands proposal and patch bridge to the existing Code Builder API/task lifecycle. The preparation result must be stored for review; only after explicit approval should LUMINA feed the converted operations into its existing backup / PatchService / build / rollback path.

## Validation status

Isolated tests exist for sandbox isolation, secret exclusion, cleanup, proposal capture, engine selection, safe-mode status, review summaries, approval gates, and OpenHands-to-PatchService conversion. These tests have not been executed by the GitHub connector. A real OpenHands task also requires OpenHands plus a configured model.

Current checkpoint: OpenHands can work in isolation, return a reviewable proposal, and that proposal can be converted into the same patch format already used by LUMINA. The integration is still NOT marked READY because the API/task wiring and real runtime proof are still required.
