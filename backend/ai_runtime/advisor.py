from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from ai_runtime.capabilities import MindOrchestrator, orchestration_context  # noqa: E402
from code_builder.ollama_service import (
    OllamaClientConfiguration,
    OllamaService,
    OllamaServiceError,
)
from pydantic import BaseModel, ConfigDict, Field
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
    "cfo": ("cash", "revenue", "profit", "cost", "budget", "tax", "finance", "financial", "bank", "liquidity", "margin", "έσοδα", "κέρδος", "κόστος", "προϋπολογ", "φόρο", "οικονομ", "τράπεζ", "ρευστότητα", "περιθώριο", "€", "$"),
    "cmo": ("marketing", "brand", "campaign", "sales funnel", "social", "advertising", "positioning", "customer acquisition", "μάρκετινγκ", "καμπάνια", "διαφήμιση", "πωλήσ", "πελάτ", "επωνυμία"),
    "strategy": ("strategy", "competitor", "market entry", "expansion", "business model", "partnership", "deal", "στρατηγ", "ανταγωνισ", "επέκταση", "συνεργασία", "συμφωνία", "αγορά"),
    "investment": ("invest", "investment", "portfolio", "return", "roi", "valuation", "asset", "property", "stock", "επένδυ", "απόδοση", "αποτίμηση", "ακίνητ", "μετοχ"),
    "operations": ("operations", "workflow", "process", "team", "staff", "supplier", "logistics", "execution", "λειτουργ", "διαδικασία", "ομάδα", "προσωπικό", "προμηθευ", "μεταφορ", "εκτέλεση"),
    "risk": ("risk", "compliance", "kyc", "aml", "legal", "regulation", "audit", "exposure", "ρίσκο", "κίνδυν", "συμμόρφωση", "νομικ", "κανονισ", "έλεγχος", "έκθεση"),
    "mentor": ("mentor", "personal", "decision", "stress", "habit", "motivation", "career", "life", "προσωπ", "απόφαση", "άγχος", "συνήθεια", "κίνητρο", "καριέρα", "ζωή"),
}


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
    orchestrate: bool = False


class AdvisorMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=10_000)
    category: str = Field(default="general", max_length=100)


class AdvisorProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: dict[str, Any] = Field(default_factory=dict)


