# LUMINA OpenHands Integration Status

Implemented on the completion branch:

1. LUMINA prepares a lean disposable copy of the repository, excluding runtime/build/log/temp/coverage/virtual-environment folders and dotenv secrets.
2. Empty instructions are rejected before copy creation.
3. OpenHands autonomous work is permitted only inside the disposable copy.
4. The real repository remains untouched during AI execution.
5. Before/after file states are compared.
6. Created, modified, and deleted files return as reviewable diffs plus simple change counts; oversized diffs are shortened and excessively large change sets are rejected.
7. OpenHands changes are converted into the same patch-operation format already understood by the existing LUMINA PatchService.
8. Native Code Builder remains the default and is explicitly preserved.
9. `task_engine_integration.py` now intercepts only pre-approval preparation tasks whose metadata explicitly requests `coding_engine: openhands`.
10. All ordinary Native TaskService execution continues through the original TaskService implementation.
11. OpenHands preparation returns a normal `TaskExecutionResult` in dry-run state, including plan, patch operations, changed paths and review metadata.
12. The existing router therefore continues to own task storage, progress, approval, persistence, execution, backup and rollback without being rewritten.
13. OpenHands preparation is automatically installed when the Code Builder package loads.
14. A real API validator now creates an OpenHands task through `/api/code-builder/tasks`, polls the same task endpoint used by the UI, requires the task to stop at `awaiting_approval`, verifies patch operations exist, and verifies the real repository was not changed.

## Current API usage

The existing API already accepts arbitrary task metadata. Until the UI selector is added, OpenHands can be selected by sending:

```json
{
  "metadata": {
    "coding_engine": "openhands"
  }
}
```

No API schema break is required for the current backend integration.

## Next integration boundary

1. Run the new backend tests in the actual LUMINA runtime.
2. Run `backend/tests/runtime_validate_openhands_api.py` with the backend and OpenHands/model available.
3. If and only if that real path reaches `awaiting_approval` safely, expose Native/OpenHands selection in the existing Code Builder UI.
4. Then validate approval -> backup -> apply -> build -> rollback using a controlled sandbox task before enabling OpenHands apply for normal work.

## Validation status

The integration code and automated tests are present in GitHub. The GitHub connector cannot execute the repository or OpenHands runtime, so these tests are not claimed as passed. OpenHands remains NOT READY until the target machine executes the tests and the real API validator successfully reaches the approval boundary.
