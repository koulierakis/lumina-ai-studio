from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from code_builder.ollama_service import OllamaService, OllamaServiceError
from runtime_info import load_runtime_config


ADVISOR_ROLES = {
    "auto": "Executive Advisor",
    "board": "Executive Board",
    "ceo": "Chief Executive Officer",
    "cfo": "Chief Financial Officer",
    "cmo": "Chief Marketing Officer",
    "strategy": "Chief Strategy Officer",
    "investment": "Investment Director",
    "operations": "Chief Operating Officer",
    "risk": "Risk & Compliance Advisor",
    "mentor": "Personal Mentor",
}

ROLE_KEYWORDS = {
    "cfo": ("cash", "revenue", "profit", "cost", "budget", "tax", "finance", "financial", "bank", "liquidity", "margin", "€", "$"),
    "cmo": ("marketing", "brand", "campaign", "sales funnel", "social", "advertising", "positioning", "customer acquisition"),
    "strategy": ("strategy", "competitor", "market entry", "expansion", "business model", "partnership", "deal"),
    "investment": ("invest", "investment", "portfolio", "return", "roi", "valuation", "asset", "property", "stock"),
    "operations": ("operations", "workflow", "process", "team", "staff", "supplier", "logistics", "execution"),
    "risk": ("risk", "compliance", "kyc", "aml", "legal", "regulation", "audit", "exposure"),
    "mentor": ("mentor", "personal", "decision", "stress", "habit", "motivation", "career", "life"),
}


class AdvisorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=50_000)
    session_id: str | None = None
    role: str = "auto"
    deep_reasoning: bool = True
    remember_message: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class AdvisorMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=10_000)
    category: str = Field(default="general", max_length=100)


class AdvisorProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: dict[str, Any] = Field(default_factory=dict)


