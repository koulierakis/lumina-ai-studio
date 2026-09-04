from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
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
    "cfo": ("cash", "revenue", "profit", "cost", "budget", "tax", "finance", "financial", "bank", "liquidity", "margin", "€", "$",
            "ταμει", "εσοδ", "κέρδ", "κερδ", "κόστος", "κοστος", "προϋπολογ", "φορο", "οικονομ", "τραπεζ", "ρευστό", "ρευστο"),
    "cmo": ("marketing", "brand", "campaign", "sales funnel", "social", "advertising", "positioning", "customer acquisition",
            "μάρκετινγκ", "μαρκετινγκ", "διαφήμ", "διαφημ", "πωλήσ", "πωλησ", "πελάτ", "πελατ", "προώθη", "προωθη"),
    "strategy": ("strategy", "competitor", "market entry", "expansion", "business model", "partnership", "deal",
                 "στρατηγ", "ανταγωνισ", "επέκτα", "επεκτα", "συνεργασ", "αγορά", "αγορα", "συμφων"),
    "investment": ("invest", "investment", "portfolio", "return", "roi", "valuation", "asset", "property", "stock",
                   "επένδ", "επενδ", "απόδο", "αποδο", "αποτίμ", "αποτιμ", "ακίνητ", "ακινητ", "μετοχ"),
    "operations": ("operations", "workflow", "process", "team", "staff", "supplier", "logistics", "execution",
                   "λειτουργ", "διαδικασ", "ομάδ", "ομαδ", "προσωπ", "προμηθευ", "logistic", "εκτέλε", "εκτελε"),
    "risk": ("risk", "compliance", "kyc", "aml", "legal", "regulation", "audit", "exposure",
             "ρίσκ", "ρισκ", "κίνδυν", "κινδυν", "συμμόρφ", "συμμορφ", "νομικ", "κανονισ", "έλεγχ", "ελεγχ"),
    "mentor": ("mentor", "personal", "decision", "stress", "habit", "motivation", "career", "life",
               "μέντορ", "μεντορ", "προσωπ", "απόφασ", "αποφασ", "άγχ", "αγχ", "κίνητρ", "κινητρ", "καριέρ", "καριερ", "ζωή", "ζωη"),
}


MAX_CONTEXT_DOCUMENTS = 3
MAX_CONTEXT_CHARS_PER_DOCUMENT = 20_000
MAX_CONTEXT_TOTAL_CHARS = 45_000


class AdvisorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=50_000)
    session_id: str | None = None
    role: str = "auto"
    deep_reasoning: bool = True
    remember_message: bool = False
    provider: str = "auto"
    web_research: bool = False
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

    def openai_model_name(self) -> str:
        return os.environ.get("LUMINA_OPENAI_MODEL", "gpt-5").strip() or "gpt-5"

    def openai_configured(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())

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
        normalized_text = text.strip()
        normalized_category = category.strip() or "general"
        memories = self._owner(owner).setdefault("memories", [])
        for existing in reversed(memories):
            if (
                str(existing.get("text") or "").strip().casefold() == normalized_text.casefold()
                and str(existing.get("category") or "general").strip().casefold() == normalized_category.casefold()
            ):
                return existing
        memory = {"id": uuid4().hex, "text": normalized_text, "category": normalized_category, "created_at": time.time()}
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

    @staticmethod
    def _bounded_context(context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(context, dict):
            return {}
        safe: dict[str, Any] = {}
        documents = context.get("documents")
        if isinstance(documents, list):
            bounded_documents = []
            remaining = MAX_CONTEXT_TOTAL_CHARS
            for item in documents[:MAX_CONTEXT_DOCUMENTS]:
                if not isinstance(item, dict) or remaining <= 0:
                    continue
                text = str(item.get("text") or "")[: min(MAX_CONTEXT_CHARS_PER_DOCUMENT, remaining)]
                remaining -= len(text)
                bounded_documents.append({
                    "id": str(item.get("id") or "")[:200],
                    "title": str(item.get("title") or "Attached document")[:500],
                    "category": str(item.get("category") or "")[:200],
                    "text": text,
                })
            if bounded_documents:
                safe["documents"] = bounded_documents
        for key, value in context.items():
            if key == "documents":
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[str(key)[:100]] = str(value)[:2000] if isinstance(value, str) else value
        return safe

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
        current_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return f"""You are LUMINA Executive Intelligence, acting as {role_name}.
Current UTC date/time: {current_utc}. Treat current or fast-changing facts as unverified unless supported by supplied context or live research.
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

    @staticmethod
    def _extract_openai_output(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
        texts: list[str] = []
        sources: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if not isinstance(content, dict) or content.get("type") != "output_text":
                        continue
                    text = content.get("text")
                    if isinstance(text, str):
                        texts.append(text)
                    for annotation in content.get("annotations", []):
                        if not isinstance(annotation, dict):
                            continue
                        url = annotation.get("url")
                        title = annotation.get("title")
                        if isinstance(url, str) and url and url not in seen_urls:
                            seen_urls.add(url)
                            sources.append({"url": url, "title": str(title or url)})
            if item.get("type") == "web_search_call":
                action = item.get("action")
                if isinstance(action, dict):
                    for source in action.get("sources", []):
                        if not isinstance(source, dict):
                            continue
                        url = source.get("url")
                        if isinstance(url, str) and url and url not in seen_urls:
                            seen_urls.add(url)
                            sources.append({"url": url, "title": url})
        return "\n".join(texts).strip(), sources

    async def _ask_openai(
        self,
        *,
        messages: list[dict[str, str]],
        deep_reasoning: bool,
        web_research: bool,
    ) -> tuple[str, list[dict[str, str]], str]:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        model = self.openai_model_name()
        input_messages = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ]
        payload: dict[str, Any] = {"model": model, "input": input_messages}
        if deep_reasoning:
            payload["reasoning"] = {"effort": "high"}
        if web_research:
            payload["tools"] = [{"type": "web_search"}]
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"OpenAI Responses API returned HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        answer, sources = self._extract_openai_output(data)
        if not answer:
            raise RuntimeError("OpenAI Responses API returned no output text")
        return answer, sources, model

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
        bounded_context = self._bounded_context(request.context)
        if bounded_context:
            context_text = "\n\nAdditional structured context:\n" + json.dumps(bounded_context, ensure_ascii=False, indent=2)
        messages.append({"role": "user", "content": request.message + context_text})

        requested_provider = request.provider.strip().casefold()
        if requested_provider not in {"auto", "local", "openai"}:
            requested_provider = "auto"
        use_openai = requested_provider == "openai" or request.web_research

        started = time.monotonic()
        sources: list[dict[str, str]] = []
        error = None
        if use_openai:
            try:
                answer, sources, model = await self._ask_openai(
                    messages=messages,
                    deep_reasoning=request.deep_reasoning,
                    web_research=request.web_research,
                )
                provider = "openai"
                provider_status = "ok"
            except Exception as exc:
                answer = "OpenAI cloud mode is currently unavailable. Check OPENAI_API_KEY, billing, network access, and the configured model, then retry or switch to Local mode."
                model = self.openai_model_name()
                provider = "openai"
                provider_status = "unavailable"
                error = str(exc)
        else:
            model = self.model_name()
            provider = "local"
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
            except OllamaServiceError as exc:
                if requested_provider == "auto" and self.openai_configured():
                    try:
                        answer, sources, model = await self._ask_openai(
                            messages=messages,
                            deep_reasoning=request.deep_reasoning,
                            web_research=False,
                        )
                        provider = "openai"
                        provider_status = "fallback"
                        error = f"Local provider unavailable; automatic cloud fallback used: {exc}"
                    except Exception as cloud_exc:
                        answer = "Both the local advisor and automatic cloud fallback are currently unavailable. Check Ollama and the OpenAI configuration, then retry."
                        provider_status = "unavailable"
                        error = f"Local: {exc}; Cloud fallback: {cloud_exc}"
                else:
                    answer = "The local advisor model is currently unavailable. Check Ollama and the configured advisor model, then retry."
                    provider_status = "unavailable"
                    error = str(exc)

        now = time.time()
        session["messages"].append({"id": uuid4().hex, "role": "user", "content": request.message, "created_at": now, "role_mode": role})
        session["messages"].append({"id": uuid4().hex, "role": "assistant", "content": answer, "created_at": time.time(), "role_mode": role, "model": model, "provider": provider, "sources": sources})
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
            "provider": provider,
            "model": model,
            "provider_status": provider_status,
            "sources": sources,
            "error": error,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "deep_reasoning": request.deep_reasoning,
            "web_research": request.web_research,
        }

    async def status(self) -> dict[str, Any]:
        health = await self.ollama.check_connection(include_models=True)
        model = self.model_name()
        installed = [item.name for item in health.installed_models]
        return {
            "available": health.available or self.openai_configured(),
            "local_available": health.available,
            "openai_configured": self.openai_configured(),
            "model": model,
            "openai_model": self.openai_model_name(),
            "model_installed": any(name.casefold() == model.casefold() or name.casefold().startswith(model.casefold() + ":") for name in installed),
            "ollama": health.to_dict(),
            "roles": ADVISOR_ROLES,
            "capabilities": ["persistent_sessions", "persistent_memory", "profile_context", "automatic_role_routing", "greek_role_routing", "board_mode", "deep_reasoning", "local_first", "automatic_cloud_fallback", "optional_openai", "optional_web_research", "bounded_document_grounding"],
        }


executive_advisor = ExecutiveAdvisorService()
