"""Opt-in lifecycle markers containing metadata only, never prompts or responses."""
from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path


def mark(event: str, **metadata) -> None:
    if os.environ.get("GOLD_BUILDER_PROGRESS") != "1":
        return
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **metadata}
    line = json.dumps(record, sort_keys=True)
    print(line, flush=True)
    destination = os.environ.get("GOLD_BUILDER_PROGRESS_PATH")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(line + "\n")


@asynccontextmanager
async def stage(name: str, **metadata):
    started = time.monotonic()
    mark(name + " START", **metadata)
    try:
        yield
    except BaseException as exc:
        mark(name + " ERROR", error_type=type(exc).__name__,
             elapsed_s=round(time.monotonic() - started, 3), **metadata)
        raise
    else:
        mark(name + " COMPLETE", elapsed_s=round(time.monotonic() - started, 3), **metadata)


def traced(name: str):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            async with stage(name):
                return await function(*args, **kwargs)
        return wrapped
    return decorate
