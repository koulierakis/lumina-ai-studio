"""OpenHands as an LLM provider: a delegated coding agent behind the registry.

This makes OpenHands a *provider*, not a new authority. It answers the same
``LLMProvider.complete()`` contract as every other vendor, so the planner,
generator, diagnosis and repair flows use it unchanged — and, crucially, the
router's fallback, cooldown and health semantics keep working.

Two design choices matter for the "never lie about COMPLETED" mandate:

- A delegated conversation runs for minutes, so the provider declares a timeout
  floor (``min_attempt_timeout_s``/``min_total_timeout_s``) and the router
  honours it instead of cancelling mid-conversation.
- The provider is registered **last**: it is a strong coding engine, but a
  whole agent conversation is slower and costlier than a single completion, so
  it is the deliberate escalation, not the default.

Configuration (all optional except the key):

- ``OPENHANDS_API_KEY``      — API key (Cloud or self-hosted). Required.
- ``OPENHANDS_BASE_URL``     — API base (default ``https://app.all-hands.dev``).
- ``OPENHANDS_PROVIDER_MODEL`` — model label used for identity/independence.
- ``OPENHANDS_REPO``         — optional repository to clone into the sandbox.
- ``OPENHANDS_BRANCH``       — optional branch for that repository.
- ``OPENHANDS_MAX_WAIT_S``   — polling ceiling (default 900s).

Response mapping: the delegated conversation's final assistant message becomes
``CompletionResponse.text``. It is never wrapped in markdown fences here, so
``_strip_fences`` downstream sees exactly what the agent produced.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, List, Optional

import httpx

from .base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    ProviderError,
    TransientProviderError,
    classify_transient,
    provider_exception,
)

DEFAULT_BASE_URL = "https://app.all-hands.dev"
DEFAULT_MODEL = "agent"

# A full coding conversation is not a single completion. These floors keep the
# router from cancelling a healthy conversation at the default 30s/120s budget.
MIN_ATTEMPT_TIMEOUT_S = 300.0
MIN_TOTAL_TIMEOUT_S = 900.0
POLL_INTERVAL_S = 3.0

# The events-search endpoint rejects limit>=200 with HTTP 422 ("should be less
# than 200"), so page well below that ceiling to still catch a final assistant
# message without tripping validation.
_EVENTS_PAGE_LIMIT = 100

# The events-search endpoint is *paginated* and returns events oldest-first:
# ``next_page_id`` is an offset cursor for the next (newer) page, and it is
# ``None`` on the last page. A real coding conversation routinely exceeds one
# page, so the final assistant message lives on a later page than the first.
# Follow the cursor to the end, bounded so a pathological conversation cannot
# issue unbounded requests.
_MAX_EVENT_PAGES = 20

# Terminal executes before the final assistant message is indexed.
_FINAL_TEXT_GRACE_S = 30.0

_TERMINAL_EXECUTION_STATES = {"finished", "error", "stopped", "cancelled"}


def _as_items(payload: object) -> list[dict]:
    """Normalize an OpenHands list response.

    The app-conversation endpoints return a bare JSON array on most Cloud
    deployments but a ``{"items": [...]}`` envelope on others. Accept both so a
    shape difference degrades into an empty page, not an ``AttributeError``.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("results") or []
        return [item for item in items if isinstance(item, dict)]
    return []


