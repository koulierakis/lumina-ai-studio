# LUMINA Code Builder — OpenHands Experiment

## Goal
Evaluate OpenHands as the coding engine behind the existing LUMINA Code Builder UI without changing the current production Code Builder branch.

## Safety boundary
This experiment lives only on branch `experiment/openhands-code-builder`, created from `work/code-builder-final-hardening` at commit `1b5843aeb0932014f747c54c02774541b7b11426`.

The current Code Builder remains untouched on its existing branch.

## What the current LUMINA Code Builder already has
The existing implementation already contains useful product-level pieces that should be preserved:

- React Code Builder UI with task creation, progress, persistence, approval, cancel and rollback actions.
- FastAPI `/api/code-builder/...` backend routes.
- Repository analysis and path safety rules.
- Planning, backup, patch validation/application, build validation and rollback services.
- Persistent task state and event history.
- Ollama model status and local model integration.

The weak point observed in real use is the custom AI orchestration / structured patch generation path: unit and targeted tests can pass while real model responses still vary and fail at runtime.

## OpenHands finding
OpenHands provides a software-agent engine designed specifically for coding tasks. It can read/edit files, use a terminal, run tests and work against a repository. It offers an SDK and server/API approach.

### Important compatibility decision
Do **not** initially embed the OpenHands Python SDK directly into the existing LUMINA backend.

Reason: the current LUMINA environment is built around its existing Python runtime/dependencies, while the current OpenHands SDK documentation requires a newer Python environment. Embedding it directly would force a risky backend/runtime upgrade before we even know whether OpenHands improves the real Code Builder experience.

### Recommended experiment architecture
Run OpenHands as a separate local service and connect LUMINA to it through a small adapter.

```text
LUMINA Code Builder UI
        |
        v
Existing FastAPI Code Builder routes
        |
        v
LUMINA OpenHands Adapter
        |
        v
OpenHands local service / agent
        |
        v
Repository workspace + coding model
```

This lets us keep the existing LUMINA UI, approvals, task history, backup/rollback policy and security boundary while replacing only the unreliable AI coding engine during the experiment.

## Model constraint discovered
OpenHands needs a much larger context window than the current 4096-token Ollama configuration used in prior Code Builder runs. Current OpenHands documentation recommends at least about 22k context and preferably 32k for local agent use.

This means the current `qwen2.5-coder:1.5b` / `7b` setup must be tested carefully. OpenHands can connect to Ollama, but a small model or too-small context may behave like a chatbot, fail tool use, or produce unreliable actions.

This is a model/hardware limitation, not something the adapter can magically fix.

## Phase 1 — non-destructive proof of concept
Before replacing any current Code Builder logic, implement only these experiment pieces:

1. `OpenHandsAdapter` abstraction in the Code Builder backend.
2. Health/status check for the OpenHands local service.
3. A test endpoint/mode that sends one safe coding task to OpenHands.
4. Capture OpenHands progress/events and map them into the existing LUMINA task/event format.
5. No automatic writes to the main branch.
6. Run against a disposable/test workspace or dry-run branch first.

## Pass/fail criteria
The OpenHands experiment is useful only if it can pass real tasks, not merely mocked tests.

Minimum acceptance gate:

- OpenHands service is reachable from LUMINA.
- The model can inspect the repository.
- It can correctly identify target files.
- It can produce a valid small code change.
- It can run a validation/test command.
- LUMINA receives progress and final status.
- Failure messages are preserved instead of hidden.
- 10 consecutive real safe tasks complete without orchestration failure.

If these conditions are not met, do not replace the existing Code Builder engine.

## Phase 2 — only after proof succeeds
If the proof succeeds:

- Keep the current Code Builder UI.
- Keep LUMINA approval controls.
- Keep LUMINA backup/rollback safety.
- Use OpenHands as the execution/coding agent behind an adapter.
- Preserve the old engine temporarily as a fallback until the 10-task acceptance suite is green.

## What must be done on the user's PC later
GitHub-side preparation can be done remotely. The final local proof requires the PC because GitHub cannot start local Docker/Ollama processes.

At that stage the user should only need to:

1. Start Docker Desktop.
2. Start Ollama.
3. Run one prepared setup/start command.
4. Open the LUMINA Code Builder page and start the prepared validation.

The rest should be automated and should output one final result: `CODE BUILDER READY: YES` or `NO`.
