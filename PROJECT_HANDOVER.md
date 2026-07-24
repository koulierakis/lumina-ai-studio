# Lumina AI Desktop — Project Handover

This document is written so a new developer (or a future you) can pick the project
up and continue it without any hidden state.

## Repository normalization (2026-07-24)

`C:\Users\User\Desktop\LUMINA` is the single project root. The former nested
`lumina-ai-studio-main` tree was audited, merged, and removed. Its authoritative
backend, tests, authentication hardening, and documentation were preserved;
ten newer valid frontend fixes from the previous root copy were retained.

The repository now has valid Git metadata, comprehensive ignore rules, backend
and frontend environment examples, and a pre-change inventory in
`NORMALIZATION_BACKUP_MANIFEST.md`. Local secrets and generated media remain
untracked. The original archive is preserved under `backups/`.

## 1. What is implemented (Phase 1 + Sprint 2, verified working)

### Phase 1 (previously shipped)
- **Private single-owner authentication** (JWT, 30-day sessions).
- **Identity Packs** (up to 5 reference photos, primary photo, cascade delete).
- **Identity-preserving generation** via Gemini Nano Banana (prompt + negative +
  scene preset + outfit preset + 5 aspect ratios + 1–4 outputs, background job).
- **Private Gallery** (grid, favorite, full-screen viewer, download, delete).
- **Provider registry** with `Gemini` active and slots for OpenAI / Flux / fal.ai /
  Runway / Kling.

### Sprint 2 (new — professional image editor foundation)
- **Editor page** (`/studio/editor/:mediaId`) with a luxury 3-column workspace:
  left tool nav, center canvas, right contextual controls.
- **Canvas viewport**: zoom (mouse wheel via +/- or buttons), pan (drag), fit,
  actual pixels view.
- **Transforms**: rotate ±90°, fine straighten (±45°), flip H / V, crop with
  presets (Free / 1:1 / 16:9 / 9:16 / 4:5 / 3:2) via drag-to-select overlay,
  apply / clear / remove crop.
- **17 manual adjustment sliders** with numeric entry + per-control reset:
  exposure, brightness, contrast, highlights, shadows, whites, blacks,
  temperature, tint, saturation, vibrance, sharpness, clarity, dehaze, blur,
  vignette, opacity. Real-time preview via CSS filter + overlay divs. Export
  uses Canvas 2D with `ctx.filter` for pixel-perfect output at full resolution.
- **10 filter presets** (`None`, Natural, Portrait, Cinematic, Warm, Cool,
  Vintage, Black & White, Matte, Film) with live thumbnail previews, intensity
  slider, and user-saveable custom presets stored locally.
- **Non-destructive** — Save Version writes a new `MediaAsset` with
  `kind=edited` and `parent_media_id=source`. Original never mutated.
- **History**: undo / redo stack (up to 100 steps), jump-to-past history panel,
  Reset All, per-tool reset.
- **Before / After**: hold-to-compare + split-view compare with draggable
  slider.
- **Autosave & session recovery**: state auto-persists to localStorage on every
  change AND is mirrored to backend (`PUT /api/editor/sessions/:mediaId`,
  throttled 1.5s). Reopening the image restores the session across refresh /
  browser restart.
- **Export**: PNG / JPEG / WEBP with per-format quality slider, canvas render at
  full source resolution.
- **Keyboard shortcuts**: Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y (undo/redo), Ctrl+S
  (save version), `+` / `-` (zoom), `0` (fit), `1` (actual), `Esc` (cancel /
  close).

Backend endpoints added in Sprint 2:
- `POST /api/editor/versions` (multipart)
- `GET  /api/editor/versions/{media_id}`
- `GET / PUT / DELETE /api/editor/sessions/{media_id}`

MediaAsset now carries `parent_media_id` + `edit_note` (see `models.py`).

## 2. What is intentionally deferred (Phase 2)

- Full AI Image Editor (crop, adjust, filters, text overlay, background
  removal / replace / blur, relight, upscale, restore) — placeholder page exists.
- Projects (organize images into named projects, autosave editor state) — placeholder.
- Advanced export presets, EXIF stripping, social-media size presets.
- Keyboard shortcuts (Ctrl+Z, Ctrl+S, Ctrl+O, Ctrl+V paste).
- Trash / restore, bulk selection, bulk download.
- Windows packaging via Tauri / Electron (see section 6 below for roadmap).
- Video editing (explicitly out of scope for this build).

## 3. Repository layout

