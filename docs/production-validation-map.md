# Production Validation Gate — Verified Application Map

Phase 0 deliverable. Everything below was verified against the repository
(`frontend/src`, `backend`, `e2e`, `.github/workflows`) at local HEAD
`6f2bcc8` — which is also the deployed production commit (confirmed via
`GET /api/health` → `commit_sha=6f2bcc87ca68b0205c17f40048b25f098a11fc27`).
No routes, selectors, endpoints, response fields, or storage keys were invented.

Production target: `https://lumina-ai-studio.onrender.com` (default `baseURL` in `playwright.config.js:3`).

---

## 1. Frontend routing (`frontend/src/App.js`)

Served by `BrowserRouter`; all areas below `/studio` are wrapped in
`RequireAuth > StudioLayout` (`App.js:45-79`).

| Path | Component | Source |
|---|---|---|
| `/` | Navigate → `/studio/dashboard` | App.js:43 |
| `/login` | `Login` | App.js:44 |
| `/studio` (index) | Navigate → `dashboard` | App.js:53 |
| `/studio/dashboard` | `Dashboard` (testid `dashboard-page`) | App.js:54 |
| `/studio/mind` | `ExecutiveAdvisor` (testid `lumina-mind-page`) | App.js:55 |
| `/studio/advisor` | `ExecutiveAdvisor` (alias) | App.js:56 |
| `/studio/developer` | `DeveloperCenter` | App.js:57 |
| `/studio/code-creator` | `CodeCreator` | App.js:58 |
| `/studio/code-builder` | `CodeBuilder` (v1) | App.js:59 |
| `/studio/code-builder-v2` | `CodeBuilderV2` | App.js:60 |
| `/studio/generate` | `Generate` | App.js:61 |
| `/studio/identity` | `IdentityPacks` | App.js:62 |
| `/studio/gallery` | `Gallery` | App.js:63 |
| `/studio/media-library` | `PlatformHub mode="media"` | App.js:64 |
| `/studio/jobs` | `PlatformHub mode="jobs"` | App.js:65 |
| `/studio/notifications` | `PlatformHub mode="notifications"` | App.js:66 |
| `/studio/editor` | `EditorLanding` | App.js:67 |
| `/studio/documents` | `DocumentStudio` | App.js:73 |
| `/studio/finance` | Navigate → `mind` | App.js:74 |
| `/studio/search` | `WorkspaceCenter mode="search"` | App.js:78 |
| `*` | Navigate → `/studio/dashboard` | App.js:80 |

Unauthenticated access to any `/studio/*` is rejected client-side by
`RequireAuth` (`frontend/src/components/RequireAuth.jsx`): when `user` is
null it renders `<Navigate to="/login" state={{ from: pathname }} />`.

## 2. Authentication

Verified flow (`frontend/src/context/AuthContext.jsx`, `frontend/src/lib/api.js`,
`backend/server.py`).

- **Login endpoint**: `POST /api/auth/login`, JSON body `{ email, password }`
  → `200` `TokenResponse { access_token, email }` (`server.py:814-836`).
  Errors: `401 "Invalid credentials"`, `429` (login rate-limit).
- **Token storage key**: `localStorage['lumina_token']` (`AuthContext.jsx:52`);
  user object `localStorage['lumina_user'] = { email }`.
- **Authenticated user endpoint**: `GET /api/auth/me` with
  `Authorization: Bearer <lumina_token>` → `200 { "email": "..." }`
  (`server.py:839-841`). Without a valid token → `401`.
- **API client**: axios instance `api` with `baseURL = ${BACKEND_URL}/api`
  (`frontend/src/lib/api.js:4,11-12`); request interceptor attaches
  `Authorization: Bearer <lumina_token>` from localStorage; response
  interceptor clears `lumina_token`/`lumina_user` on `401`
  (`api.js:19-33`).
- **Logout**: removes `lumina_token` + `lumina_user`, then
  `window.location.href = '/login'` (`AuthContext.jsx:58-63`). UI button:
  `data-testid="logout-btn"` in `frontend/src/components/Sidebar.jsx:53`.
