"""Shared owner-private platform actions and notification helpers."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

def notification_key(category: str, resource_type: str, resource_id: str, state: str) -> str:
    return f"{category}:{resource_type}:{resource_id}:{state}"

async def emit_notification(repo: Any, owner: str, category: str, title: str, message: str, resource_type: str, resource_id: str, source_module: str = "workspace") -> None:
    """Persist one safe lifecycle notification; duplicate transitions are ignored."""
    key = notification_key(category, resource_type, resource_id, category)
    exists = await repo.find_one({"owner_email": owner, "dedupe_key": key})
    if exists:
        return
    await repo.insert_one({"id": f"notice-{resource_id}-{category}", "owner_email": owner, "type": category, "title": title, "message": message[:500], "resource_type": resource_type, "resource_id": resource_id, "source_module": source_module, "read": False, "dedupe_key": key, "created_at": datetime.now(timezone.utc).isoformat()})
