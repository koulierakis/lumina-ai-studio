# Lumina AI Desktop — Product Requirements Doc

## Original problem statement (verbatim summary)
Desktop-first (Windows / Chrome / Edge) AI Image Studio for personal use.
Three-column workspace (sidebar / canvas / control panel), luxury dark UI, warm
gold accents. Private single-owner authentication. Identity-preserving image
generation from up to 5 uploaded reference photographs — preserves face, hair,
grey hair, wrinkles, skin texture, natural age. Reusable Identity Packs.
Full AI Image Editor with basic + AI edits. Private gallery, projects, export.
Modular AI provider layer (Gemini / OpenAI / Flux / fal.ai / Runway / Kling).
Portable — packageable later as Tauri or Electron Windows app.

## User persona
- **Owner (only user)** — private personal user who owns the instance. No public
  signup, no other users, no social features.

## Architecture (implemented)
- FastAPI backend, Motor + MongoDB, JWT auth, local disk private storage.
- React 19 SPA with react-resizable-panels for the three-column desktop layout.
- Provider registry in `/app/backend/providers/` — Gemini adapter active,
  slots for OpenAI / Flux / fal.ai / Runway / Kling.
- All AI calls proxied through backend; API keys never touch the browser.

## Core requirements (static)
- Single-owner private access.
- Modular provider layer.
- Identity-preserving generation.
- Reusable Identity Packs (≤5 refs each).
- Private gallery.
- Fully local storage (no accidental public URLs).
- Portable / package-able for Windows.

## Completed in Sprint 3 (2026-02) — AI Editing, Masks, Text Layers, Clipboard
- Freehand + rectangular mask overlay with brush size / hardness / opacity /
  feather / invert / clear / undo/redo / session-persisted.
- 14 AI editing tools via Gemini edit() (retouch, enhance, upscale, sharpen,
  remove/replace/blur background, change clothing, change location,
  remove/replace object, outpaint, relight, restore).
- Async `AiEditJob` state machine (queued/processing/completed/failed/canceled)
  with retry + cancel; jobs survive browser refresh; canceled jobs are protected
  from race with the running background task via conditional Mongo update.
- Non-destructive: every AI edit creates new MediaAsset(kind=edited,
  parent_media_id=source) + Gallery entry; original bytes byte-for-byte
  preserved.
- Multi-layer text: font family, size, bold/italic/underline, align, color,
  opacity, rotation, letter-spacing, line-height, shadow, outline, background
  box (Greek + English fully supported). Drag/resize/rotate handles on canvas,
  Delete removes selected, Esc deselects. Included in undo/redo, autosave,
  Save Version, and export.
- Clipboard paste (Ctrl+V outside text fields) — image uploaded to a Clipboard
  identity pack and opened as a new editor source; text-input paste unaffected.

## Completed in Sprint 2 (2026-02) — Professional Image Editor Foundation
- Editor page `/studio/editor/:mediaId` with luxury 3-column workspace.
- Zoom (buttons + `+/-`), pan (drag), fit (`0`), actual pixels (`1`).
- Transforms: rotate ±90°, straighten fine (±45°), flip H/V, crop with 6 aspect
  presets (Free / 1:1 / 16:9 / 9:16 / 4:5 / 3:2), apply/clear/remove crop.
- 17 manual adjustment sliders (light/color/detail/effects) with numeric input +
  per-control + all-adjustments reset.
- 10 filter presets with live thumbnail previews + intensity slider + custom
  presets stored in localStorage.
- Non-destructive edits: Save Version creates a new MediaAsset(kind=edited,
  parent_media_id=source) + Gallery entry; original never mutated.
- History with jump-to-past, Reset All, Undo/Redo (up to 100 entries).
- Before/After: hold-to-compare + split-view compare slider.
- Autosave to backend `PUT /api/editor/sessions/:mediaId` + localStorage mirror;
  session restored on reopen.
- Export: PNG / JPEG / WEBP with quality slider, canvas-rendered at full source
  resolution.
- Keyboard shortcuts: Ctrl+Z, Ctrl+Shift+Z, Ctrl+Y, Ctrl+S, +/-, 0, 1, Esc.

Backend additions:
- `POST /api/editor/versions` (multipart)
- `GET  /api/editor/versions/{media_id}`
- `GET / PUT / DELETE /api/editor/sessions/{media_id}`
- MediaAsset now carries `parent_media_id` + `edit_note`.

## Completed in Phase 1 (2026-02)
- Private JWT auth (single owner, env-configured).
- Identity Packs: create, upload, primary, delete, cascade delete.
- Gemini Nano Banana identity-preserving generation (prompt + negative +
  scene preset + outfit preset + 5 aspect ratios + 1–4 outputs).
- Async background job runner with polling.
- Private Gallery: list, favorite, download, full-screen viewer, delete.
- Luxury dark three-column desktop UI.
- 100% backend test pass (auth, identity packs, generation, gallery, cascade).

## Prioritized backlog

### P0 (Phase 2 next)
- Full AI Image Editor
  - Basic transforms: crop, resize, rotate, straighten, flip, aspect presets.
  - Manual adjustments: exposure, contrast, saturation, warmth, tint, sharpness,
    clarity, blur, vignette, opacity.
  - Filters (natural, cinematic, warm, cool, B/W, high contrast, vintage,
    portrait, custom save).
  - Text overlays (multi-layer, font, size, alignment, rotation, opacity,
    shadow, outline, box, Greek + English).
  - AI edits: identity-safe retouch, background remove / replace / blur,
    change clothes / location, remove / replace object, extend canvas, relight,
    restore.
- Projects: create / rename / delete, move images between projects, autosave
  editor state.
- Non-destructive editing pipeline: undo / redo / history, save as new version,
  before/after compare.

### P1
- Advanced export presets (social size presets, EXIF strip, filename templates,
  copy-to-clipboard).
- Keyboard shortcuts (Ctrl+Z, Ctrl+Shift+Z, Ctrl+S, Ctrl+O, Ctrl+V paste,
  Delete, Escape, arrows in gallery).
- Trash / restore + bulk actions in gallery.
- Reference photo reorder + duplicate pack.

### P2
- Additional providers (OpenAI GPT-Image-1, Flux, fal.ai, Runway, Kling).
- Windows packaging via Tauri (or Electron fallback).
- Optional cloud object storage adapter (S3 / GCS) as swap for local disk.

## What's mocked / pending / requires external keys
- Nothing mocked. All flows use real Gemini via Emergent Universal Key.
- `AI Image Editor`, `Projects`, `Settings` sidebar entries render explicit
  `Coming Soon` placeholders — no fake features.

## Next tasks
1. Implement AI Image Editor (basic transforms + manual adjustments first).
2. Implement Projects.
3. Add keyboard shortcuts and advanced export.
4. Add OpenAI GPT-Image-1 provider adapter.
5. Windows Tauri packaging.
