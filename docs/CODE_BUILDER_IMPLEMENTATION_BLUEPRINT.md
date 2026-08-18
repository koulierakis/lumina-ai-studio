# LUMINA Code Builder Implementation Blueprint

| File | Current responsibility | Required change | Reason / dependency | Risk |
|---|---|---|---|---|
| `backend/code_builder/router.py` | API lifecycle, task store, approval/start/cancel/rollback | Preserve preparation result; schedule safe preparation before approval; bind the exact prepared patch on approval | Makes existing approval the real production-write boundary | Medium; state-transition compatibility |
| `backend/code_builder/task_service.py` | Canonical orchestration pipeline | Reuse unchanged for preparation through a cloned dry-run request and for approved execution | Avoid a second orchestrator; preserves rollback/build/event behavior | Low for this step |
| `backend/code_builder/patch_service.py` | Patch normalize/validate/diff/apply | Reuse unchanged | Existing dry-run is already the proposed-diff engine and apply path is transactional | Low |
| `backend/code_builder/backup_service.py` | Backup and repository restoration | Reuse unchanged | Existing rollback performs real file restoration and integrity checks | Low |
| `backend/code_builder/build_service.py` | Verification commands | Reuse after approval; later expose verification semantics explicitly in API/UI | Already supports targeted backend/frontend verification | Low |
| `backend/code_builder/planning_service.py` | Structured AI implementation plan | Reuse unchanged initially | Existing structured plan is suitable for approval payload | Low |
| `backend/code_builder/repository_service.py` | Repository analysis/index | Reuse; later enhance relevant-file selection only if evidence requires it | Avoid duplicate repository-analysis subsystem | Low |
| `backend/code_builder/security.py` | Path/command safety | Reuse unchanged unless targeted tests reveal a gap | Existing safety controls must remain authoritative | Low |
| Existing Code Builder frontend | Task creation/status/approval UX | Surface plan, affected files, proposed diff, patch validation, AI review and explicit approve/reject | User must approve concrete proposed work, not an instruction alone | Medium |
| Backend review integration | No dedicated AI-review artifact identified in current orchestration | Add a bounded review step over plan + proposed patch + validation before approval, reusing configured AI provider | Required target architecture item | Medium |
| Tests | Pipeline and approval unit tests | Keep focused transaction-boundary regression; add API/state/UI tests alongside each subsequent change | Prevent direct-write regression | Low |

## Ordered implementation

1. Transaction boundary and preparation result — implemented on the working branch.
2. API contract hardening for prepared artifacts and approval immutability.
3. Dedicated AI review artifact before approval.
4. Existing Code Builder UI integration for plan/diff/validation/review.
5. Post-approval verification result presentation.
6. Rollback status/verification presentation.
7. Targeted backend and frontend regression tests.
8. Remove/ignore legacy Code Creator and DeveloperCenter paths from all new work; do not migrate them into the Code Builder.