- **Login UI**: form `data-testid="login-form"`, fields `login-email` /
  `login-password`, submit `login-submit`; after success navigates to
  `/studio/generate` (`frontend/src/pages/Login.jsx:25,33,57-76`).
  Production builds always use backend login (LOCAL_DEV_AUTH only when
  `NODE_ENV !== 'production'`).

## 3. Mind (Executive Advisor)

UI: `frontend/src/pages/ExecutiveAdvisor.jsx`; Backend:
`backend/ai_runtime/router.py`, `backend/ai_runtime/advisor.py`.

### Selectors
- Page: `main[data-testid="lumina-mind-page"]`, heading `LUMINA Mind`.
- Provider buttons (exact text, role=button): `Groq`, `Τοπικό`, `SambaNova`,
  `Cloud ανάλυση`, `Έρευνα διαδικτύου` (lines 560-564). Default provider is
  `groq` (line 190), role `auto`, deep reasoning on.
- Composer textarea: the single `textarea` inside `main[data-testid="lumina-mind-page"]`
  (helpers `mindComposer` / `mindSendButton`, `e2e/helpers/lumina.js:132-138`).
- Messages: assistant bubble `.whitespace-pre-wrap` (lines 154); orchestration
  panel `data-testid="mind-orchestration-panel"` with decision buttons
  `mind-approve-action` / `mind-decline-action` (lines 110, 130, 133).
- Session list: `aside > section > div.space-y-1 > div` per session; open button
  is the `flex-1 text-left` button whose `.truncate div` shows `item.title`
  (lines 537-543).
- Attach panel: `data-testid="advisor-documents-panel"` (line 608).

### API
- `POST /api/runtime/advisor/ask` body
  `{ message, session_id, role, deep_reasoning, remember_message, provider,
     web_research, orchestrate, context: { documents: [...] } }`
  (`ExecutiveAdvisor.jsx:341-351`; fixed schema `AdvisorRequest`, `advisor.py:45-48`,
  `extra="forbid"`).
  Response `{ session_id, answer, role, role_name, provider, model,
  provider_status: "ok"|"unavailable", sources, orchestration, error,
  elapsed_seconds, ... }` (`advisor.py:497-511`).
- Provider failure fallback: the assistant reply is substituted with a canned
  English string, e.g. `"Groq cloud mode is currently unavailable. Check …"`
  (`advisor.py:446,457,472,484`). **The gate MUST detect this marker and fail**
  (this is the demo/unavailable content trap).
- `GET /api/runtime/advisor/status` → includes `groq_configured`,
  `sambanova_configured`, `openai_configured`, `local_available` (presence checks,
  `advisor.py:128-129` and surrounding; the send guard at
  `ExecutiveAdvisor.jsx:320-331` blocks sending until the chosen cloud flag is
  true).
- `GET /api/runtime/advisor/sessions` → `{ sessions: [{ id, title,
  message_count, last_message, ... }] }`. Session title = first 72 chars of the
  first user message (`advisor.py:492-493`).
- `GET /api/runtime/advisor/sessions/{session_id}` → session dict with
  `messages: [{ id, role: "user"|"assistant", content, role_mode, provider,
  model, sources, orchestration }]` (`advisor.py:181-185`, inspect/ask append at
  `489-490`). Messages persist server-side (last 100 kept).
- Mind orchestration (approval/decline) — used only for reference here; the gate
  exercises the safe Code Builder cancel path instead:
  `POST /api/runtime/mind/execute`, `POST /api/runtime/mind/decide { decision }`,
  `GET /api/runtime/mind/actions`, `GET /api/runtime/mind/pending`
  (`router.py`; verified in prior e2e phases).

## 4. Documents

UI: `frontend/src/pages/DocumentStudio.jsx` (no data-testids — uses class/aria
selectors); API client `frontend/src/documents/model.js`; backend
`backend/document_studio/router.py` + `models.py`.

### Selectors (verified against source)
- Toolbar `New` button: `button.doc-tool-btn` with visible text `New`
  (creates via `POST /api/documents`, line 215).
- Title input: `input.doc-title-input`, `aria-label="Document title"`
  (line 214); on blur it auto-saves via `documentApi.update` =
  `PATCH /api/documents/{id}`.
- Library panel: `div.doc-library-item` buttons showing `doc.title`
  (offered when library open; list itself loads GET /api/documents on mount).
- Export buttons: `Export PDF`, `Export Word` (`doc-btn-export`, line 214).

