"""Owner-private productivity modules for Lumina: Finance, Research and Automations."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from auth import require_owner
from persistence import LocalPersistenceCollection, PersistenceProvider, SQLitePersistenceProvider
from platform_services import emit_notification

router = APIRouter(tags=["productivity"])
_provider: PersistenceProvider | None = None
_records: LocalPersistenceCollection | None = None
_notifications: LocalPersistenceCollection | None = None
_scheduler_task: asyncio.Task | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def configure_productivity_router(provider: PersistenceProvider) -> None:
    global _provider, _records, _notifications
    if not isinstance(provider, SQLitePersistenceProvider):
        raise RuntimeError("Productivity modules currently require Lumina local SQLite persistence.")
    _provider = provider
    _records = LocalPersistenceCollection(provider, "preferences")
    _notifications = LocalPersistenceCollection(provider, "notifications")


def _repos() -> tuple[LocalPersistenceCollection, LocalPersistenceCollection]:
    if _records is None or _notifications is None:
        raise RuntimeError("Productivity router is not configured.")
    return _records, _notifications


async def _list_kind(owner: str, kind: str) -> list[dict[str, Any]]:
    records, _ = _repos()
    cursor = records.find({"owner_email": owner, "kind": kind}, {"_id": 0}).sort("updated_at", -1)
    return [row async for row in cursor]


def _record(kind: str, owner: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    return {
        "id": str(uuid4()),
        "owner_email": owner,
        "kind": kind,
        "created_at": now,
        "updated_at": now,
        **payload,
    }


def _require_currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("Currency must be a 3-letter code such as EUR or USD.")
    return normalized


class FinanceEntryInput(BaseModel):
    direction: Literal["income", "expense"]
    amount_cents: int = Field(gt=0, le=10_000_000_000_00)
    currency: str = "EUR"
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=240)
    occurred_on: str = Field(min_length=10, max_length=10)
    notes: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return _require_currency(value)

    @field_validator("occurred_on")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("occurred_on must use YYYY-MM-DD.") from exc
        return value


class FinanceEntryPatch(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, min_length=1, max_length=240)
    notes: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)


@router.get("/api/finance/entries")
async def finance_entries(owner: str = Depends(require_owner)) -> list[dict[str, Any]]:
    return await _list_kind(owner, "finance_entry")


@router.post("/api/finance/entries", status_code=201)
async def finance_create(body: FinanceEntryInput, owner: str = Depends(require_owner)) -> dict[str, Any]:
    records, _ = _repos()
    row = _record("finance_entry", owner, body.model_dump())
    await records.insert_one(row)
    return row


@router.patch("/api/finance/entries/{entry_id}")
async def finance_update(entry_id: str, body: FinanceEntryPatch, owner: str = Depends(require_owner)) -> dict[str, Any]:
    records, _ = _repos()
    current = await records.find_one({"id": entry_id, "owner_email": owner, "kind": "finance_entry"}, {"_id": 0})
    if not current:
        raise HTTPException(404, "Finance entry not found.")
    changes = {key: value for key, value in body.model_dump().items() if value is not None}
    changes["updated_at"] = _now_iso()
    current.update(changes)
    await records.replace_one({"id": entry_id, "owner_email": owner}, current)
    return current


@router.delete("/api/finance/entries/{entry_id}", status_code=204)
async def finance_delete(entry_id: str, owner: str = Depends(require_owner)) -> None:
    records, _ = _repos()
    result = await records.delete_one({"id": entry_id, "owner_email": owner, "kind": "finance_entry"})
    if not result.deleted_count:
        raise HTTPException(404, "Finance entry not found.")


@router.get("/api/finance/summary")
async def finance_summary(owner: str = Depends(require_owner)) -> dict[str, Any]:
    rows = await _list_kind(owner, "finance_entry")
    month = _now().strftime("%Y-%m")
    year = _now().strftime("%Y")

    def aggregate(prefix: str) -> dict[str, dict[str, int]]:
        totals: dict[str, dict[str, int]] = {}
        for row in rows:
            if not str(row.get("occurred_on") or "").startswith(prefix):
                continue
            currency = str(row.get("currency") or "EUR")
            bucket = totals.setdefault(currency, {"income_cents": 0, "expense_cents": 0, "net_cents": 0})
            amount = int(row.get("amount_cents") or 0)
            if row.get("direction") == "income":
                bucket["income_cents"] += amount
            else:
                bucket["expense_cents"] += amount
            bucket["net_cents"] = bucket["income_cents"] - bucket["expense_cents"]
        return totals

    return {
        "month": month,
        "year": year,
        "month_totals": aggregate(month),
        "year_totals": aggregate(year),
        "entry_count": len(rows),
    }


class ResearchInput(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    query: str = Field(default="", max_length=500)
    source_url: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=20_000)
    findings: str = Field(default="", max_length=60_000)
    status: Literal["open", "reviewed", "archived"] = "open"
    tags: list[str] = Field(default_factory=list, max_length=30)


class ResearchPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    query: str | None = Field(default=None, max_length=500)
    source_url: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=20_000)
    findings: str | None = Field(default=None, max_length=60_000)
    status: Literal["open", "reviewed", "archived"] | None = None
    tags: list[str] | None = Field(default=None, max_length=30)


class UrlFetchInput(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    title: str = Field(default="", max_length=180)
    save: bool = True


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()[:180]
        if not self._skip:
            self.parts.append(text)


def _validate_public_url(raw: str) -> str:
    parsed = urlparse(raw.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http/https URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in URLs are not allowed.")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Only standard web ports are allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("The source hostname could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("Private or local network URLs are not allowed.")
    return raw.strip()


def _fetch_public_source(url: str) -> dict[str, Any]:
    safe_url = _validate_public_url(url)
    request = Request(safe_url, headers={"User-Agent": "LuminaResearch/1.0", "Accept": "text/html,text/plain;q=0.9"})
    with urlopen(request, timeout=12) as response:  # noqa: S310 - URL is explicitly validated above
        final_url = _validate_public_url(response.geturl())
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type and "text/plain" not in content_type:
            raise ValueError("The source is not HTML or plain text.")
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("The source is larger than the 1 MB research import limit.")
        charset = response.headers.get_content_charset() or "utf-8"
    text = raw.decode(charset, errors="replace")
    if "text/html" in content_type:
        parser = _TextExtractor()
        parser.feed(text)
        body = "\n".join(parser.parts)
        title = parser.title
    else:
        body = text
        title = ""
    normalized = "\n".join(line.strip() for line in body.splitlines() if line.strip())
    return {"url": final_url, "title": title, "text": normalized[:60_000], "fetched_at": _now_iso()}


@router.get("/api/research/items")
async def research_items(owner: str = Depends(require_owner)) -> list[dict[str, Any]]:
    return await _list_kind(owner, "research_item")


@router.post("/api/research/items", status_code=201)
async def research_create(body: ResearchInput, owner: str = Depends(require_owner)) -> dict[str, Any]:
    records, _ = _repos()
    row = _record("research_item", owner, body.model_dump())
    await records.insert_one(row)
    return row


@router.patch("/api/research/items/{item_id}")
async def research_update(item_id: str, body: ResearchPatch, owner: str = Depends(require_owner)) -> dict[str, Any]:
    records, _ = _repos()
    current = await records.find_one({"id": item_id, "owner_email": owner, "kind": "research_item"}, {"_id": 0})
    if not current:
        raise HTTPException(404, "Research item not found.")
    current.update({key: value for key, value in body.model_dump().items() if value is not None})
    current["updated_at"] = _now_iso()
    await records.replace_one({"id": item_id, "owner_email": owner}, current)
    return current


@router.delete("/api/research/items/{item_id}", status_code=204)
async def research_delete(item_id: str, owner: str = Depends(require_owner)) -> None:
    records, _ = _repos()
    result = await records.delete_one({"id": item_id, "owner_email": owner, "kind": "research_item"})
    if not result.deleted_count:
        raise HTTPException(404, "Research item not found.")


@router.post("/api/research/fetch")
async def research_fetch(body: UrlFetchInput, owner: str = Depends(require_owner)) -> dict[str, Any]:
    try:
        fetched = await asyncio.to_thread(_fetch_public_source, body.url)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if not body.save:
        return fetched
    records, _ = _repos()
    row = _record(
        "research_item",
        owner,
        {
            "title": body.title.strip() or fetched.get("title") or fetched["url"],
            "query": "",
            "source_url": fetched["url"],
            "notes": "",
            "findings": fetched["text"],
            "status": "open",
            "tags": ["web-import"],
            "fetched_at": fetched["fetched_at"],
        },
    )
    await records.insert_one(row)
    return row


class AutomationInput(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    message: str = Field(min_length=1, max_length=1000)
    cadence: Literal["once", "hourly", "daily", "weekly"] = "once"
    run_at: datetime
    enabled: bool = True

    @field_validator("run_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("run_at must include a timezone offset.")
        return value.astimezone(timezone.utc)


class AutomationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    message: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None


def _next_run(current: datetime, cadence: str) -> datetime | None:
    if cadence == "hourly":
        return current + timedelta(hours=1)
    if cadence == "daily":
        return current + timedelta(days=1)
    if cadence == "weekly":
        return current + timedelta(days=7)
    return None


async def _execute_automation(task: dict[str, Any]) -> dict[str, Any]:
    records, notifications = _repos()
    owner = str(task["owner_email"])
    task_id = str(task["id"])
    run_count = int(task.get("run_count") or 0) + 1
    await emit_notification(
        notifications,
        owner,
        f"automation-{run_count}",
        str(task.get("title") or "Lumina automation"),
        str(task.get("message") or "Scheduled task completed."),
        "automation",
        f"{task_id}-{run_count}",
        "automations",
    )
    now = _now()
    next_dt = _next_run(now, str(task.get("cadence") or "once"))
    task.update(
        {
            "last_run_at": now.isoformat(),
            "run_count": run_count,
            "next_run_at": next_dt.isoformat() if next_dt else None,
            "enabled": bool(next_dt),
            "updated_at": now.isoformat(),
        }
    )
    await records.replace_one({"id": task_id, "owner_email": owner}, task)
    return task


@router.get("/api/automations/tasks")
async def automation_tasks(owner: str = Depends(require_owner)) -> list[dict[str, Any]]:
    return await _list_kind(owner, "automation_task")


@router.post("/api/automations/tasks", status_code=201)
async def automation_create(body: AutomationInput, owner: str = Depends(require_owner)) -> dict[str, Any]:
    records, _ = _repos()
    run_at = body.run_at.astimezone(timezone.utc)
    row = _record(
        "automation_task",
        owner,
        {
            "title": body.title,
            "message": body.message,
            "cadence": body.cadence,
            "run_at": run_at.isoformat(),
            "next_run_at": run_at.isoformat(),
            "enabled": body.enabled,
            "run_count": 0,
            "last_run_at": None,
        },
    )
    await records.insert_one(row)
    return row


@router.patch("/api/automations/tasks/{task_id}")
async def automation_update(task_id: str, body: AutomationPatch, owner: str = Depends(require_owner)) -> dict[str, Any]:
    records, _ = _repos()
    task = await records.find_one({"id": task_id, "owner_email": owner, "kind": "automation_task"}, {"_id": 0})
    if not task:
        raise HTTPException(404, "Automation task not found.")
    task.update({key: value for key, value in body.model_dump().items() if value is not None})
    task["updated_at"] = _now_iso()
    await records.replace_one({"id": task_id, "owner_email": owner}, task)
    return task


@router.post("/api/automations/tasks/{task_id}/run")
async def automation_run_now(task_id: str, owner: str = Depends(require_owner)) -> dict[str, Any]:
    records, _ = _repos()
    task = await records.find_one({"id": task_id, "owner_email": owner, "kind": "automation_task"}, {"_id": 0})
    if not task:
        raise HTTPException(404, "Automation task not found.")
    return await _execute_automation(task)


@router.delete("/api/automations/tasks/{task_id}", status_code=204)
async def automation_delete(task_id: str, owner: str = Depends(require_owner)) -> None:
    records, _ = _repos()
    result = await records.delete_one({"id": task_id, "owner_email": owner, "kind": "automation_task"})
    if not result.deleted_count:
        raise HTTPException(404, "Automation task not found.")


async def _automation_scheduler_loop() -> None:
    while True:
        await asyncio.sleep(15)
        try:
            records, _ = _repos()
            tasks = [row async for row in records.find({"kind": "automation_task", "enabled": True}, {"_id": 0})]
            now = _now()
            for task in tasks:
                raw = task.get("next_run_at")
                if not raw:
                    continue
                try:
                    due = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
                except ValueError:
                    continue
                if due <= now:
                    await _execute_automation(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Scheduler failures must never crash the Lumina backend.
            continue


def start_productivity_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_automation_scheduler_loop(), name="lumina-productivity-scheduler")


async def stop_productivity_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None:
        return
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None