```
LUMINA/
├── backend
│   ├── server.py            # FastAPI app + all routes
│   ├── auth.py              # JWT + owner-only dependency
│   ├── models.py            # Pydantic models
│   ├── storage.py           # local disk media storage
│   ├── providers            # image provider registry
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── gemini_provider.py
│   ├── requirements.txt
│   └── .env                 # secrets (never commit)
├── frontend
│   ├── src
│   │   ├── App.js
│   │   ├── index.css
│   │   ├── context/AuthContext.jsx
│   │   ├── lib/api.js
│   │   ├── components
│   │   │   ├── Sidebar.jsx
│   │   │   ├── StudioLayout.jsx
│   │   │   ├── RequireAuth.jsx
│   │   │   └── AuthImage.jsx
│   │   └── pages
│   │       ├── Login.jsx
│   │       ├── Generate.jsx
│   │       ├── IdentityPacks.jsx
│   │       ├── Gallery.jsx
│   │       └── ComingSoon.jsx
│   ├── package.json
│   └── .env
├── README.md
├── PROJECT_HANDOVER.md
└── .env.example
```

## 4. Local development on Windows

1. Install Python 3.11+, Node 18+, MongoDB, Yarn.
2. Clone repo, then:
   ```
   cd backend
   python -m venv .venv && .venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env
   # edit .env: set OWNER_EMAIL, OWNER_PASSWORD_HASH, provider keys, JWT_SECRET
   uvicorn server:app --host 0.0.0.0 --port 8001 --reload
   ```
3. In another shell:
   ```
   cd frontend
   yarn install
   copy .env.example .env
   # edit .env if the backend is not at http://127.0.0.1:8000
   yarn start
   ```
4. Open http://localhost:3000 in Chrome or Edge, log in with your owner
   credentials.

## 5. Production deployment (outside Emergent)

- Any host that can run Python + Node + MongoDB works: Fly.io, Railway, Render,
  bare Linux VM.
- Serve the built frontend (`yarn build`) behind Nginx on the same origin, or set
  `REACT_APP_BACKEND_URL` to the backend origin and enable CORS.
- Set all secrets via environment variables. Do not commit `.env`.
- Restrict access at the network layer (VPN, Cloudflare Access) since the whole
  application is single-owner private.

## 6. Windows desktop packaging roadmap

The application is already a plain web app talking to a REST backend, so
packaging is a wrapper problem:

- **Tauri (recommended)** — smaller binary, native webview.
  1. `cargo install create-tauri-app`
  2. `npm create tauri-app@latest` inside `frontend`, choose the existing React
     project.
  3. In `tauri.conf.json` set `build.beforeDevCommand=yarn start` and
     `build.beforeBuildCommand=yarn build`.
  4. Bundle the FastAPI backend either as a separate service (Windows service) or
     using `pyinstaller` and launch it as a sidecar via Tauri's `sidecar` feature.

- **Electron** — heavier but well documented.
  1. `yarn add -D electron electron-builder`.
  2. Add a `main.js` that spawns the Python backend and opens a `BrowserWindow`
     pointed at `http://localhost:8001` / the built frontend.
  3. Package with `electron-builder`.

Both approaches require zero changes to the React source or the FastAPI routes.

## 7. Switching AI providers

1. Create a new file under `backend/providers/`, e.g. `openai_provider.py`,
   subclassing `ImageProvider` and implementing `is_configured()` and
   `async generate(spec: GenerationInput) -> List[GeneratedImage]`.
2. Register it in `backend/providers/__init__.py` in the `_REGISTRY` dict.
3. Set `IMAGE_PROVIDER=<key>` in `.env` and restart the backend.

The frontend does not need to change — it calls `/api/generate` and
`/api/providers` uniformly.

## 8. Security notes

- All secrets (provider keys, `JWT_SECRET`, `OWNER_PASSWORD_HASH`) live only in
  `backend/.env`. Frontend never sees them.
- Login failures are throttled per client. The defaults are 5 failures in 15
  minutes followed by a 15-minute block; all three values are configurable.
- Uploads are size-limited (15 MB) and mime-type validated.
- Filenames on disk are random UUIDs; the original filename is never used, so
  path traversal is impossible.
- Media is only served through `/api/media/{id}` which requires the owner's JWT.
- No reference photograph is ever sent to any endpoint other than the configured
  AI provider, and the provider is called through the backend only.
- Emergent Universal Key can be swapped for your own OpenAI / Gemini / Anthropic
  keys at any time.

## 9. Known limitations

- Reference photos are stored on the container's local filesystem. If the
  container is destroyed and there is no volume mount, data is lost. Mount
  `STORAGE_DIR` to a persistent volume in production.
- Aspect ratio in Gemini is a prompt hint — the model may not always return the
  exact requested ratio. Client can crop with the (future) editor.
- No public share URLs by design — everything is private.
- Job progress is coarse-grained (queued / processing / completed / failed); no
  step-by-step progress from the provider.

## 10. Completion report (as of this build)

Implemented and tested end-to-end:
- Login with owner credentials.
- Create Identity Pack, upload references.
- Generate 1–4 images with identity preservation.
- Gallery viewing, favorite, download, delete.

Mocked / pending: nothing critical for Phase 1. AI Editor, Projects, Settings
pages are explicit `Coming Soon` placeholders.

Requires external API key: only `EMERGENT_LLM_KEY` (provided by Emergent
Universal Key). No other third-party keys are used.