class ExecutiveAdvisorService:
    def __init__(self, root: Path | None = None, ollama: OllamaService | None = None, mind: MindOrchestrator | None = None) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        configured_root = os.environ.get("LUMINA_ADVISOR_STATE_DIR", "").strip()
        self.root = root or (Path(configured_root) if configured_root else repository_root / ".lumina" / "advisor")
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        if ollama is None:
            configured_url = os.environ.get("OLLAMA_URL", "").strip().rstrip("/")
            ollama = OllamaService(
                configuration=OllamaClientConfiguration(
                    base_url=configured_url or "http://127.0.0.1:11434"
                )
            )
        self.ollama = ollama
        self.mind = mind or MindOrchestrator()
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

    def groq_model_name(self) -> str:
        return os.environ.get("LUMINA_GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"

    def groq_configured(self) -> bool:
        return bool(os.environ.get("GROQ_API_KEY", "").strip())

    def sambanova_model_name(self) -> str:
        return (
            os.environ.get("SAMBANOVA_MODEL", "Qwen2.5-Coder-32B-Instruct").strip()
            or "Qwen2.5-Coder-32B-Instruct"
        )

    def sambanova_base_url(self) -> str:
        return os.environ.get("SAMBANOVA_BASE_URL", "").strip().rstrip("/")

    def sambanova_configured(self) -> bool:
        return bool(os.environ.get("SAMBANOVA_API_KEY", "").strip()) and bool(
            self.sambanova_base_url()
        )

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
        recent_actions = [
            entry
            for entry in self.mind.recent_actions(owner, limit=6)
            if entry.get("status") in {"completed", "failed", "declined"}
        ]
        actions_text = "\n".join(
            f"- [{entry.get('created_at') or ''}] {entry.get('capability')}/{entry.get('action')} -> {entry.get('status')} "
            f"({str(entry.get('result') or entry.get('error') or '')[:240]})"
            for entry in recent_actions
        ) or "- none"
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
Always answer in the language used by the owner in the latest message. When the owner writes in Greek, use clear natural Greek and keep unavoidable technical terms simple.
Never invent facts, financial figures, legal status, source documents, or completed actions. Ask for missing facts only when they are essential; otherwise make bounded assumptions and label them.
For financial, legal, medical, tax, compliance, or investment matters, explicitly flag uncertainty and the need for professional verification when material.
{depth}
{board_instruction}

You are also the orchestrator of the LUMINA capabilities (documents, image, video, voice, media/projects, code builder). When a capability was executed in the latest turn, its real outcome is provided as 'LUMINA capability results'. Ground your answer in those real results: reference actual ids, statuses, counts and outputs. If an action requires owner approval and was NOT executed, say clearly what will happen if approved and ask for explicit confirmation. Never claim a capability ran unless the provided results show it.
Persistent owner profile (treat as user-provided context, not independently verified):
{json.dumps(profile, ensure_ascii=False, indent=2)}

Persistent memories (user-provided context):
{memory_text or '- none'}

Recent real LUMINA orchestration actions by the owner:
{actions_text}

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

    async def _ask_groq(self, *, messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]], str]:
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")
        model = self.groq_model_name()
        api_url = os.environ.get(
            "GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions"
        ).strip().rstrip("/") or "https://api.groq.com/openai/v1/chat/completions"
        if not api_url.endswith("/chat/completions"):
            api_url = f"{api_url}/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": 0.2}
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"Groq API returned HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        try:
            answer = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Groq API returned no output text") from exc
        if not answer:
            raise RuntimeError("Groq API returned no output text")
        return answer, [], model

    async def _ask_sambanova(
        self, *, messages: list[dict[str, str]]
    ) -> tuple[str, list[dict[str, str]], str]:
        api_key = os.environ.get("SAMBANOVA_API_KEY", "").strip()
        base_url = self.sambanova_base_url()
        if not api_key or not base_url:
            raise RuntimeError("SAMBANOVA_API_KEY and SAMBANOVA_BASE_URL are not configured")
        if not base_url.startswith("https://"):
            raise RuntimeError("SAMBANOVA_BASE_URL must be an HTTPS URL")
        model = self.sambanova_model_name()
        endpoint = f"{base_url}/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": 0.2}
        timeout = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"SambaNova API returned HTTP {response.status_code}")
        data = response.json()
        try:
            answer = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("SambaNova API returned no output text") from exc
        if not answer:
            raise RuntimeError("SambaNova API returned no output text")
        return answer, [], model

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
        user_content = request.message + context_text

        # --- LUMINA Mind orchestration (real capability execution) ---------
        orchestration: dict[str, Any] = {"status": "none"}
        if request.orchestrate:
            orchestration = await self._orchestrate(owner, request, session_id, session, user_content)
            note = orchestration.get("note")
            if note:
                user_content = f"{user_content}\n\n{note}"
        messages.append({"role": "user", "content": user_content})

        requested_provider = request.provider.strip().casefold()
        if requested_provider not in {"auto", "local", "groq", "openai", "sambanova"}:
            requested_provider = "auto"
        use_openai = requested_provider == "openai" or request.web_research
        use_sambanova = requested_provider == "sambanova" or (
            requested_provider == "auto"
            and not request.web_research
            and self.sambanova_configured()
        )
        use_groq = requested_provider == "groq" or (
            requested_provider == "auto"
            and not request.web_research
            and not self.sambanova_configured()
            and self.groq_configured()
        )

        started = time.monotonic()
        sources: list[dict[str, str]] = []
        error = None
        if use_sambanova:
            try:
                answer, sources, model = await self._ask_sambanova(messages=messages)
                provider = "sambanova"
                provider_status = "ok"
            except Exception as exc:
                answer = "SambaNova cloud mode is currently unavailable. Check SAMBANOVA_API_KEY, SAMBANOVA_BASE_URL, rate limits, network access, and the configured model, then retry or switch provider."
                model = self.sambanova_model_name()
                provider = "sambanova"
                provider_status = "unavailable"
                error = str(exc)
        elif use_groq:
            try:
                answer, sources, model = await self._ask_groq(messages=messages)
                provider = "groq"
                provider_status = "ok"
            except Exception as exc:
                answer = "Groq cloud mode is currently unavailable. Check GROQ_API_KEY, rate limits, network access, and the configured model, then retry or switch provider."
                model = self.groq_model_name()
                provider = "groq"
                provider_status = "unavailable"
                error = str(exc)
        elif use_openai:
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
                answer = await self._local_chat(messages)
                provider_status = "ok"
            except OllamaServiceError as exc:
                answer = "The local advisor model is currently unavailable. Check Ollama and the configured advisor model, then retry."
                provider_status = "unavailable"
                error = str(exc)

        now = time.time()
        session["messages"].append({"id": uuid4().hex, "role": "user", "content": request.message, "created_at": now, "role_mode": role})
        session["messages"].append({"id": uuid4().hex, "role": "assistant", "content": answer, "created_at": time.time(), "role_mode": role, "model": model, "provider": provider, "sources": sources, "orchestration": orchestration if orchestration.get("status") != "none" else None})
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
            "orchestration": orchestration if orchestration.get("status") != "none" else None,
            "error": error,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "deep_reasoning": request.deep_reasoning,
            "web_research": request.web_research,
        }

    async def _orchestrate(
        self,
        owner: str,
        request: AdvisorRequest,
        session_id: str | None,
        session: dict[str, Any],
        user_content: str,
    ) -> dict[str, Any]:
        """Run LUMINA Mind orchestration for the current request in a single turn.

        Order of operations:
        1. If a pending action (awaiting approval) exists, first check whether the
           message is an explicit confirmation/denial and resolve it resident.
        2. Otherwise resolve the message to an intent; if none, this is a chat turn.
        3. Execute the resolved real capability and return a grounded context note
           plus a compact machine-readable record for the response/session.
        """
        try:
            pending = self.mind.pending(owner, session_id)
            decision = self.mind.confirm_decision(request.message) if pending is not None else None
            if decision is not None and not self._mentions_capability(request.message):
                handled = await self.mind.handle_decision(owner, session_id, request.message)
                if handled is not None:
                    return self._decision_note(handled)

            intent = self.mind.resolve(request.message, request.context)
            if intent is None:
                return {"status": "none"}

            entry = await self.mind.execute(
                owner,
                intent.capability,
                intent.action,
                intent.params,
                session_id=session_id,
            )
            entry = {**entry, "capability": intent.capability, "action": intent.action}
            status = entry.get("status")
            return {
                "status": status,
                "capability": intent.capability,
                "action": intent.action,
                "result": entry.get("result"),
                "error": entry.get("error"),
                "next": entry.get("next"),
                "pending": entry.get("pending_id") or entry.get("pending"),
                "params": entry.get("params"),
                "note": orchestration_context(entry),
            }
        except Exception as exc:  # noqa: BLE001 - never break the advisory chat
            return {
                "status": "error",
                "error": str(exc)[:300],
                "note": f"LUMINA orchestration failed: {str(exc)[:300]}",
            }

    @staticmethod
    def _mentions_capability(message: str) -> bool:
        from ai_runtime.capabilities.intent import _mentions_capability

        return _mentions_capability(message or "")

    def _decision_note(self, decision: dict[str, Any]) -> dict[str, Any]:
        status = decision.get("status")
        if status == "executed":
            result = decision.get("result")
            detail = ", ".join(f"{key}={value}" for key, value in (result or {}).items())
            note = (
                f"LUMINA capability results:\n- Capability: {decision.get('capability')} / {decision.get('action')}\n"
                f"  Status: approved and executed. Result: {detail or 'ok'}"
            )
            return {
                "status": "executed",
                "capability": decision.get("capability"),
                "action": decision.get("action"),
                "result": result,
                "note": note,
            }
        if status == "declined":
            note = (
                f"LUMINA capability status:\n- Capability: {decision.get('capability')} / {decision.get('action')}\n"
                "  Status: declined by owner; nothing was executed."
            )
            return {
                "status": "declined",
                "capability": decision.get("capability"),
                "action": decision.get("action"),
                "note": note,
            }
        if status == "no_pending_action":
            return {
                "status": "none",
                "note": "You indicated a decision, but there is no pending action awaiting approval.",
            }
        return {"status": "none"}

    async def _local_chat(self, messages: list[dict[str, str]]) -> str:
        """Query the local advisor model, degrading deep reasoning when the model lacks thinking support."""
        for think in ("high", False):
            try:
                result = await self.ollama.chat(
                    model=self.model_name(),
                    messages=messages,
                    think=think,
                    timeout_seconds=300,
                    verify_model=False,
                )
                return result.content.strip()
            except OllamaServiceError as exc:
                message = str(exc).casefold()
                if think is False or "think" not in message or "not support" not in message:
                    raise

    async def status(self) -> dict[str, Any]:
        health = await self.ollama.check_connection(include_models=True)
        model = self.model_name()
        installed = [item.name for item in health.installed_models]
        return {
            "available": health.available or self.groq_configured() or self.openai_configured() or self.sambanova_configured(),
            "local_available": health.available,
            "groq_configured": self.groq_configured(),
            "openai_configured": self.openai_configured(),
            "sambanova_configured": self.sambanova_configured(),
            "model": model,
            "groq_model": self.groq_model_name(),
            "openai_model": self.openai_model_name(),
            "sambanova_model": self.sambanova_model_name(),
            "model_installed": any(name.casefold() == model.casefold() or name.casefold().startswith(model.casefold() + ":") for name in installed),
            "ollama": health.to_dict(),
            "roles": ADVISOR_ROLES,
            "capabilities": ["persistent_sessions", "persistent_memory", "profile_context", "automatic_role_routing", "board_mode", "deep_reasoning", "local_first", "optional_openai", "optional_web_research", "optional_sambanova"],
        }


executive_advisor = ExecutiveAdvisorService()
