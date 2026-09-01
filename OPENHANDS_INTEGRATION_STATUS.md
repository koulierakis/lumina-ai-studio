# LUMINA OpenHands Integration Status

Implemented on the completion branch:

1. LUMINA prepares a lean disposable copy of the repository, excluding runtime/build/log/temp/coverage/virtual-environment folders and dotenv secrets.
2. Empty instructions are rejected before copy creation.
3. OpenHands autonomous work is permitted only inside the disposable copy.
4. The real repository remains untouched during proposal preparation.
5. Before/after file states are compared and converted into the same patch-operation format already understood by the existing LUMINA PatchService.
6. Native Code Builder remains the default and is explicitly preserved.
7. `task_engine_integration.py` intercepts only pre-approval preparation tasks whose metadata explicitly requests `coding_engine: openhands`.
8. Ordinary Native TaskService execution continues through the original TaskService implementation.
9. Approved OpenHands plans are restored instead of invoking a second planner after approval, preventing approved plan/patch drift.
10. OpenHands scope is enforced both in the prompt and after execution: target paths, excluded paths, create permission, and delete permission are checked before a proposal can reach approval.
11. Out-of-scope proposals are rejected before approval.
12. OpenHands preparation returns a normal `TaskExecutionResult` in dry-run state with plan, patch operations, changed paths, review metadata, and `scope_enforced: true`.
13. The existing router continues to own task storage, progress, approval, persistence, execution, backup and rollback without being rewritten.
14. OpenHands preparation is automatically installed when the Code Builder package loads.
15. A real API preparation validator now requires the task to reach `awaiting_approval`, verifies exact scoped patch paths, and verifies the real repository remains unchanged.
16. A separate opt-in real runtime validator covers approval -> backup -> apply -> rollback using one controlled validation file and removes the validation folder afterward.
17. A separate opt-in reliability validator runs 10 consecutive real OpenHands preparation tasks and requires all 10 to reach `awaiting_approval` without changing the real repository.
18. `scripts/validate_openhands_code_builder.ps1` runs the focused tests and real preparation validator, with explicit opt-in gates for the 10-task reliability run and controlled apply/rollback run.

## Current API usage

The existing API already accepts arbitrary task metadata. Until the UI selector is added, OpenHands can be selected by sending:

```json
{
  "metadata": {
    "coding_engine": "openhands"
  }
}
```

A request should also provide narrow `target_paths` whenever practical. No API schema break is required for the current backend integration.

## Runtime gates before READY

1. Focused backend tests must pass in the actual LUMINA runtime.
2. Real scoped preparation must reach `awaiting_approval` safely.
3. 10 consecutive real preparation tasks must pass.
4. Controlled approval -> backup -> apply -> rollback must pass.
5. One larger real LUMINA change must pass with approval, verification and rollback available.
6. Only after those gates should Native/OpenHands selection be exposed for normal UI use.

## Validation status

The integration code and automated/runtime validators are present in GitHub. The GitHub connector cannot execute the repository or OpenHands runtime, so none of these runtime gates are claimed as passed here. OpenHands remains NOT READY until the target machine executes them successfully.