class ExecutiveAdvisorService:
    def __init__(self, root: Path | None = None, ollama: OllamaService | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        self.root = root or repository_root / ".lumina" / "advisor"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.ollama = ollama or OllamaService()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return {"owners": {}}

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_path)

    def _owner(self, owner: str) -> dict[str, Any]:
        owners = self._state.setdefault("owners", {})
        return owners.setdefault(owner, {"profile": {}, "memories": [], "sessions": {}})

    def model_name(self) -> str:
        configured = os.environ.get("LUMINA_ADVISOR_MODEL", "").strip()
        if configured:
            return configured
        try:
            runtime = load_runtime_config()
            preferred = str(runtime.get("preferred_ollama_model") or "").strip()
            if preferred:
                return preferred
        except Exception:
            pass
        return "qwen2.5:7b"

    def route_role(self, message: str, requested: str) -> str:
        normalized = requested.strip().casefold()
        if normalized in ADVISOR_ROLES and normalized != "auto":
            return normalized
        text = message.casefold()
        scores = {
            role: sum(1 for keyword in keywords if keyword in text)
            for role, keywords in ROLE_KEYWORDS.items()
        }
        winner = max(scores, key=scores.get, default="ceo")
        return winner if scores.get(winner, 0) else "ceo"

    def _session(self, owner: str, session_id: str | None) -> tuple[str, dict[str, Any]]:
        owner_state = self._owner(owner)
        sessions = owner_state.setdefault("sessions", {})
        resolved = session_id or uuid4().hex
        session = sessions.setdefault(
            resolved,
            {"id": resolved, "title": "Executive Advisory Session", "messages": [], "created_at": time.time(), "updated_at": time.time()},
        )
        return resolved, session

    def list_sessions(self, owner: str) -> list[dict[str, Any]]:
        sessions = self._owner(owner).get("sessions", {})
        rows = []
        for session in sessions.values():
            messages = session.get("messages", [])
            rows.append({
                "id": session.get("id"),
                "title": session.get("title") or "Executive Advisory Session",
                "updated_at": session.get("updated_at"),
                "message_count": len(messages),
                "last_message": messages[-1].get("content", "")[:160] if messages else "",
            })
        return sorted(rows, key=lambda row: row.get("updated_at") or 0, reverse=True)

    def get_session(self, owner: str, session_id: str) -> dict[str, Any]:
        session = self._owner(owner).get("sessions", {}).get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def delete_session(self, owner: str, session_id: str) -> None:
        sessions = self._owner(owner).get("sessions", {})
        if session_id not in sessions:
            raise KeyError(session_id)
        del sessions[session_id]
        self._save()

    def memories(self, owner: str) -> list[dict[str, Any]]:
        return list(self._owner(owner).get("memories", []))

    def remember(self, owner: str, text: str, category: str = "general") -> dict[str, Any]:
        memory = {"id": uuid4().hex, "text": text.strip(), "category": category.strip() or "general", "created_at": time.time()}
        memories = self._owner(owner).setdefault("memories", [])
        memories.append(memory)
        del memories[:-100]
        self._save()
        return memory

    def forget(self, owner: str, memory_id: str) -> None:
        memories = self._owner(owner).setdefault("memories", [])
        remaining = [item for item in memories if item.get("id") != memory_id]
        if len(remaining) == len(memories):
            raise KeyError(memory_id)
        self._owner(owner)["memories"] = remaining
        self._save()

    def profile(self, owner: str) -> dict[str, Any]:
        return dict(self._owner(owner).get("profile", {}))

    def update_profile(self, owner: str, profile: dict[str, Any]) -> dict[str, Any]:
        safe_profile = json.loads(json.dumps(profile, ensure_ascii=False, allow_nan=False))
        self._owner(owner)["profile"] = safe_profile
        self._save()
        return safe_profile

    def _system_prompt(self, owner: str, role: str, deep_reasoning: bool) -> str:
        owner_state = self._owner(owner)
        profile = owner_state.get("profile", {})
        memories = owner_state.get("memories", [])[-30:]
        memory_text = "\n".join(f"- [{m.get('category','general')}] {m.get('text','')}" for m in memories)
        role_name = ADVISOR_ROLES.get(role, ADVISOR_ROLES["ceo"])
        board_instruction = ""
        if role == "board":
            board_instruction = (
                "Internally evaluate the issue from CEO, CFO, CMO, strategy, investment, operations, risk/compliance, and mentor perspectives. "
                "Return one unified recommendation; surface material disagreements and trade-offs without simulating a theatrical conversation."
            )
        depth = "Use deliberate multi-step analysis before answering." if deep_reasoning else "Prefer a concise operational answer."
        return f"""You are LUMINA Executive Intelligence, acting as {role_name}.
You are an exacting advisor, not a passive assistant. Challenge weak assumptions, distinguish evidence from inference, and state material risks.
Never invent facts, financial figures, legal status, source documents, or completed actions. Ask for missing facts only when they are essential; otherwise make bounded assumptions and label them.
For financial, legal, medical, tax, compliance, or investment matters, explicitly flag uncertainty and the need for professional verification when material.
{depth}
{board_instruction}

Persistent owner profile (treat as user-provided context, not independently verified):
{json.dumps(profile, ensure_ascii=False, indent=2)}

Persistent memories (user-provided context):
{memory_text or '- none'}

Response format: lead with the decision/recommendation, then reasoning, risks, and concrete next actions when useful. Avoid filler."""

    async def ask(self, owner: str, request: AdvisorRequest) -> dict[str, Any]:
        requested_role = request.role.strip().casefold()
        role = "board" if requested_role == "board" else self.route_role(request.message, requested_role)
        session_id, session = self._session(owner, request.session_id)
        if request.remember_message:
            self.remember(owner, request.message, "conversation")

        history = list(session.get("messages", []))[-24:]
        messages: list[dict[str, str]] = [{"role": "system", "content": self._system_prompt(owner, role, request.deep_reasoning)}]
        for item in history:
            item_role = str(item.get("role") or "user")
            if item_role in {"user", "assistant"}:
                messages.append({"role": item_role, "content": str(item.get("content") or "")})
        context_text = ""
        if request.context:
            context_text = "\n\nAdditional structured context:\n" + json.dumps(request.context, ensure_ascii=False, indent=2)
        messages.append({"role": "user", "content": request.message + context_text})

        model = self.model_name()
        started = time.monotonic()
        try:
            result = await self.ollama.chat(
                model=model,
                messages=messages,
                think="high" if request.deep_reasoning else False,
                timeout_seconds=300,
                verify_model=False,
            )
            answer = result.content.strip()
            provider_status = "ok"
            error = None
        except OllamaServiceError as exc:
            answer = "The local advisor model is currently unavailable. Check Ollama and the configured advisor model, then retry."
            provider_status = "unavailable"
            error = str(exc)

        now = time.time()
        session["messages"].append({"id": uuid4().hex, "role": "user", "content": request.message, "created_at": now, "role_mode": role})
        session["messages"].append({"id": uuid4().hex, "role": "assistant", "content": answer, "created_at": time.time(), "role_mode": role, "model": model})
        session["messages"] = session["messages"][-100:]
        if len(session["messages"]) == 2:
            session["title"] = re.sub(r"\s+", " ", request.message).strip()[:72] or "Executive Advisory Session"
        session["updated_at"] = time.time()
        self._save()

        return {
            "session_id": session_id,
            "answer": answer,
            "role": role,
            "role_name": ADVISOR_ROLES.get(role),
            "model": model,
            "provider_status": provider_status,
            "error": error,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "deep_reasoning": request.deep_reasoning,
        }

    async def status(self) -> dict[str, Any]:
        health = await self.ollama.check_connection(include_models=True)
        model = self.model_name()
        installed = [item.name for item in health.installed_models]
        return {
            "available": health.available,
            "model": model,
            "model_installed": any(name.casefold() == model.casefold() or name.casefold().startswith(model.casefold() + ":") for name in installed),
            "ollama": health.to_dict(),
            "roles": ADVISOR_ROLES,
            "capabilities": ["persistent_sessions", "persistent_memory", "profile_context", "automatic_role_routing", "board_mode", "deep_reasoning", "local_first"],
        }


executive_advisor = ExecutiveAdvisorService()
