# Base44 Dev Environment — Lumina AI Desktop

## Stack
- **Frontend**: React 18 + CRA (`react-scripts` 5) wrapped by **craco**, Tailwind, React Router 7. Served by the CRA dev server on port **3000** (the Base44 preview entry). Requires **Node >= 20** (react-router 7.15 needs it).
- **Backend**: FastAPI + uvicorn on internal port **8000**. Uses **SQLite** (`/app/.lumina-runtime/database/lumina.db`) for persistence — **no MongoDB is required to boot** despite `motor`/`pymongo` in requirements. Local file storage under `backend/storage/`.
- Single-owner JWT auth, but the frontend ships in **local-owner-mode** (`src/context/AuthContext.jsx`) — it auto-logs in as `owner@lumina.local` and never calls `/api/auth/login`, so no credentials are needed to view the app.

## Running
```
docker compose -f docker-compose.base44.yml up -d --build
```
- `backend`: `python:3.11-slim`, bind-mounts the repo, `pip install -r requirements.txt` then `uvicorn server:app --reload`. Health: `GET /api/health`.
- `frontend`: `node:20`, bind-mounts the repo (anonymous volume for `node_modules`), `yarn install` then `yarn start` (craco). Depends on backend being healthy.
- Both pip and yarn installs run in the container command, so the first boot is slow (~1-2 min); restarts reuse the installed deps.

## How the frontend reaches the backend (single origin)
- The frontend's API client (`src/lib/api.js`) uses `REACT_APP_BACKEND_URL` which is **empty** → all calls go to same-origin `/api/*`.
- `frontend/src/setupProxy.js` proxies `/api` → `http://backend:8000` (CRA auto-loads it). Client-side routes (`/studio/...`) are served by the dev server's history fallback, so SPA routing is unaffected.
- The craco config sets `allowedHosts: 'all'` so the dynamic Base44 preview hostname is accepted.
- The backend sets `TRUSTED_HOSTS=*` so proxied requests are never rejected by `TrustedHostMiddleware`.

## Mock providers (no external keys needed)
The compose sets `IMAGE_PROVIDER=mock`, `VIDEO_PROVIDER=mock`, `VOICE_PROVIDER=mock`, `TALKING_FACE_PROVIDER=mock`, and `LUMINA_TEST_PROVIDER=true` so the mock image provider reports as configured. The app is fully interactive without any external API keys. To enable real generation, set `GEMINI_API_KEY` / `OPENAI_API_KEY` via the Base44 secrets dashboard (optional, not required at boot).

## Repo quirks fixed for this environment
- `backend/requirements.txt` was missing **`httpx`** (imported by `backend/code_builder/ollama_service.py`); added `httpx>=0.27.0`.
- `frontend/src/documents/model.js` imported `../runtime/model` which did not exist; created `frontend/src/runtime/model.js` exporting `runtimeStudioJobPayload(studio, taskType, extra)`.

## Verifying it works
- `curl -sf http://localhost:8000/api/health` → backend JSON with `"database": {"provider": "sqlite", "ready": true}`.
- `curl -sf -H "Host: x.preview" http://localhost:3000/` → CRA index.html.
- `curl -sf -H "Host: x.preview" http://localhost:3000/api/health` → proxied backend JSON.
- `curl -sf -H "Host: x.preview" http://localhost:3000/studio/dashboard` → index.html (SPA route).
- `docker compose -f docker-compose.base44.yml ps` → both services Up, backend (healthy).
