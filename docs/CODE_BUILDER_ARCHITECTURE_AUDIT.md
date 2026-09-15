# LUMINA Code Builder Architecture Audit

## Architecture map

The active Code Builder is the existing `backend/code_builder/` subsystem. The production path is:

`router.py` → `TaskService` (`task_service.py`) → `RepositoryService` → `PlanningService` → existing patch generation path (`PatchService` + configured `OllamaService`) → patch dry-run/validation → approval boundary → backup → patch application → `BuildService` verification → rollback through `BackupService` on failure.

No second planner/coder/repository-analysis subsystem is required or introduced.

## Current reusable components

- `repository_service.py`: repository-root validation, scanning/indexing, symbols/imports, hashes and safe file reads.
- `planning_service.py`: structured AI implementation planning; it does not write production files.
- `task_service.py`: canonical orchestration stages, events, cancellation/timeouts, build and rollback policy.
- `patch_service.py`: canonical patch operations, dry-run validation/diff, atomic writes, transaction rollback and path safety.
- `backup_service.py`: repository file snapshots, integrity verification and real file restoration with a rollback safety snapshot.
- `build_service.py`: constrained verification commands including compile, pytest, Ruff, mypy and frontend build/test operations.
- `security.py`: repository/path/command boundaries and destructive-command controls.
- `router.py`: task persistence, API lifecycle, approval/cancel/start/rollback endpoints and task event exposure.

## Confirmed architectural gap

Before this change, an approval-required task entered `AWAITING_APPROVAL` immediately and was not analyzed. After approval, `TaskService` executed the complete pipeline, including production patch application. As a result, the user was being asked to approve before a concrete plan and proposed patch/diff existed.

The domain already contained `AWAITING_APPROVAL`, `APPROVED`, approval timestamps/comments and approval endpoints, so replacing it would have duplicated working architecture.

## Transaction boundary implemented

Approval-required tasks now perform a preparation execution using the existing TaskService with:

- `dry_run=True`
- backup disabled
- build disabled
- rollback disabled

This preparation execution still performs repository analysis, structured planning, patch generation and patch validation. For canonical `PatchRequestPayload`, validation uses the existing dry-run application path, which produces the proposed diff without writing production files.

On successful preparation, the task transitions to `AWAITING_APPROVAL` and exposes `preparation_result` through the existing task detail API. Approval binds the exact prepared patch operations into `approved_patch_operations`; unapproved raw patch-operation metadata is removed. The normal execution then reuses the existing plan/patch safety checks, creates the backup, applies the approved patch and runs the configured verification/build pipeline. Existing rollback policy remains authoritative for failures.

## State model

`QUEUED → ANALYZING → AWAITING_APPROVAL → APPROVED → EXECUTING → COMPLETED`

Failure paths remain:

`ANALYZING/EXECUTING → FAILED | CANCELLED | TIMED_OUT`

and after a production mutation failure:

`EXECUTING → ROLLING_BACK → ROLLED_BACK | ROLLBACK_FAILED`

Tasks created with `require_approval=False` keep the direct execution path.

## Verification

A focused transaction-boundary test proves that an approval-required change produces a validated diff while the target file is absent, then applies the exact prepared change only after approval. Existing execution-pipeline tests continue to cover backup, patch application, path-plan enforcement and rollback.

## Remaining product work

The backend now has the correct transaction boundary. The next product layers are to surface preparation data clearly in the existing Code Builder UI, add a dedicated AI-review artifact before approval, and make post-apply verification/review status explicit in the UI without creating a parallel code-generation subsystem.
