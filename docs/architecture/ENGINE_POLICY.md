# Code Engine Policy

LUMINA Code Builder selects between three engines. The order is deterministic
and never opaque:

| Engine | Role | Default | Availability |
| --- | --- | --- | --- |
| `gold_builder` | **Primary** — recommended when reachable | no | opt-in, needs the Gold Builder service |
| `openhands` | **Secondary** — experimental alternate agent | no | opt-in, needs OpenHands runtime |
| `native` | **Legacy fallback** — always available | **yes** | always |

The `native` engine remains the safe default. Gold Builder becomes the
*preferred* engine automatically once its service answers, but nothing is
routed to it implicitly unless the owner selects it (manual) or auto mode is
explicitly chosen.

## Gold Builder integration boundary

Gold Builder is **not** copied into LUMINA. It is a separate FastAPI service
mounting `/api/gb/*`. LUMINA talks to it through
`backend/code_builder/gold_builder_engine.py` over HTTP:

- `GOLD_BUILDER_URL` selects the service (default `http://127.0.0.1:8010`).
- The adapter only creates/inspects jobs and reads activity, preview, review and
  the final report. Applying changes is never enabled from LUMINA's side here.
- When the service is unreachable the engine reports unavailable and LUMINA
  keeps working on native.

## Mapping to the Code Builder panel

| Panel | Gold Builder endpoint |
| --- | --- |
| Agent Activity | `GET /api/gb/jobs/{id}/stream` (SSE) |
| Live Preview | `GET/POST /api/gb/jobs/{id}/preview` |
| Final Report | assembled from `/jobs/{id}`, `/review`, `/screenshot` |
| Provider changes | `GET /api/gb/providers` |
| Cancel | `DELETE /api/gb/jobs/{id}` |
| Resume | `POST /api/gb/jobs/{id}/guardian/resume` |

## Safety

- No engine mutates the source repository without an explicit approval step.
- OpenHands and Gold Builder run in isolated copies / their own service.
- Selecting an unavailable engine raises a clear error instead of silently
  falling back to a different engine.