class OpenHandsProvider(LLMProvider):
    provider = "openhands"
    # A coding agent is not a text-only completion; it can serve every core flow.
    capabilities = frozenset({"text", "json", "coding", "reasoning"})

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: Optional[str] = None,
        api_key_env: str = "OPENHANDS_API_KEY",
        repo: Optional[str] = None,
        branch: Optional[str] = None,
        max_wait_s: Optional[float] = None,
    ):
        self.model = model or DEFAULT_MODEL
        self.id = f"openhands-{self.model}".replace("/", "-")
        self.base_url = (base_url or os.environ.get("OPENHANDS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key_env = api_key_env
        self.repo = repo or os.environ.get("OPENHANDS_REPO") or None
        self.branch = branch or os.environ.get("OPENHANDS_BRANCH") or None
        try:
            configured_wait = float(os.environ.get("OPENHANDS_MAX_WAIT_S", "") or 0)
        except ValueError:
            configured_wait = 0.0
        self.max_wait_s = max_wait_s or configured_wait or MIN_TOTAL_TIMEOUT_S
        self.min_attempt_timeout_s = MIN_ATTEMPT_TIMEOUT_S
        self.min_total_timeout_s = MIN_TOTAL_TIMEOUT_S

    # ---------------------------------------------------------------- lifecycle
    def available(self) -> bool:
        return bool(os.environ.get(self.api_key_env, "").strip())

    def _key(self) -> str:
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise ProviderError(f"{self.api_key_env} not configured")
        return key

    # ------------------------------------------------------------------ request
    async def complete(self, req: CompletionRequest) -> CompletionResponse:
        key = self._key()
        prompt = self._build_prompt(req)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                start = await self._start_conversation(client, headers, prompt)
                conv_id = await self._resolve_conversation_id(client, headers, start)
                text = await self._await_conversation(client, headers, conv_id)
            except (ProviderError, TransientProviderError):
                raise
            except Exception as exc:  # noqa: BLE001
                raise provider_exception(self.id, exc) from None

        if not text or not text.strip():
            raise ProviderError("OpenHands conversation produced no assistant output")
        return CompletionResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            usage={"openhands_conversation_id": conv_id},
            finish_reason="stop",
        )

    async def _start_conversation(self, client, headers, prompt: str) -> dict:
        payload: dict[str, Any] = {
            "initial_message": {"content": [{"type": "text", "text": prompt}]},
            "title": "Gold Builder delegation",
        }
        if self.repo:
            payload["selected_repository"] = self.repo
        if self.branch:
            payload["selected_branch"] = self.branch
        r = await client.post(f"{self.base_url}/api/v1/app-conversations", headers=headers, json=payload)
        self._raise_for_status(r)
        try:
            return r.json()
        except ValueError as exc:
            raise ProviderError("OpenHands returned a non-JSON start response") from exc

    async def _resolve_conversation_id(self, client, headers, start: dict) -> str:
        conv_id = start.get("app_conversation_id") or start.get("conversation_id")
        if conv_id:
            return str(conv_id)
        task_id = start.get("id")
        if not task_id:
            raise ProviderError("OpenHands start response contained no conversation or start-task id")
        # The start endpoint is asynchronous on most deployments: poll the
        # start-task until it yields the app_conversation_id.
        deadline = asyncio.get_running_loop().time() + min(self.max_wait_s, 120.0)
        while asyncio.get_running_loop().time() < deadline:
            r = await client.get(
                f"{self.base_url}/api/v1/app-conversations/start-tasks",
                headers=headers, params={"ids": str(task_id)},
            )
            self._raise_for_status(r)
            items = _as_items(r.json())
            record = next((it for it in items if str(it.get("id")) == str(task_id)), None)
            if record:
                conv_id = record.get("app_conversation_id") or record.get("conversation_id")
                if conv_id:
                    return str(conv_id)
                if record.get("status") in {"FAILED", "ERROR"}:
                    raise ProviderError(
                        f"OpenHands start-task failed: {record.get('detail') or record.get('status')}"
                    )
            await asyncio.sleep(POLL_INTERVAL_S)
        raise TransientProviderError("OpenHands start-task did not become ready in time")

    async def _await_conversation(self, client, headers, conv_id: str) -> str:
        deadline = asyncio.get_running_loop().time() + self.max_wait_s
        last_error: Optional[str] = None
        while asyncio.get_running_loop().time() < deadline:
            r = await client.get(
                f"{self.base_url}/api/v1/app-conversations",
                headers=headers, params={"ids": conv_id},
            )
            self._raise_for_status(r)
            items = _as_items(r.json())
            record = next((it for it in items if str(it.get("app_conversation_id") or it.get("id")) == conv_id), None)
            if record:
                execution = str(record.get("execution_status", "")).lower()
                if execution in _TERMINAL_EXECUTION_STATES:
                    if execution in {"error", "stopped", "cancelled"}:
                        last_error = execution
                        break
                    return await self._final_assistant_text(client, headers, conv_id)
            await asyncio.sleep(POLL_INTERVAL_S)
        if last_error:
            raise ProviderError(f"OpenHands conversation ended with status {last_error}")
        # The list payload omits ``execution_status`` on some deployments, so a
        # finished conversation can appear to "never finish". The events stream
        # still records the authoritative terminal state update; consult it once
        # before giving up, and only accept it as finished when a terminal status
        # is actually present (never return a mid-conversation partial message).
        events = await self._all_events(client, headers, conv_id)
        status = self._execution_status_from_events(events)
        if status in {"error", "stopped", "cancelled"}:
            raise ProviderError(f"OpenHands conversation ended with status {status}")
        if status == "finished":
            return await self._final_assistant_text(client, headers, conv_id)
        raise TransientProviderError(
            f"OpenHands conversation {conv_id} did not finish within {int(self.max_wait_s)}s"
        )

    @staticmethod
    def _execution_status_from_events(events: list[dict]) -> str:
        """Latest authoritative execution_status recorded in the event stream."""
        for event in reversed(events):
            if event.get("kind") != "ConversationStateUpdateEvent":
                continue
            if event.get("key") != "execution_status":
                continue
            value = event.get("value")
            if isinstance(value, str):
                return value.lower()
        return ""

    async def _final_assistant_text(self, client, headers, conv_id: str) -> str:
        # Conversation events are indexed slightly after execution_status turns
        # terminal, so poll briefly instead of accepting a transient empty page.
        deadline = asyncio.get_running_loop().time() + _FINAL_TEXT_GRACE_S
        while True:
            events = await self._all_events(client, headers, conv_id)
            text = self._latest_assistant_text(events)
            if text:
                return text
            if asyncio.get_running_loop().time() >= deadline:
                return ""
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _all_events(self, client, headers, conv_id: str) -> list[dict]:
        """Return every event in chronological order, following the paging cursor.

        ``events/search`` returns events oldest-first and exposes ``next_page_id``
        as the offset of the next (newer) page. A single page is not enough: the
        final assistant message of a real conversation usually sits on the last
        page. Walk the cursor to the end (bounded) so the newest events are
        actually seen.
        """
        events: list[dict] = []
        page_id: Optional[Any] = None
        for _ in range(_MAX_EVENT_PAGES):
            params: dict[str, Any] = {"limit": _EVENTS_PAGE_LIMIT}
            if page_id is not None:
                params["page_id"] = page_id
            r = await client.get(
                f"{self.base_url}/api/v1/conversation/{conv_id}/events/search",
                headers=headers, params=params,
            )
            self._raise_for_status(r)
            payload = r.json()
            events.extend(_as_items(payload))
            next_page_id = payload.get("next_page_id") if isinstance(payload, dict) else None
            # ``None``/0 means the last page; stop rather than looping forever.
            if next_page_id in (None, 0) or next_page_id == page_id:
                break
            page_id = next_page_id
        return events

    @classmethod
    def _latest_assistant_text(cls, events: list[dict]) -> str:
        """Latest non-empty assistant message text, or "" when there is none."""
        for event in reversed(events):
            if event.get("kind") != "MessageEvent":
                continue
            message = event.get("llm_message") or event.get("message") or event.get("content")
            role = event.get("source")
            if isinstance(message, dict):
                role = message.get("role") or role
            # OpenHands labels assistant turns "agent" on some deployments.
            if role not in {"assistant", "agent"}:
                continue
            text = cls._message_text(event)
            if text and text.strip():
                return text
        return ""

    @staticmethod
    def _message_text(event: dict) -> str:
        message = (
            event.get("llm_message")
            or event.get("message")
            or event.get("content")
        )
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "\n".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("text")
                )
        if isinstance(message, list):
            return "\n".join(
                part.get("text", "")
                for part in message
                if isinstance(part, dict) and part.get("text")
            )
        return ""

    # ------------------------------------------------------------------ helpers
    def _build_prompt(self, req: CompletionRequest) -> str:
        parts: List[str] = []
        system = req.system or ""
        for message in req.messages:
            if message.role == "system" and not system:
                system = message.content
        if system:
            parts.append(f"# Instructions\n{system}")
        for message in req.messages:
            if message.role == "system":
                continue
            label = "Request" if message.role == "user" else message.role.capitalize()
            parts.append(f"# {label}\n{message.content}")
        if req.json_mode:
            parts.append(
                "# Output format\nReply with a single JSON object and nothing else. "
                "No markdown fences, no commentary."
            )
        return "\n\n".join(parts)

    @staticmethod
    def _raise_for_status(response) -> None:
        status = response.status_code
        if status < 400:
            return
        retry_after = None
        try:
            header = response.headers.get("retry-after")
            retry_after = float(header) if header else None
        except (TypeError, ValueError):
            retry_after = None
        message = f"OpenHands API error HTTP {status}"
        if status in (429, 500, 502, 503, 504):
            if classify_transient(Exception(message)):
                raise TransientProviderError(message, status_code=status, retry_after=retry_after)
        raise ProviderError(message, status_code=status)


def configured_openhands_provider() -> Optional[LLMProvider]:
    """Build the provider only when it is actually configured.

    An unconfigured provider must not sit in the registry advertising a
    capability it cannot serve, so this returns ``None`` without a key.
    """
    if not os.environ.get("OPENHANDS_API_KEY", "").strip():
        return None
    model = os.environ.get("OPENHANDS_PROVIDER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return OpenHandsProvider(model=model)
