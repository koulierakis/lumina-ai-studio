# ADR 0003: Mind Autonomy Dial

Status: Accepted

## Context

The Mind orchestrator classifies every operation as `risk="auto"` or
`risk="approval"`. Approval operations always asked, and auto operations always
ran. There was no way for the owner to say "I trust the safe steps, stop asking"
— nor, more importantly, to make Mind *stricter* than the default.

Two failure modes were possible once connectors and the code builder existed:

- an owner who wants full control still has to approve harmless reads;
- an owner who wants speed could be tempted by a blanket "skip approval" switch
  that would also auto-send email or auto-delete a project.

## Decision

Add a three-level autonomy dial with an asymmetric, explicit policy, in
`backend/ai_runtime/capabilities/autonomy.py`.

Levels: `manual` < `assisted` (default) < `auto`.

The dial can always make Mind stricter. It can relax only one narrow, reversible
category:

- `manual` — every operation requires approval, even `risk="auto"` ones.
- `assisted` — default: `risk="auto"` runs; `risk="approval"` asks.
- `auto` — additionally runs `("code_builder", "execute")`, which is local and
  backed by an automatic rollback in the engine.

Everything else stays gated at every level, enforced by a single invariant:

- any capability in `_NEVER_CAPABILITIES` (`connect` — all outbound sends);
- any action whose name starts with `delete` or `remove`;
- any unrecognised approval operation (fail closed).

The default level is read from `LUMINA_MIND_AUTONOMY`, with a runtime override
via `POST /api/runtime/mind/autonomy`. The effective level is exposed through
`GET /api/runtime/mind/autonomy` and `GET /api/runtime/advisor/status`.

## Consequences

- Default behaviour is byte-for-byte the old behaviour: `assisted` runs auto
  operations and gates approval operations.
- The dangerous switch does not exist: there is no level at which email,
  WhatsApp, social posts or deletions run without approval.
- New capabilities default to "never auto" until deliberately classified, so a
  future action cannot silently become automatic.
- The policy is pure and unit-tested directly, independent of the orchestrator.
- Reversible: the module, the two endpoints and the gating call can be removed;
  the orchestrator falls back to the previous `risk == "approval"` check.
