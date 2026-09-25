"""LUMINA Mind orchestrator.

Understands a user request, selects an existing LUMINA capability from the
registry, executes it through the real API surface, and records the outcome so
context survives across turns. High-impact operations (destructive, financial,
legal-signature, publishing, credential, repository-apply) are gated behind an
explicit approval that is persisted per session until confirmed or declined.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .client import CapabilityExecutionError, MindCapabilityClient
from .intent import ResolvedIntent, detect_confirmation, resolve_intent
from .registry import CAPABILITY_REGISTRY


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str, ensure_ascii=False))
    except Exception:
        return str(value)


class MindOrchestrator:
    def __init__(
        self,
        client: MindCapabilityClient | None = None,
        root: Path | None = None,
    ) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        configured_root = os.environ.get("LUMINA_MIND_STATE_DIR", "").strip()
        self.root = root or (Path(configured_root) if configured_root else repository_root / ".lumina" / "mind")
        self.root.mkdir(parents=True, exist_ok=True)
        self.actions_path = self.root / "actions.json"
        self.pending_path = self.root / "pending.json"
        self.client = client or MindCapabilityClient()
        self._actions = self._load(self.actions_path)
        self._pending_map = self._load(self.pending_path)

    # ------------------------------------------------------------------ state
    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return {"entries": []}

    @staticmethod
    def _save(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(path)

    def _flush(self) -> None:
        self._save(self.actions_path, self._actions)
        self._save(self.pending_path, self._pending_map)

    # ------------------------------------------------------------- capability
    def catalog(self) -> list[dict[str, Any]]:
        return [capability.describe() for capability in CAPABILITY_REGISTRY.values()]

    def resolve(self, message: str, context: dict[str, Any] | None = None) -> ResolvedIntent | None:
        return resolve_intent(message, context)

    def confirm_decision(self, message: str) -> str | None:
        return detect_confirmation(message)

    # ---------------------------------------------------------------- pending
    def pending(self, owner: str, session_id: str | None) -> dict[str, Any] | None:
        entries = self._pending_map.setdefault("entries", [])
        candidates = [
            entry
            for entry in entries
            if entry.get("owner") == owner and entry.get("session_id") == (session_id or entry.get("session_id"))
        ]
        return candidates[-1] if candidates else None

    def _record_pending(
        self,
        owner: str,
        session_id: str | None,
        capability: str,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        pending = {
            "id": uuid4().hex,
            "owner": owner,
            "session_id": session_id,
            "capability": capability,
            "action": action,
            "params": _json_safe(params),
            "created_at": time.time(),
        }
        entries = self._pending_map.setdefault("entries", [])
        entries[:] = [
            entry
            for entry in entries
            if not (
                entry.get("owner") == owner
                and entry.get("session_id") == session_id
                and entry.get("capability") == capability
                and entry.get("action") == action
            )
        ]
        entries.append(pending)
        entries[:] = entries[-50:]
        self._flush()
        return pending

    def _drop_pending(self, owner: str, session_id: str | None, capability: str, action: str) -> None:
        entries = self._pending_map.setdefault("entries", [])
        entries[:] = [
            entry
            for entry in entries
            if not (
                entry.get("owner") == owner
                and entry.get("session_id") == session_id
                and entry.get("capability") == capability
                and entry.get("action") == action
            )
        ]
        self._flush()

    async def _followup_pending(
        self,
        owner: str,
        session_id: str | None,
        capability_id: str,
        action: str,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Register an approval gate for processes ending in a reviewable state.

        Currently: a code_builder plan lands in ``awaiting_approval``; the
        follow-up ``execute`` (which applies repository changes, an
        approval-level risk) must be confirmed by the owner in a later turn.

        The real backend returns the plan task nested under ``{"task": {...}}``
        and starts it asynchronously, so a non-reviewable initial state is
        polled (bounded) through ``get_task`` until it becomes reviewable or
        terminal.
        """
        if not (capability_id == "code_builder" and action == "plan"):
            return None
        if not isinstance(result, dict):
            return None
        task = result.get("task") if isinstance(result.get("task"), dict) else result
        task_id = task.get("id")
        status = str(task.get("status") or "").lower()

        if not task_id:
            return None
        if status in {"awaiting_approval", "approval_required"}:
            pending = self._record_pending(owner, session_id, capability_id, "execute", {"task_id": task_id})
            return {
                "capability": capability_id,
                "action": "execute",
                "params": {"task_id": task_id},
                "pending_id": pending["id"],
            }

        reviewable = {"awaiting_approval", "approval_required"}
        terminal = {
            "completed", "failed", "cancelled", "canceled", "rejected", "error",
            "applied", "rolled_back", "resolved",
        }
        if status in terminal or status in reviewable:
            return None

        get_task = CAPABILITY_REGISTRY["code_builder"].operations.get("get_task")
        if get_task is None:
            return None
        for _ in range(24):
            await asyncio.sleep(1.5)
            try:
                polled = await self.client.execute(get_task, owner, {"task_id": task_id})
            except CapabilityExecutionError:
                break
            if not isinstance(polled, dict):
                break
            task = polled.get("task") if isinstance(polled.get("task"), dict) else polled
            status = str(task.get("status") or "").lower()
            if status in reviewable:
                pending = self._record_pending(owner, session_id, capability_id, "execute", {"task_id": task_id})
                return {
                    "capability": capability_id,
                    "action": "execute",
                    "params": {"task_id": task_id},
                    "pending_id": pending["id"],
                }
            if status in terminal:
                break
        return None

    # ---------------------------------------------------------------- journal
    def recent_actions(self, owner: str, limit: int = 12) -> list[dict[str, Any]]:
        entries = [
            entry
            for entry in self._actions.get("entries", [])
            if entry.get("owner") == owner
        ]
        return sorted(entries, key=lambda entry: entry.get("created_at") or 0, reverse=True)[:limit]

    def list_actions(self, owner: str) -> list[dict[str, Any]]:
        return self.recent_actions(owner, limit=50)

    def _journal(
        self,
        owner: str,
        session_id: str | None,
        capability: str,
        action: str,
        params: dict[str, Any],
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        risk: str = "auto",
    ) -> dict[str, Any]:
        entry = {
            "id": uuid4().hex,
            "owner": owner,
            "session_id": session_id,
            "created_at": time.time(),
            "capability": capability,
            "action": action,
            "risk": risk,
            "params": _json_safe(params),
            "status": status,
            "result": _json_safe(result),
            "error": error,
        }
        entries = self._actions.setdefault("entries", [])
        entries.append(entry)
        entries[:] = entries[-200:]
        self._flush()
        return entry

    # --------------------------------------------------------------- execute
    async def execute(
        self,
        owner: str,
        capability_id: str,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
        session_id: str | None = None,
        journal: bool = True,
    ) -> dict[str, Any]:
        """Run a real capability operation.

        Approval-required actions only execute after an explicit ``confirmed``
        decision; otherwise the plan is persisted as pending and returned without
        side effects.
        """
        params = params or {}
        try:
            capability = CAPABILITY_REGISTRY[capability_id]
        except KeyError as exc:
            raise CapabilityExecutionError(400, f"Unknown capability: {capability_id}") from exc
        try:
            operation = capability.operations[action]
        except KeyError as exc:
            raise CapabilityExecutionError(400, f"Unknown action {action!r} for capability {capability_id!r}") from exc

        missing = [name for name in operation.required_params if not params.get(name)]
        if missing:
            raise CapabilityExecutionError(400, f"Missing required parameter(s): {', '.join(missing)}")

        if operation.risk == "approval" and not confirmed:
            pending = self._record_pending(owner, session_id, capability_id, action, params)
            if journal:
                self._journal(
                    owner, session_id, capability_id, action, params,
                    status="needs_approval", risk=operation.risk,
                )
            return {
                "status": "needs_approval",
                "capability": capability_id,
                "action": action,
                "risk": "approval",
                "params": _json_safe(params),
                "pending_id": pending["id"],
                "message": "This action requires explicit approval before execution.",
            }

        try:
            result = await self.client.execute(operation, owner, params)
            outcome = summarize_result(operation, result)
            if journal:
                self._journal(
                    owner, session_id, capability_id, action, params,
                    status="completed", result=outcome, risk=operation.risk,
                )
            self._drop_pending(owner, session_id, capability_id, action)
            response: dict[str, Any] = {
                "status": "executed",
                "capability": capability_id,
                "action": action,
                "risk": operation.risk,
                "result": _json_safe(outcome),
            }
            followup = await self._followup_pending(owner, session_id, capability_id, action, result)
            if followup:
                response["next"] = "approval_required"
                response["pending"] = followup
            return response
        except CapabilityExecutionError as exc:
            if journal:
                self._journal(
                    owner, session_id, capability_id, action, params,
                    status="failed", error=exc.message, risk=operation.risk,
                )
            return {
                "status": "failed",
                "capability": capability_id,
                "action": action,
                "risk": operation.risk,
                "error": exc.message,
                "detail": exc.response,
            }

    async def handle_decision(
        self,
        owner: str,
        session_id: str | None,
        message: str,
    ) -> dict[str, Any] | None:
        """Process an explicit approve/decline for the stored pending action."""
        decision = self.confirm_decision(message)
        if decision is None:
            return None
        pending = self.pending(owner, session_id)
        if pending is None:
            return {"status": "no_pending_action", "decision": decision}
        if decision == "approve":
            return await self.execute(
                owner,
                pending["capability"],
                pending["action"],
                pending.get("params") or {},
                confirmed=True,
                session_id=session_id,
            )
        if decision == "decline":
            self._drop_pending(owner, session_id, pending["capability"], pending["action"])
            self._journal(
                owner, session_id, pending["capability"], pending["action"],
                pending.get("params") or {}, status="declined", risk="approval",
            )
            return {
                "status": "declined",
                "capability": pending["capability"],
                "action": pending["action"],
                "message": "The pending action was cancelled and will not be executed.",
            }
        return None


