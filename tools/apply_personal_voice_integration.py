from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "backend" / "server.py"
VOICE_UI = ROOT / "frontend" / "src" / "pages" / "VoiceStudio.jsx"

BACKEND_MARKER = "# ---------- Personal Voice / ElevenLabs integration ----------"
CENTRAL_MARKER = "# ---------- Central platform: projects, unified work, search and settings ----------"

BACKEND_BLOCK = r'''
# ---------- Personal Voice / ElevenLabs integration ----------
@api.post("/voice/packs/{pack_id}/clone", response_model=VoicePack)
async def clone_voice_pack(pack_id: str, owner: str = Depends(require_owner)) -> VoicePack:
    """Create one persistent ElevenLabs Instant Voice Clone from saved pack samples."""
    pack = await voice_packs_coll.find_one({"id": pack_id, "owner_email": owner}, {"_id": 0})
    if not pack:
        raise HTTPException(404, "Voice Pack not found")
    if pack.get("provider_voice_id") and pack.get("provider") == "elevenlabs" and pack.get("readiness_status") == "ready":
        return VoicePack(**pack)
    if not pack.get("consent_confirmed") or not str(pack.get("ownership_declaration") or "").strip():
        raise HTTPException(400, "Confirm ownership and consent before creating My Voice.")
    sample_ids = list(pack.get("sample_media_ids") or [])
    if not sample_ids:
        raise HTTPException(400, "Record and save your voice before creating My Voice.")

    provider = get_voice_provider("elevenlabs")
    configured = getattr(provider, "is_configured", lambda: True)()
    if not configured:
        raise HTTPException(409, "ELEVENLABS_API_KEY is not configured.")

    await voice_packs_coll.update_one(
        {"id": pack_id, "owner_email": owner},
        {"$set": {"provider": "elevenlabs", "readiness_status": "provider-pending", "updated_at": now_iso()}},
    )
    try:
        audio_files = []
        extension_for_mime = {
            "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3", "audio/ogg": ".ogg", "audio/webm": ".webm",
        }
        for index, media_id in enumerate(sample_ids, start=1):
            media = await media_coll.find_one({"id": media_id, "owner_email": owner}, {"_id": 0})
            if not media:
                continue
            mime = str(media.get("mime_type") or "audio/webm").lower()
            audio_files.append((f"my-voice-{index}{extension_for_mime.get(mime, '.audio')}", mime, read_bytes(media["filename"], "reference")))
        if not audio_files:
            raise RuntimeError("No readable voice recording was found in this Voice Pack.")

        result = await provider.clone_voice(
            name=str(pack.get("name") or "My Voice"),
            audio_files=audio_files,
            description="Personal voice model created by the owner in LUMINA Voice Studio.",
        )
        status = "provider-pending" if result.get("requires_verification") else "ready"
        await voice_packs_coll.update_one(
            {"id": pack_id, "owner_email": owner},
            {"$set": {
                "provider": "elevenlabs",
                "provider_voice_id": result["voice_id"],
                "readiness_status": status,
                "updated_at": now_iso(),
            }},
        )
    except Exception as exc:
        logger.exception("Personal voice cloning failed: %s", exc)
        await voice_packs_coll.update_one(
            {"id": pack_id, "owner_email": owner},
            {"$set": {"readiness_status": "failed", "updated_at": now_iso()}},
        )
        raise HTTPException(502, "My Voice could not be created. Check the ElevenLabs account/key and the recording, then try again.") from exc

    updated = await voice_packs_coll.find_one({"id": pack_id, "owner_email": owner}, {"_id": 0})
    return VoicePack(**updated)


@api.post("/voice/generate-personal", response_model=VoiceJob)
async def generate_with_personal_voice(
    background: BackgroundTasks,
    pack_id: str = Form(...),
    text: str = Form(...),
    style_prompt: str = Form("Ήρεμα, φυσικά και επαγγελματικά."),
    owner: str = Depends(require_owner),
) -> VoiceJob:
    """Generate any new text with the persistent cloned voice from a Voice Pack."""
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(400, "Enter text to generate speech.")
    pack = await voice_packs_coll.find_one({"id": pack_id, "owner_email": owner}, {"_id": 0})
    if not pack:
        raise HTTPException(404, "Voice Pack not found")
    voice_id = str(pack.get("provider_voice_id") or "").strip()
    if pack.get("provider") != "elevenlabs" or not voice_id or pack.get("readiness_status") != "ready":
        raise HTTPException(409, "My Voice is not ready yet.")
    provider = get_voice_provider("elevenlabs")
    if not getattr(provider, "is_configured", lambda: True)():
        raise HTTPException(409, "ELEVENLABS_API_KEY is not configured.")

    direction = (style_prompt or "calm").strip()[:500]
    job = VoiceJob(
        owner_email=owner,
        provider="elevenlabs",
        mode="text-to-speech",
        text=clean_text,
        voice=voice_id,
        style=direction,
        output_format="mp3",
        sample_rate=44100,
        bitrate="128k",
        title=clean_text[:80] or "My Voice",
        metadata={
            "personal_voice": True,
            "voice_pack_id": pack_id,
            "style_prompt": direction,
            "identity_preservation": True,
        },
    )
    await voice_jobs_coll.insert_one(job.model_dump())
    background.add_task(_run_voice_job, job.id, owner)
    return job

'''


