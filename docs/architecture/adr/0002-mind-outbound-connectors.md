# ADR 0002: Mind Outbound Connectors

Status: Accepted

## Context

The Mind studio is the owner's business suite (marketer, CEO, financial
advisor, attorney, banker, coach) and must reach the owner's WhatsApp, social
media and email. Before this change LUMINA had no outbound channel module at
all, so Mind could only produce content inside the app.

## Decision

Add a connector layer under `backend/ai_runtime/connectors/` behind the existing
Mind capability registry, rather than a parallel messaging subsystem.

- One `Connector` abstraction with a `configured()` / `mode()` contract.
- Three connectors: email (SMTP), WhatsApp (Cloud API), social (webhook
  gateway, provider-neutral so the gateway owns platform OAuth).
- A new registry capability `connect` with `status`, `send_email`,
  `send_whatsapp`, `publish_social`.
- Every send action has `risk="approval"`, so it is gated by the existing
  persisted approval flow. The orchestrator runs connector sends in-process so
  the approval decision is honoured at the exact moment it is taken.
- When a connector is unconfigured or disabled it runs a validated **dry-run**:
  it reports exactly what would be sent and never claims delivery.

## Consequences

- The Mind studio works without credentials (dry-run) and upgrades to live
  sending by setting environment variables only.
- No secret is stored in the repository; configuration is environment-only and
  connector results redact secret-looking keys.
- Email headers are guarded against CR/LF injection; WhatsApp numbers are
  normalised to E.164 (Greek local numbers get the 30 country code).
- Reversible: the connector package and the `connect` capability can be removed
  without touching other capabilities. The Mind registry, orchestrator gating
  and existing endpoints are unchanged.
