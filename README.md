# Lumina AI Desktop

A private, desktop-first AI Image Studio for identity-preserving image generation.
Runs in Chrome / Edge on Windows. Prepared for later packaging as a Tauri or Electron
desktop application without changing the core.

## Stack

- **Frontend**: React 19 + React Router 7 + Tailwind + shadcn UI + `react-resizable-panels`
- **Backend**: FastAPI + Motor (MongoDB async) + JWT auth
- **AI provider**: Gemini Nano Banana (`gemini-3.1-flash-image-preview`) via
  `emergentintegrations` and the Emergent Universal Key. Modular provider registry
  so OpenAI / Flux / fal.ai / Runway / Kling can be added later without touching
  route code.
- **Storage**: private local filesystem (`backend/storage/`), served through
  authenticated `/api/media/{id}` endpoint.

## Quickstart (in this container)

```
# Backend (auto-started by supervisor at :8001)
sudo supervisorctl restart backend
# Frontend (auto-started by supervisor at :3000)
sudo supervisorctl restart frontend
```

Open the local frontend URL and log in with the credentials configured in
`backend/.env`.

### Local port-8000 troubleshooting

The automated suite never uses port 8000. If local development has duplicate
listeners, inspect them with `netstat -ano | findstr :8000`, stop only the
processes you own, then start one backend instance from `backend/` with
`python -m uvicorn server:app --host 127.0.0.1 --port 8000`. Verify
`GET /api/health` and then `POST /api/auth/login` using the credentials in the
local backend `.env`. Avoid starting multiple reloaders for the same port.

## Owner credentials

Configured via environment variables in `backend/.env`:

- `OWNER_EMAIL=owner@lumina.local`
- `OWNER_PASSWORD_HASH=<bcrypt hash>`

Generate a hash with `python -c "from auth import hash_password; print(hash_password(input()))"`
from the backend directory. `OWNER_PASSWORD` remains supported only for backward
compatibility. Remove it after configuring the hash. No public signup exists.

Failed logins are limited to 5 attempts per client in 15 minutes by default.
Tune this with `LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_SECONDS`, and
`LOGIN_BLOCK_SECONDS`.

## Video Studio

The Video Studio now exposes all supported generation modes and advanced
settings, provides lifecycle progress and controls, and includes a searchable,
sortable private library with favorites, rename, preview, download, duplicate,
and delete actions. The bundled mock provider produces animated GIF previews;
real adapters can return MP4/WebM through the same provider contract.

Video Library folders are owner-private organizational locations; collections
are independent reusable groups and support multiple collection memberships per
video. Empty folders and collections persist as explicit Video Studio records.

- Private image-to-motion workspace at `/studio/video-studio`.
- Upload an image, describe the movement, choose 3/5/8 seconds and vertical or
  horizontal output, then preview, download, or delete saved results.
- The `backend/video_providers` contract keeps engines replaceable. The included
  `mock` engine produces a local animated GIF motion preview with no credentials;
  future adapters can return MP4/WebM without changing the user interface.

## Phase 1 features (implemented)

## Control Center

The default route is `/studio/dashboard`: a private, premium workspace overview
with immediate access to every Lumina studio. It shows current tasks, recent
gallery files, active generation jobs, video-project count, provider readiness,
system messages, and context-aware next actions. Its widget registry is ready
for later user-customizable layout preferences.

## Central platform foundation

LUMINA now has a shared module registry used by the primary navigation, an
owner-private Projects foundation at `/studio/projects`, and central APIs for
workspace overview, cross-module job aggregation, owner-private search, and
safe settings readiness. The platform never returns secret values; provider and
security diagnostics expose only readiness state.

Projects now support status, archive/restore, tags, descriptions, linked work,
notes, exports and a private activity history. Workspace Search is debounced and
grouped by result type; Settings separates safe editable preferences from
read-only diagnostics.

Shared platform services now include owner-private Media Library metadata,
unified Jobs Center aggregation, persisted notifications, and a Ctrl+K command
palette that searches modules and private workspace results.

Shared navigation now exposes Media Library, Jobs Center, and Notifications as
authenticated central pages.

## Developer Center (local only)

Open `http://127.0.0.1:3000/studio/developer` after signing in. The page is
available only to the LUMINA owner and monitors local application activity:
system health, repository changes, local test/build tasks, retained sanitized
logs, and active media jobs. It never observes remote Codex or ChatGPT cloud
task execution.

The Developer Center can run only predefined local actions: backend tests,
frontend tests, frontend production build, Python compilation, backend/frontend
health checks, and repository refresh. It cannot accept arbitrary commands.

- Private single-owner login (JWT, 30-day sessions)
- **Identity Packs**: create, upload up to 5 reference photos (drag & drop or picker),
  select primary photo, delete photos, delete pack
