# LUMINA Code Builder V2

## Goal

Build a new Code Builder from scratch without carrying forward the legacy module's accumulated complexity. V2 remains isolated until it passes acceptance tests.

## Non-negotiable design rules

1. Small modules with one responsibility.
2. Structured task state machine; no hidden phase changes.
3. Repository path containment on every file operation.
4. Plan first, explicit approval before writes by default.
5. Atomic change application and backup/rollback before integration.
6. Validation commands must pass before a task can be marked completed.
7. Every planned file must be accounted for by the produced change set.
8. Live events/progress are first-class API data for the UI.
9. AI provider is an adapter, not embedded in orchestration logic.
10. Legacy `backend/code_builder` stays untouched until V2 is proven.

## Initial package

- `models.py`: API contracts and task lifecycle.
- `security.py`: repository path containment.
- `repository.py`: minimal safe filesystem boundary.
- `planner.py`: provider-neutral planning interface.
- `executor.py`: command execution boundary.
- `service.py`: task orchestration.
- `router.py`: thin FastAPI transport layer.

## Next implementation gates

### Gate 1 — Core safety
Path safety, lifecycle tests, persistent store, cancellation semantics.

### Gate 2 — Planning
Ollama adapter, structured JSON plan schema, retry/repair for malformed model output.

### Gate 3 — Patch transaction
Backup, exact planned-file enforcement, atomic apply, rollback.

### Gate 4 — Validation
Per-project test/build detection, timeout, captured stdout/stderr, completion only on pass.

### Gate 5 — UI
New V2 page with prompt, plan approval, live phase/progress, elapsed time, logs, cancel and rollback.

### Gate 6 — Acceptance
Real local-model E2E tasks, including a multi-file task that fails if even one planned file is omitted.

Only after Gate 6 passes should `/studio/code-builder` switch from legacy to V2.