### API
- `GET /api/documents` → `list[CorporateDocument]` (`router.py:1419-1420`).
- `POST /api/documents` body
  `{ title, content_html, content_text, document_type, category, language,
  country, tags, ... }` → `CorporateDocument` (`router.py:1566-1613`).
  Runs auto legal review; requires `owner` (Bearer).
- `GET /api/documents/{document_id}` → `CorporateDocument`.
  `GET /api/documents/{document_id}/preview` → HTML preview
  (`router.py:2423`). Export: `GET /api/documents/{document_id}/export/{fmt}`
  (`router.py:2542`; fmt ∈ supported set, see `EXPORT_FORMATS` around
  `router.py:407`).
- `documents` capability contract (`backend/ai_runtime/capabilities/registry.py:83-143`):
  create risk=auto, delete risk=approval; summary fields `id`, `title`.
- `CorporateDocument` fields (`models.py:234-264`): `id`, `owner_email`, `title`,
  `document_type`, `category`, `status`, `content_html`, `content_text`,
  `searchable_text`, `version_number`, `created_at`, `updated_at`, etc.
- Media streaming (for images/media assets): `GET /api/media/{media_id}`
  (Bearer, owner-scoped) returns file bytes (`server.py:1035+`).

## 5. Code Builder V2 (safe approval gate)

UI: `frontend/src/pages/CodeBuilderV2.jsx`; backend `backend/code_builder_v2/`.
Safe, non-destructive path: create plan → wait `awaiting_approval` → **Cancel**
(never Execute in production).

### Selectors / UI behavior
- Route `/studio/code-builder-v2`; form `textarea` (instruction) + `input`
  (model, default `qwen2.5-coder:7b`) + submit button `Create plan`.
- Status badge (`.uppercase`) shows task status; action buttons `Execute`,
  `Cancel`, `Rollback`, `Refresh`.
- `canExecute = status === 'awaiting_approval'`; `canCancel` for any
  non-terminal status; `execute` applies the plan to the real repository.
- Frontend `api()` helper calls the relative `/api/code-builder-v2/...` path
  **without** attaching the Bearer token (unlike the Mind/documents clients).
  The router does not require `require_owner` on task routes.

### API (backend/code_builder_v2/router.py, models.py)
- `GET /api/code-builder-v2/health` → `{ status:"healthy", version:2, configured }`.
- `POST /api/code-builder-v2/tasks` body
  `TaskRequest { prompt (min 3), model?, auto_apply:false, timeout_seconds }`
  → `BuildTask` (`router.py:37-39`, `models.py:23-28`).
- `GET /api/code-builder-v2/tasks/{task_id}` → `BuildTask`.
- `POST /api/code-builder-v2/tasks/{task_id}/cancel` → status `cancelled`,
  no repository change (`router.py:52-54`; `service.cancel_task`).
- `POST /api/code-builder-v2/tasks/{task_id}/execute` → applies plan
  (risk=approval in registry `registry.py:330-334`) — **must never be invoked
  by the gate**.
- `TaskStatus` enum (`models.py:11-20`): `queued, planning, awaiting_approval,
  executing, validating, completed, failed, cancelled, rolled_back`.
- `BuildTask` (`models.py:54-63`): `id, request, status, plan: ChangePlan |
  { summary, changes: [{ path, operation, reason }], validation_commands },
  execution: { backup_id, changed_paths, ... }, error, events[]`.
- Capability registry risk map (`registry.py:309-339`): plan=auto, get_task=auto,
  execute=approval, rollback=auto. Registry also shows v2 `cancel` identical to
  rollback risk grouping (safe).

### Planner reality (verified in source and in runs)
- `backend/code_builder_v2/ollama.py`: planner is cloud-first — Groq when
  `GROQ_API_KEY` present, else HuggingFace InferenceClient
  (`Qwen/Qwen2.5-Coder-32B-Instruct`). There is no local fallback.
- Observed locally: with the stored `GROQ_API_KEY` present but returning
  `HTTP 401 Unauthorized` (8/8 calls in the Groq acceptance run), planning
  fails and tasks land in `status:"failed"` with `task.error` set — the
  `awaiting_approval` gate never engages. The gate reports this honestly:
  TEST 4 requires `awaiting_approval` + a real plan before touching Cancel.