- **Identity-preserving generation** with Gemini Nano Banana:
  prompt + negative + scene preset + outfit preset + aspect ratio (1:1, 16:9, 9:16,
  4:5, 3:2) + 1–4 outputs, all reference photos passed to the model,
  strong system prompt to preserve facial structure / hairline / skin texture / age
- **Private Gallery**: masonry grid, favorite, full-screen viewer, download, delete,
  filter by favorites
- **Three-column resizable desktop layout** (sidebar / canvas / control panel)

## Sprint 2 features (implemented — professional editor foundation)

- **Editor page** at `/studio/editor/:mediaId` — luxury dark 3-column workspace
  (left tool nav / center canvas / right settings). Open from Gallery via the Edit
  button on hover, or from the Editor landing page.
- **Canvas viewport**: zoom in / out / fit / actual size, pan (drag), image loaded
  through the authenticated `/api/media/:id` endpoint.
- **Transforms**: rotate ±90°, straighten (fine ±45°), flip horizontal / vertical,
  crop with aspect-ratio presets (Off / Free / 1:1 / 16:9 / 9:16 / 4:5 / 3:2) via
  drag-to-select overlay.
- **Manual adjustments** (17 sliders with numeric input + per-control reset):
  exposure, brightness, contrast, highlights, shadows, whites, blacks,
  temperature, tint, saturation, vibrance, sharpness, clarity, dehaze, blur,
  vignette, opacity. Real-time preview via CSS filter + colored overlays; final
  export renders pixel-perfect through Canvas 2D `ctx.filter` at native resolution.
- **Filter presets** (10, incl. `None`): Natural, Portrait, Cinematic, Warm,
  Cool, Vintage, Black & White, Matte, Film. Live thumbnail previews. Intensity
  slider (0–100%). Custom user presets saved locally.
- **Non-destructive editing**: all edits live in state; the original media is
  never touched. Save Version writes a new `MediaAsset` (kind=`edited`,
  `parent_media_id` = source) plus a Gallery entry — the original stays intact.
- **History**: undo / redo (Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y), jump-to-past history
  panel, Reset All, per-adjustment Reset.
- **Before/After**: hold-to-compare button + split-view compare slider.
- **Autosave & session recovery**: state written to localStorage on every change
  and mirrored to the backend at `/api/editor/sessions/:mediaId` (throttled 1.5s).
  Re-opening the same image restores the session.
- **Export**: PNG / JPEG / WEBP with per-format quality control, canvas render at
  full resolution. Save Version uploads back into the Gallery.
- **Keyboard shortcuts**: Ctrl+Z / Ctrl+Shift+Z (undo/redo), Ctrl+S (save
  version), `+` / `-` (zoom), `0` (fit), `1` (actual), `Esc` (cancel crop / close).

## Sprint 3 features (implemented — AI editing, masks & text layers)

- **Freehand & rectangular mask overlay** on the source image, with brush size /
  hardness / opacity, feather (blur mask), invert, clear, show/hide, undo/redo,
  session persistence, restore after refresh. Mask lives at the source's native
  resolution and is uploaded to the backend as a PNG when running AI edits.
- **14 AI editing tools** wired through the Gemini provider (identity-safe retouch,
  enhance, upscale, sharpen, remove background, replace background, blur
  background, change clothing, change location, remove object, replace object,
  outpaint / extend, relight, restore). Each tool sends a tool-specific system
  prompt + user instruction + optional Identity Pack + optional mask.
- **AI edit job system** — `AiEditJob` with states queued / processing /
  completed / failed / canceled + retry endpoint. Jobs survive browser refresh
  (persisted in Mongo). Completed jobs produce a new `MediaAsset(kind=edited,
  parent_media_id=source)` + Gallery entry, original untouched.
- **Text layers** — multi-layer non-destructive text with:
  - add, edit, duplicate, delete, reorder, show/hide, lock/unlock
  - font family, size, bold, italic, underline, alignment
  - color, opacity, rotation, letter-spacing, line-height
  - shadow, outline, background box (color + opacity + radius + padding)
  - drag to move, resize handle, rotation handle on canvas
  - Delete key removes selected layer, Escape deselects
  - Greek + English (Cormorant + Outfit + 7 system families available)
  - included in undo/redo, autosave, Save Version, export.
- **Clipboard paste** (Ctrl+V outside any input) — image on the clipboard is
  uploaded and opened as a new editor source. Non-image clipboard content is
  ignored; text input paste keeps working.
- **Non-destructive guarantee** — every AI edit and every Save Version creates a
  new MediaAsset linked to the parent. Byte-for-byte parent preservation is
  verified in tests.

### Provider capability matrix (Gemini Nano Banana, active)

