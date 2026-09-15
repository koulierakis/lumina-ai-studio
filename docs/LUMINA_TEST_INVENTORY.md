# LUMINA automated test inventory

Source of truth: `frontend/src/platform/moduleRegistry.js` on `work/documents-mind-completion`.

| Module | Route | Primary frontend | Primary backend / provider area |
|---|---|---|---|
| Control Center | `/studio/dashboard` | `frontend/src/pages/Dashboard.jsx` | `backend/runtime_info.py`, `backend/server.py` |
| LUMINA Mind | `/studio/mind` | `frontend/src/pages/ExecutiveAdvisor.jsx`, `frontend/src/platform/speechTranscript.js`, `studioHandoff.js` | `backend/ai_runtime/advisor.py`, `router.py` |
| Code Builder V2 | `/studio/code-builder-v2` | `frontend/src/pages/CodeBuilderV2.jsx` | `backend/code_builder_v2/` |
| Image Studio | `/studio/generate` | `frontend/src/pages/Generate.jsx` | `backend/providers/` |
| AI Image Editor | `/studio/editor` | `frontend/src/pages/Editor.jsx`, `frontend/src/editor/` | `backend/server.py` |
| Video Studio | `/studio/video-studio` | `frontend/src/pages/VideoStudio.jsx`, `frontend/src/video/` | `backend/video_providers/` |
| Voice Studio | `/studio/voice-studio` | `frontend/src/pages/VoiceStudio.jsx` | `backend/voice_providers/`, `backend/openvoice_service.py` |
| Identity Packs | `/studio/identity` | `frontend/src/pages/IdentityPacks.jsx` | `backend/server.py` |
| Documents | `/studio/documents` | `frontend/src/pages/DocumentStudio.jsx`, `frontend/src/documents/`, `components/documentstudio/` | `backend/document_studio/` |
| Media Library | `/studio/media-library` | `frontend/src/pages/Gallery.jsx` | `backend/storage.py`, `storage_backends.py` |
| Jobs Center | `/studio/jobs` | `frontend/src/pages/ProductivityCenter.jsx` | `backend/productivity_router.py` |
| Notifications | `/studio/notifications` | `frontend/src/pages/ProductivityCenter.jsx` | `backend/productivity_router.py` |
| Projects | `/studio/projects` | `frontend/src/pages/WorkspaceCenter.jsx`, `ProjectDetail.jsx` | `backend/platform_services.py` |
| Settings | `/studio/settings` | `frontend/src/pages/PlatformHub.jsx` | `backend/ai_runtime/admin.py` |

Legacy/hidden modules retained in the registry: Code Builder Legacy (`frontend/src/pages/CodeBuilder.jsx`, `backend/code_builder/`) and Developer Center (`frontend/src/pages/DeveloperCenter.jsx`, `backend/developer_center.py`).

Additional separately packaged subsystem: `drive-assistant/` with its own Node smoke/feature gates and backend support in `backend/driver_assistance_services.py`.

## Pipeline policy

The CI pipeline runs deterministic backend pytest coverage, frontend Jest/CRA coverage, production frontend build, Drive Assistant gates, and a CodeQL scan. Provider tests must mock paid/external providers unless an explicit authenticated runtime test is requested. Browser production tests remain separate because the deployed LUMINA requires authentication.