def patch_server() -> bool:
    text = SERVER.read_text(encoding="utf-8")
    if BACKEND_MARKER in text:
        return False
    if CENTRAL_MARKER not in text:
        raise RuntimeError("Could not find the central-platform insertion marker in backend/server.py")
    text = text.replace(CENTRAL_MARKER, BACKEND_BLOCK + "\n" + CENTRAL_MARKER, 1)
    SERVER.write_text(text, encoding="utf-8")
    return True


def patch_frontend() -> bool:
    text = VOICE_UI.read_text(encoding="utf-8")
    changed = False
    import_line = "import PersonalVoiceStudio from './PersonalVoiceStudio';"
    if import_line not in text:
        anchor = "import { apiDelete, apiGet, apiPatch, apiPost, uploadFormData } from '../lib/api';"
        if anchor not in text:
            raise RuntimeError("Could not find VoiceStudio API import anchor")
        text = text.replace(anchor, anchor + "\n" + import_line, 1)
        changed = True

    old_tabs = "export const VOICE_TABS=['Generate Speech','Voice Packs','Record Voice','Transcribe','Talking Video','Jobs','Audio Library','Settings'];"
    new_tabs = "export const VOICE_TABS=['Generate Speech','My Voice','Voice Packs','Record Voice','Transcribe','Talking Video','Jobs','Audio Library','Settings'];"
    if old_tabs in text:
        text = text.replace(old_tabs, new_tabs, 1)
        changed = True
    elif "'My Voice'" not in text:
        raise RuntimeError("Could not find VoiceStudio tab list anchor")

    old_tab_router = "function Tab({tab,packs,jobs,reload}){if(tab==='Generate Speech')return <Generate/>;if(tab==='Voice Packs')return <Packs packs={packs} reload={reload}/>;"
    new_tab_router = "function Tab({tab,packs,jobs,reload}){if(tab==='Generate Speech')return <Generate/>;if(tab==='My Voice')return <PersonalVoiceStudio packs={packs} reload={reload}/>;if(tab==='Voice Packs')return <Packs packs={packs} reload={reload}/>;"
    if old_tab_router in text:
        text = text.replace(old_tab_router, new_tab_router, 1)
        changed = True
    elif "<PersonalVoiceStudio" not in text:
        raise RuntimeError("Could not find VoiceStudio tab router anchor")

    if changed:
        VOICE_UI.write_text(text, encoding="utf-8")
    return changed


def main() -> None:
    server_changed = patch_server()
    frontend_changed = patch_frontend()
    print("PERSONAL VOICE INTEGRATION INSTALLED")
    print(f"backend/server.py: {'updated' if server_changed else 'already installed'}")
    print(f"frontend/src/pages/VoiceStudio.jsx: {'updated' if frontend_changed else 'already installed'}")
    print("Next: restart LUMINA, open Voice Studio > My Voice, record once, then Create My Voice.")


if __name__ == "__main__":
    main()
