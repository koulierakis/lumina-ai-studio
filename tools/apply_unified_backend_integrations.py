from __future__ import annotations

from pathlib import Path

from apply_personal_voice_integration import BACKEND_BLOCK, BACKEND_MARKER

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "backend" / "server.py"
PERSISTENCE = ROOT / "backend" / "persistence.py"
VOICE_UI = ROOT / "frontend" / "src" / "pages" / "VoiceStudio.jsx"

CENTRAL_MARKER = "# ---------- Central platform: projects, unified work, search and settings ----------"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not find {label} anchor")
    return text.replace(old, new, 1)


def patch_server() -> bool:
    text = SERVER.read_text(encoding="utf-8")
    original = text

    if BACKEND_MARKER not in text:
        if CENTRAL_MARKER not in text:
            raise RuntimeError("Could not find Personal Voice backend insertion marker")
        text = text.replace(CENTRAL_MARKER, BACKEND_BLOCK + "\n" + CENTRAL_MARKER, 1)

    text = replace_once(
        text,
        "from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus  # noqa: E402\n",
        "from ai_runtime.schemas import RuntimeJob, RuntimeJobStatus  # noqa: E402\nfrom mentor import configure_mentor, router as mentor_router  # noqa: E402\n",
        "Mentor import",
    )
    text = replace_once(
        text,
        'notifications_coll = LocalPersistenceCollection(persistence_provider, "notifications")\n',
        'notifications_coll = LocalPersistenceCollection(persistence_provider, "notifications")\nmentor_sessions_coll = LocalPersistenceCollection(persistence_provider, "mentor_sessions")\n',
        "Mentor collection",
    )
    text = replace_once(
        text,
        "configure_document_studio_router(persistence_provider, media_coll, notifications_coll)\n",
        "configure_document_studio_router(persistence_provider, media_coll, notifications_coll)\nconfigure_mentor(sessions_collection=mentor_sessions_coll, model=str(runtime_config[\"preferred_ollama_model\"]))\n",
        "Mentor configuration",
    )
    text = replace_once(
        text,
        "app.include_router(runtime_router)\n",
        "app.include_router(runtime_router)\napp.include_router(mentor_router)\n",
        "Mentor router include",
    )

    if text != original:
        SERVER.write_text(text, encoding="utf-8")
        return True
    return False


def patch_persistence() -> bool:
    text = PERSISTENCE.read_text(encoding="utf-8")
    original = text
    if '"mentor_sessions"' not in text:
        anchor = '        "provider_status",\n'
        if anchor not in text:
            raise RuntimeError("Could not find SQLite table registry anchor")
        text = text.replace(anchor, '        "provider_status", "mentor_sessions",\n', 1)
    if text != original:
        PERSISTENCE.write_text(text, encoding="utf-8")
        return True
    return False


def patch_voice_ui() -> bool:
    text = VOICE_UI.read_text(encoding="utf-8")
    original = text

    import_line = "import PersonalVoiceStudio from './PersonalVoiceStudio';"
    if import_line not in text:
        anchor = "import { apiDelete, apiGet, apiPatch, apiPost, uploadFormData } from '../lib/api';"
        if anchor not in text:
            raise RuntimeError("Could not find Voice Studio import anchor")
        text = text.replace(anchor, anchor + "\n" + import_line, 1)

    old_tabs = "export const VOICE_TABS=['Generate Speech','Voice Packs','Record Voice','Transcribe','Talking Video','Jobs','Audio Library','Settings'];"
    new_tabs = "export const VOICE_TABS=['Generate Speech','My Voice','Voice Packs','Record Voice','Transcribe','Talking Video','Jobs','Audio Library','Settings'];"
    if old_tabs in text:
        text = text.replace(old_tabs, new_tabs, 1)
    elif "'My Voice'" not in text:
        raise RuntimeError("Could not find Voice Studio tab anchor")

    old_router = "function Tab({tab,packs,jobs,reload}){if(tab==='Generate Speech')return <Generate reload={reload}/>;if(tab==='Voice Packs')return <Packs packs={packs} reload={reload}/>;"
    new_router = "function Tab({tab,packs,jobs,reload}){if(tab==='Generate Speech')return <Generate reload={reload}/>;if(tab==='My Voice')return <PersonalVoiceStudio packs={packs} reload={reload}/>;if(tab==='Voice Packs')return <Packs packs={packs} reload={reload}/>;"
    if old_router in text:
        text = text.replace(old_router, new_router, 1)
    elif "<PersonalVoiceStudio" not in text:
        raise RuntimeError("Could not find Voice Studio router anchor")

    if text != original:
        VOICE_UI.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    changes = {
        "server": patch_server(),
        "persistence": patch_persistence(),
        "voice_ui": patch_voice_ui(),
    }
    print("UNIFIED BACKEND INTEGRATIONS APPLIED", changes)


if __name__ == "__main__":
    main()
