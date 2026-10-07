# LUMINA Mind Connectors

The Mind studio can send the owner's communications through their own channels.
Everything is environment-configured; no credential is ever committed.

## Channels

| Channel | Enabling variables | Notes |
| --- | --- | --- |
| Email | `LUMINA_SMTP_HOST`, `LUMINA_SMTP_FROM` | Optional `LUMINA_SMTP_PORT` (587), `LUMINA_SMTP_USER`, `LUMINA_SMTP_PASSWORD`, `LUMINA_SMTP_USE_TLS` |
| WhatsApp | `LUMINA_WHATSAPP_TOKEN`, `LUMINA_WHATSAPP_PHONE_ID` | Optional `LUMINA_WHATSAPP_BASE_URL` |
| Social | `LUMINA_SOCIAL_WEBHOOK_URL` | Optional `LUMINA_SOCIAL_CHANNELS`, `LUMINA_SOCIAL_TOKEN` |

Each channel can be forced off with `LUMINA_<CHANNEL>_DISABLED=true`.

## Modes

- `live` — configured and enabled; the message is sent for real.
- `dry_run` — not configured (or disabled); the request is validated and
  reported, but nothing leaves the machine. The result always carries
  `dry_run: true`.
- `disabled` — explicitly turned off; behaves like dry-run.

## Safety

- Every send is `risk="approval"`: Mind stores it as pending and executes only
  after an explicit owner approval. Declining sends nothing.
- Email subject and recipient are rejected if they contain line breaks
  (header-injection guard).
- WhatsApp numbers are normalised to E.164; a Greek local number
  (`6941234567`) becomes `306941234567`.
- Connector results redact any value whose key looks secret-bearing.

## API

- `GET  /api/runtime/mind/connectors` — channel status
- `POST /api/runtime/mind/connectors/email/send`
- `POST /api/runtime/mind/connectors/whatsapp/send`
- `POST /api/runtime/mind/connectors/social/publish`

The same actions are available through Mind: `POST /api/runtime/mind/execute`
with `capability="connect"`, or by chat ("στείλε email στο …",
"δημοσίευσε στο facebook …"). The capability catalog is exposed at
`GET /api/runtime/mind/capabilities`.