- Consequence for TEST 4: if production planning succeeds → safe decline
  verified end-to-end; if it fails → TEST 4 fails with the provider diagnostic
  (never faked).

## 6. Playwright infrastructure

- `@playwright/test ^1.62.1` (`package.json`); `testDir ./e2e`.
- `playwright.config.js`: chromium desktop only; `timeout 180000`;
  `expect.timeout 30000`; retries `CI?1:0`; reporter `list` + `html`
  (test_reports/playwright-html); outputDir test_reports/playwright-artifacts;
  trace `retain-on-failure` (off when `LUMINA_E2E_ISOLATED=1`); screenshot
  `only-on-failure`; video off.
- npm scripts: `e2e:render` → `playwright test`; `e2e:local` →
  `python scripts/run_local_e2e.py`.
- Helpers (`e2e/helpers/lumina.js`): `signIn`, `ensureSignedIn`,
  `authenticatedGet`, `authenticatedPost`, `openMind`, `mindComposer`,
  `mindSendButton`, `attachDiagnostics`. Redaction: `Bearer <tok>`,
  `access_token`, `password`, secret-like query keys; bodies sliced to 3000 chars.
- CI `.github/workflows/render-e2e.yml`: `workflow_dispatch` (input `base_url`)
  + `workflow_run` on frontend finalize; env `LUMINA_E2E_EMAIL` /
  `LUMINA_E2E_PASSWORD` from GitHub secrets; `npm ci`;
  `npx playwright install --with-deps chromium`; curl wait (up to 30×20s,
  accepts 200/301/302/401/403); `npm run e2e:render`; artifact upload.

## 7. Configuration blockers / current production state

- Credentials for the deployed app (`LUMINA_E2E_EMAIL`, `LUMINA_E2E_PASSWORD`)
  exist only as GitHub Actions secrets (`.github/workflows/render-e2e.yml`) —
  they are not available in the local environment, so authenticated production
  tests run in CI; locally those tests are skipped (never faked).
- `GROQ_API_KEY` is SET in `backend/.env` but invalid (all Groq calls → 401),
  impacting Mind/Coding LLM calls locally. `groq_configured` is only a
  presence indicator, not a validity check.
- Production `/api/health` at commit `6f2bcc8`: `status=ok, backend=ok,
  version=0.1.0, provider_active=gemini`.

## 8. Evidence from prior phases (context)

- Local hermetic Mind e2e: 10/10 (approve=real delete→404, decline=doc
  kept→200, persistence via reopen). Groq acceptance: 5/5 with real
  orchestration side effects but all 8 Groq LLM calls → 401.
- `scripts/run_local_e2e.py` / `run_production_audit_e2e.py` isolate state via
  `LUMINA_MIND_STATE_DIR`, `LUMINA_ADVISOR_STATE_DIR`, `LUMINA_SQLITE_PATH`;
  the audit runner pins Ollama to a blocked port and greps the backend log for
  tracebacks + `api.groq.com` evidence. Not used by the gate itself.

## 9. Gate implementation

- `e2e/production-validation.spec.js` — Tests 1a (unauthenticated rejection),
  1b (real login + session + logout), 2 (Mind persistence across reload), 3
  (Documents via real interface + preview download), 4 (Code Builder V2 safe
  decline via Cancel), 5 (deployed health/commit evidence). Credential-gated
  tests skip locally (no secrets) and run in CI via `render-e2e.yml`.
- `e2e/helpers/lumina.js` additions: `installBrowserDiagnostics` (page
  errors / console errors / failed requests / ≥400 responses with sanitized
  bodies), `authenticatedFetch` (text+content-type variant), `fetchHealth`,
  plus origin fallback to the production API.
- Failure behavior: every failure attaches trace, screenshot, browser-network
  diagnostics, and (where set) a sanitized JSON evidence attachment. TEST 4
  fails honestly (never fakes success) if production planning fails instead of
  reaching `awaiting_approval`.
- No approval/execute is ever issued in production; TEST 4 only exercises
  `POST /api/code-builder-v2/tasks/{id}/cancel`.
- Verified against live production on this date: TEST 1a and TEST 5 pass (2/2);
  the four credential-gated tests skip locally as designed.
