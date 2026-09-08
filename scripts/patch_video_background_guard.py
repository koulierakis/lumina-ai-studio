from pathlib import Path

path = Path("backend/server.py")
text = path.read_text(encoding="utf-8")

marker = '\n\n@api.get("/video/providers")\n'
if marker not in text:
    raise SystemExit("video providers marker not found")

wrapper = '''\n\nasync def _run_video_generation_guarded(job_id: str, owner: str) -> None:\n    \"\"\"Catch failures that happen before _run_video_generation reaches its internal try/except.\"\"\"\n    logger.info("Video background job starting job_id=%s owner=%s", job_id, owner)\n    try:\n        await _run_video_generation(job_id, owner)\n    except Exception as exc:\n        logger.exception("Video background job crashed before normal error handling job_id=%s: %s", job_id, exc)\n        try:\n            await video_generation_jobs_coll.update_one(\n                {"id": job_id, "owner_email": owner},\n                {"$set": {\n                    "status": "failed",\n                    "error": getattr(exc, "safe_message", None) or "Video generation could not be started.",\n                    "progress": 0,\n                    "estimated_seconds_remaining": None,\n                    "updated_at": now_iso(),\n                }},\n            )\n        except Exception:\n            logger.exception("Could not persist guarded video failure job_id=%s", job_id)\n'''

if "async def _run_video_generation_guarded(" not in text:
    text = text.replace(marker, wrapper + marker, 1)

old = "background.add_task(_run_video_generation,"
new = "background.add_task(_run_video_generation_guarded,"
count = text.count(old)
if count == 0 and new not in text:
    raise SystemExit("no video background task calls found")
text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print(f"patched {path}; replaced {count} background task call(s)")
