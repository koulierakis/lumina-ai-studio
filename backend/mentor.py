from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any

from auth import require_owner
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/mentor", tags=["Mentor"])

_sessions = None
_default_model = "qwen2.5-coder:7b"
_ollama_base_url = "http://127.0.0.1:11434"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class MentorSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="Mentor Session", min_length=1, max_length=120)
    goal: str = Field(default="", max_length=4000)
    context: str = Field(default="", max_length=12000)


class MentorMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=20000)
    mode: str = Field(default="mentor", pattern="^(mentor|coach|decision|accountability|reflection)$")


def configure_mentor(*, sessions_collection: Any, model: str | None = None, ollama_base_url: str | None = None) -> None:
    global _sessions, _default_model, _ollama_base_url
    _sessions = sessions_collection
    if model:
        _default_model = str(model)
    if ollama_base_url:
        _ollama_base_url = str(ollama_base_url).rstrip("/")


def _require_configured() -> Any:
    if _sessions is None:
        raise HTTPException(503, "Mentor persistence is not configured.")
    return _sessions


def _normalize_answer(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {
            "summary": "No Mentor response was produced.",
            "priorities": [],
            "next_actions": [],
            "risks": [],
            "reflection_question": "What is the most important outcome you need next?",
        }
    candidate = text
    if "```" in candidate:
        blocks = candidate.split("```")
        for block in blocks:
            stripped = block.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                candidate = stripped
                break
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return {
                "summary": str(parsed.get("summary") or text),
                "priorities": [str(x) for x in (parsed.get("priorities") or [])][:5],
                "next_actions": [str(x) for x in (parsed.get("next_actions") or [])][:7],
                "risks": [str(x) for x in (parsed.get("risks") or [])][:5],
                "reflection_question": str(parsed.get("reflection_question") or "What should you decide next?"),
            }
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {
        "summary": text,
        "priorities": [],
        "next_actions": [],
        "risks": [],
        "reflection_question": "What should you decide or do next?",
    }


def _ollama_chat(*, session: dict[str, Any], user_message: str, mode: str) -> dict[str, Any]:
    history = list(session.get("messages") or [])[-12:]
    compact_history = [
        {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")[:8000]}
        for item in history
    ]
    system = (
        "You are LUMINA Mentor, a rigorous personal and professional mentor. "
        "Do not flatter. Identify the decision the user is avoiding, challenge weak assumptions, "
        "separate facts from inference, and propose concrete next actions. Preserve continuity from the session goal and context. "
        "Return ONLY valid JSON with keys: summary (string), priorities (array of strings), "
        "next_actions (array of strings), risks (array of strings), reflection_question (string). "
        f"Current mode: {mode}. Session goal: {session.get('goal') or 'unspecified'}. "
        f"Session context: {session.get('context') or 'none'}"
    )
    payload = {
        "model": str(session.get("model") or _default_model),
        "stream": False,
        "format": "json",
        "messages": [{"role": "system", "content": system}, *compact_history, {"role": "user", "content": user_message}],
        "options": {"temperature": 0.25, "top_p": 0.9},
    }
    request = urllib.request.Request(
        f"{_ollama_base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Ollama Mentor request failed: {exc}") from exc
    content = str(((body.get("message") or {}).get("content")) or "")
    return _normalize_answer(content)


@router.get("/health")
async def mentor_health(_: str = Depends(require_owner)) -> dict[str, Any]:
    configured = _sessions is not None
    return {
        "status": "ready" if configured else "not_configured",
        "persistence": configured,
        "model": _default_model,
        "ollama_base_url": _ollama_base_url,
    }


@router.get("/sessions")
async def list_mentor_sessions(owner: str = Depends(require_owner)) -> dict[str, Any]:
    coll = _require_configured()
    items = [doc async for doc in coll.find({"owner_email": owner}, {"_id": 0}).sort("updated_at", -1).limit(100)]
    return {"items": items, "count": len(items)}


@router.post("/sessions")
async def create_mentor_session(body: MentorSessionCreate, owner: str = Depends(require_owner)) -> dict[str, Any]:
    coll = _require_configured()
    now = _now()
    session = {
        "id": _new_id(),
        "owner_email": owner,
        "title": body.title,
        "goal": body.goal,
        "context": body.context,
        "model": os.environ.get("MENTOR_MODEL", _default_model),
        "status": "active",
        "messages": [],
        "decisions": [],
        "open_actions": [],
        "created_at": now,
        "updated_at": now,
    }
    await coll.insert_one(session)
    return session


@router.get("/sessions/{session_id}")
async def get_mentor_session(session_id: str, owner: str = Depends(require_owner)) -> dict[str, Any]:
    coll = _require_configured()
    session = await coll.find_one({"id": session_id, "owner_email": owner}, {"_id": 0})
    if not session:
        raise HTTPException(404, "Mentor session not found.")
    return session


@router.patch("/sessions/{session_id}")
async def update_mentor_session(session_id: str, body: dict[str, Any], owner: str = Depends(require_owner)) -> dict[str, Any]:
    coll = _require_configured()
    allowed = {"title", "goal", "context", "status", "open_actions", "decisions"}
    update = {key: body[key] for key in allowed if key in body}
    update["updated_at"] = _now()
    session = await coll.find_one_and_update(
        {"id": session_id, "owner_email": owner},
        {"$set": update},
        return_document=True,
        projection={"_id": 0},
    )
    if not session:
        raise HTTPException(404, "Mentor session not found.")
    return session


@router.post("/sessions/{session_id}/message")
async def mentor_message(session_id: str, body: MentorMessageRequest, owner: str = Depends(require_owner)) -> dict[str, Any]:
    coll = _require_configured()
    session = await coll.find_one({"id": session_id, "owner_email": owner}, {"_id": 0})
    if not session:
        raise HTTPException(404, "Mentor session not found.")
    user_item = {"id": _new_id(), "role": "user", "content": body.message, "at": _now()}
    session.setdefault("messages", []).append(user_item)
    try:
        answer = await asyncio.to_thread(_ollama_chat, session=session, user_message=body.message, mode=body.mode)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    mentor_item = {
        "id": _new_id(),
        "role": "assistant",
        "content": answer["summary"],
        "structured": answer,
        "mode": body.mode,
        "at": _now(),
    }
    session["messages"].append(mentor_item)
    session["open_actions"] = list(dict.fromkeys([*(session.get("open_actions") or []), *answer.get("next_actions", [])]))[-20:]
    session["updated_at"] = _now()
    await coll.replace_one({"id": session_id, "owner_email": owner}, session)
    return {"session_id": session_id, "message": mentor_item, "mentor": answer, "open_actions": session["open_actions"]}