def summarize_result(operation: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Compact, JSON-safe summary of a real capability result for LLM grounding."""
    if isinstance(result, list):
        items = result[:12]
        return {
            "count": len(items),
            "items": [
                {key: item.get(key) for key in ("id", "title", "name", "filename", "prompt", "status") if item.get(key) is not None}
                for item in items if isinstance(item, dict)
            ],
        }
    if not isinstance(result, dict):
        return {"raw": str(result)[:400]}
    summary: dict[str, Any] = {}
    for field in operation.summary_fields or ():
        if field in ("items",):
            items = result.get("items") or []
            summary["count"] = len(items)
            summary["items"] = [
                {key: item.get(key) for key in ("id", "title", "name", "filename", "prompt", "status") if item.get(key) is not None}
                for item in items[:8]
            ]
            continue
        if field in result and result[field] is not None:
            summary[field] = result[field]
    if operation.id == "plan" and isinstance(result.get("plan"), dict):
        plan = result["plan"]
        summary["plan_summary"] = plan.get("summary")
        summary["planned_changes"] = len(plan.get("changes") or [])
        summary["paths"] = [change.get("path") for change in (plan.get("changes") or [])][:10]
    if not summary:
        summary = {
            key: result[key]
            for key in ("id", "title", "name", "status", "count")
            if result.get(key) is not None
        }
    return summary


def orchestration_context(entry: dict[str, Any]) -> str:
    """Human-readable context block describing an executed capability action."""
    status = entry.get("status")
    capability = entry.get("capability")
    action = entry.get("action")
    result = entry.get("result") or {}
    error = entry.get("error")
    header = (
        "LUMINA capability status:"
        if status in {"needs_approval", "declined", "error", "none"}
        else "LUMINA capability results:"
    )
    parts = [header, f"- Capability: {capability or '?'} / {action or '?'}"]
    if status == "needs_approval":
        parts.append("  Status: awaiting owner approval (not executed).")
    elif status == "declined":
        parts.append("  Status: declined by owner; nothing was executed.")
    elif status == "failed":
        parts.append(f"  Status: failed — {error or 'unknown error'}")
    else:
        details = ", ".join(f"{key}={value}" for key, value in (result or {}).items())
        parts.append(f"  Status: executed. Result: {details or 'ok'}")
    if entry.get("next") == "approval_required" and isinstance(entry.get("pending"), dict):
        pending = entry["pending"]
        parts.append(
            f"  Next: the {pending.get('capability')}/{pending.get('action')} step "
            f"(params {pending.get('params')}) requires explicit owner approval; nothing was executed yet."
        )
    return "\n".join(parts)


CAPABILITY_CATALOG_TEXT = "\n".join(
    f"- {capability.id}: {capability.name} — {capability.description}"
    for capability in CAPABILITY_REGISTRY.values()
)