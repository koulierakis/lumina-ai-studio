from pathlib import Path

SERVER = Path("backend/server.py")
text = SERVER.read_text(encoding="utf-8")

old_import = "from voice_providers import get_voice_provider, voice_provider_catalog  # noqa: E402\n"
new_import = old_import + "from voice_providers.openvoice_v2 import OpenVoiceV2ToneConverter, ToneConversionError  # noqa: E402\n"
if "from voice_providers.openvoice_v2 import" not in text:
    if old_import not in text:
        raise SystemExit("voice provider import anchor not found")
    text = text.replace(old_import, new_import, 1)

old_block = '''        (data, mime, metadata), runtime_job = await _runtime_execute(owner, "voice", task_type, job.provider, {"mode": job.mode, "title": job.title, "format": job.output_format, "voice_pack_id": job.voice_pack_id}, voice_executor)
        audio_metadata = _probe_audio_bytes(data, mime)
        filename, _, size = save_bytes(data, mime, kind="generated")
        media = MediaAsset(owner_email=owner, filename=filename, mime_type=mime, kind="generated", source_module="voice", size_bytes=size, edit_note=f"voice-studio:{job.provider}")
        await media_coll.insert_one(media.model_dump())
        await voice_jobs_coll.update_one({"id": job_id, "owner_email": owner}, {"$set": {"status": "completed", "progress": 100, "output_media_id": media.id, "metadata": {**(job.metadata or {}), **metadata, **audio_metadata, "runtime_job_id": runtime_job.id, "base_audio_media_id": media.id, "personal_voice_ready_for_conversion": bool(job.voice_pack_id)}, "updated_at": now_iso()}})
'''

new_block = '''        (data, mime, metadata), runtime_job = await _runtime_execute(owner, "voice", task_type, job.provider, {"mode": job.mode, "title": job.title, "format": job.output_format, "voice_pack_id": job.voice_pack_id}, voice_executor)
        final_data, final_mime = data, mime
        final_provider = job.provider
        conversion_metadata = {}

        if job.voice_pack_id:
            reference_media_id = (job.metadata or {}).get("reference_sample_media_id")
            reference_media = await media_coll.find_one({"id": reference_media_id, "owner_email": owner}, {"_id": 0})
            if not reference_media:
                raise RuntimeError("Personal Voice reference sample is unavailable.")
            reference_data = read_bytes(reference_media["filename"], kind="reference")
            converter = OpenVoiceV2ToneConverter.from_env()
            conversion_metadata = {
                "tone_converter": "openvoice-v2",
                "tone_conversion_status": "pending",
                "reference_sample_media_id": reference_media_id,
                "base_tts_provider": "edge-tts",
            }
            if converter.configured:
                await voice_jobs_coll.update_one(
                    {"id": job_id, "owner_email": owner},
                    {"$set": {"progress": 80, "metadata": {**(job.metadata or {}), **conversion_metadata}, "updated_at": now_iso()}},
                )
                try:
                    converted = await converter.convert(
                        source_audio=data,
                        source_mime=mime,
                        reference_audio=reference_data,
                        reference_mime=reference_media.get("mime_type") or "audio/wav",
                        output_format=job.output_format,
                    )
                    final_data, final_mime = converted.audio, converted.mime_type
                    final_provider = "edge-tts+openvoice-v2"
                    conversion_metadata.update(converted.metadata)
                    conversion_metadata.update({
                        "tone_conversion_status": "completed",
                        "tone_conversion_applied": True,
                    })
                except ToneConversionError as exc:
                    if converter.required:
                        raise
                    logger.warning("OpenVoice V2 unavailable for voice job %s (%s); returning explicit Edge TTS fallback", job_id, exc.code)
                    final_provider = "edge-tts-fallback"
                    conversion_metadata.update({
                        "tone_conversion_status": "fallback",
                        "tone_conversion_applied": False,
                        "tone_conversion_error": exc.code,
                    })
            else:
                if converter.required:
                    raise ToneConversionError("not_configured", "OpenVoice V2 endpoint is not configured.")
                final_provider = "edge-tts-fallback"
                conversion_metadata.update({
                    "tone_conversion_status": "fallback",
                    "tone_conversion_applied": False,
                    "tone_conversion_error": "not_configured",
                })

        audio_metadata = _probe_audio_bytes(final_data, final_mime)
        filename, _, size = save_bytes(final_data, final_mime, kind="generated")
        media = MediaAsset(
            owner_email=owner,
            filename=filename,
            mime_type=final_mime,
            kind="generated",
            source_module="voice",
            size_bytes=size,
            edit_note=f"voice-studio:{final_provider}",
            metadata={
                "base_tts_provider": "edge-tts" if job.voice_pack_id else job.provider,
                "final_voice_provider": final_provider,
                **conversion_metadata,
            },
        )
        await media_coll.insert_one(media.model_dump())
        await voice_jobs_coll.update_one(
            {"id": job_id, "owner_email": owner},
            {"$set": {
                "status": "completed",
                "progress": 100,
                "provider": final_provider,
                "output_media_id": media.id,
                "metadata": {
                    **(job.metadata or {}),
                    **metadata,
                    **conversion_metadata,
                    **audio_metadata,
                    "runtime_job_id": runtime_job.id,
                    "final_audio_media_id": media.id,
                    "personal_voice_ready_for_conversion": False,
                },
                "updated_at": now_iso(),
            }},
        )
'''

if old_block in text:
    text = text.replace(old_block, new_block, 1)
elif 'final_provider = "edge-tts+openvoice-v2"' not in text:
    raise SystemExit("voice execution block anchor not found")

SERVER.write_text(text, encoding="utf-8")
print("OpenVoice V2 pipeline patch applied")