| Tool                | Status                | Notes                                                    |
| ------------------- | --------------------- | -------------------------------------------------------- |
| Identity-safe retouch | Working              | Best with an attached Identity Pack.                     |
| Enhance             | Working                | Good general purpose.                                    |
| Upscale             | Working (best-effort)  | Result resolution depends on the model.                  |
| Improve sharpness   | Working                |                                                          |
| Remove background   | Working (limited)      | Model does not always return true transparent PNG.       |
| Replace background  | Working                | Requires clear text instruction.                         |
| Blur background     | Working                |                                                          |
| Change clothing     | Working                | Attach Identity Pack for best results.                   |
| Change location     | Working                | Attach Identity Pack.                                    |
| Remove object       | Working (needs mask)   | Draw mask over the object for best result.               |
| Replace object      | Working (needs mask)   | Mask + prompt describing replacement.                    |
| Extend / outpaint   | Best-effort            | Aspect ratio not always exact — model dependent.         |
| Relight             | Working                |                                                          |
| Restore             | Working (best-effort)  | Model-limited for very degraded inputs.                  |

## Further production milestones

- Named image projects and organization.
- Advanced export presets, trash / restore, and bulk operations.
- Additional providers (OpenAI GPT-Image-1, Flux, fal.ai) — adapter slots exist

## API summary

Auth
- `POST /api/auth/login` → `{access_token, email}`
- `GET  /api/auth/me`

Identity Packs
- `POST /api/identity-packs`
- `GET  /api/identity-packs`
- `GET  /api/identity-packs/{id}`
- `PATCH /api/identity-packs/{id}`
- `DELETE /api/identity-packs/{id}`
- `POST /api/identity-packs/{id}/photos` (multipart)
- `DELETE /api/identity-packs/{id}/photos/{photo_id}`

Media
- `GET /api/media/{id}` (private, auth required)

Editor
- `POST /api/editor/versions` (multipart: `source_media_id`, `edit_note`, `file`)
  → new `MediaAsset(kind=edited, parent_media_id=source)` + Gallery entry
- `GET  /api/editor/versions/{media_id}` — list edited versions of a source image
- `GET  /api/editor/sessions/{media_id}` — restore autosaved session
- `PUT  /api/editor/sessions/{media_id}` — upsert session (body: `{state}`)
- `DELETE /api/editor/sessions/{media_id}` — clear session

AI Editing (Sprint 3)
- `GET  /api/editor/ai-tools` — catalog + active provider
- `POST /api/editor/ai-edit` (multipart: `source_media_id`, `tool`, `instruction`,
  optional `identity_pack_id`, optional `mask` PNG) → creates `AiEditJob`
- `GET  /api/editor/ai-jobs/{id}` — poll status
- `GET  /api/editor/ai-jobs?source_media_id=...` — list per source
- `POST /api/editor/ai-jobs/{id}/retry` — retry failed / canceled job
- `POST /api/editor/ai-jobs/{id}/cancel` — cancel queued or processing job

Generation
- `POST /api/generate` → creates job, returns `GenerationJob`
- `GET  /api/jobs/{id}`
- `GET  /api/jobs`

Gallery
- `GET /api/gallery`
- `PATCH /api/gallery/{id}` (favorite)
- `DELETE /api/gallery/{id}`

Utility
- `GET /api/health`
- `GET /api/providers`

## Environment variables

See `.env.example`. All secrets stay server-side.

### Video Studio providers

Video Studio defaults to the local `mock` provider and remains usable without paid credentials. A production Luma Dream Machine adapter is included for asynchronous native MP4 generation. Set `VIDEO_PROVIDER=luma` and `LUMA_API_KEY` only in `backend/.env`; the key is never returned by the API or sent to the frontend. Luma supports text-to-video and image-to-video in this adapter. Image-to-video additionally requires `LUMA_IMAGE_URL_BASE`, a controlled HTTPS CDN prefix serving immutable source images by filename. The provider catalog exposes only configured providers and their modes, resolutions, durations, aspect ratios, output formats, cancellation and input limits. Provider video URLs are downloaded and stored privately in LUMINA before a job completes.

Luma usage and billing are the responsibility of the Luma account that owns `LUMA_API_KEY`. Keep the mock provider for local testing; it produces an animated GIF, not an MP4/WebM.

### Voice Studio

Voice Studio provides authenticated audio jobs, private audio storage, favorites, tags, folders and collections. The default local mock engine creates a valid WAV preview (24 kHz mono) for development. The provider-neutral catalog reserves ElevenLabs, OpenAI, Google, Azure and Cartesia adapters without exposing credentials. Real speech, transcription, cloning and audio-processing adapters require provider credentials and production verification before they are enabled.

Voice Packs are owner-private, consent-gated records for voice samples. Creating one requires an ownership declaration; samples are stored privately and are removed with the pack. ElevenLabs is the selected future cloning adapter and HeyGen the selected future talking-face adapter, but neither is connected or verified in this workspace.

## Storage layout

```
backend/storage/
  references/  # reference photos (identity packs)
  generated/   # AI-generated outputs
```

Files are only served through the authenticated `/api/media/{id}` endpoint.
