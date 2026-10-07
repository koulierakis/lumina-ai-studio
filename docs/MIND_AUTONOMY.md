# Mind Autonomy Dial

The autonomy dial decides how much LUMINA Mind may do without asking you. It is
deliberately asymmetric: it can always make Mind *stricter*, and it can relax
only one narrow, reversible category.

## Levels

| Level | Name | Behaviour |
| --- | --- | --- |
| `manual` | Χειροκίνητο | Every operation asks for approval, even harmless ones. |
| `assisted` | Ημιαυτόματο | **Default.** Safe operations run; approval operations ask. |
| `auto` | Αυτόματο | Also runs reversible local operations (code-builder apply). |

The default is `assisted`, which reproduces the behaviour that existed before the
dial, so nothing changes unless you change it.

## What never becomes automatic

At **every** level, these always ask for approval:

- any outbound send — email, WhatsApp, social publishing (`connect`);
- any deletion — projects, media, documents, gallery items, voice packs;
- any operation that is not explicitly classified (fail closed).

There is no setting that lets Mind send a message or delete something on its
own. The only thing `auto` unlocks is applying a code-builder plan, which is
local and backed by an automatic rollback.

## Changing the level

- In the app: the **Αυτονομία** panel in LUMINA Mind (right column).
- By API:
  - `GET  /api/runtime/mind/autonomy` — current level and labels.
  - `POST /api/runtime/mind/autonomy` with `{"level": "manual|assisted|auto"}`.
- At start-up: the `LUMINA_MIND_AUTONOMY` environment variable sets the default.
  A runtime change overrides it until restart.

The effective level is also reported in `GET /api/runtime/advisor/status` under
`autonomy`.
