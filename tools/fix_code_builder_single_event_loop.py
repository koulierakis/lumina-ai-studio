from pathlib import Path

ROOT = Path.cwd()
TARGET = ROOT / "backend" / "code_builder" / "task_service.py"
TEST = ROOT / "backend" / "tests" / "test_code_builder_single_event_loop.py"

text = TARGET.read_text(encoding="utf-8")

start_marker = "def _run_awaitable_sync(\n"
end_marker = "\n\ndef _analyze_task(\n"
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("_run_awaitable_sync boundaries not found; refusing unsafe patch")

state_marker = "_CODE_BUILDER_ASYNC_STATE = threading.local()"
if state_marker not in text:
    import_anchor = "from typing import Any"
    if import_anchor in text and "import threading\n" not in text[: text.find(start_marker)]:
        text = text.replace(import_anchor, "import threading\n" + import_anchor, 1)
    elif "import threading\n" not in text[: text.find(start_marker)]:
        # Safe fallback: add threading immediately before the helper state.
        pass

    state_block = '''\n\n# A Code Builder worker executes several asynchronous stages from one\n# synchronous pipeline. Reusing one asyncio.Runner per worker thread keeps\n# HTTPX/AnyIO transports on the event loop that created them and prevents\n# cross-stage "Event loop is closed" failures.\n_CODE_BUILDER_ASYNC_STATE = threading.local()\n\n\ndef _worker_async_runner():\n    import asyncio\n\n    runner = getattr(_CODE_BUILDER_ASYNC_STATE, "runner", None)\n    if runner is None:\n        runner = asyncio.Runner()\n        _CODE_BUILDER_ASYNC_STATE.runner = runner\n    return runner\n'''
    text = text[:start] + state_block + "\n" + text[start:]
    start = text.find(start_marker)
    end = text.find(end_marker, start)

new_helper = '''def _run_awaitable_sync(\n    awaitable: Any,\n    *,\n    timeout_seconds: float,\n    operation_name: str,\n) -> Any:\n    """Resolve an awaitable from the synchronous task pipeline safely.\n\n    All async stages executed by the same Code Builder worker thread share\n    one asyncio.Runner/event loop. This is required for async transports such\n    as HTTPX/AnyIO, whose sockets are bound to the loop that created them.\n    """\n\n    import asyncio\n    import inspect\n    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError\n\n    if not inspect.isawaitable(awaitable):\n        return awaitable\n\n    async def _runner() -> Any:\n        task = asyncio.create_task(awaitable)\n        done, pending = await asyncio.wait({task}, timeout=timeout_seconds)\n        if pending:\n            task.cancel()\n            try:\n                await task\n            except BaseException:\n                pass\n            raise TaskTimeoutError(\n                f"{operation_name} timed out.",\n                timeout_seconds=timeout_seconds,\n            )\n        return task.result()\n\n    try:\n        asyncio.get_running_loop()\n    except RuntimeError:\n        try:\n            return _worker_async_runner().run(_runner())\n        except asyncio.TimeoutError as exc:\n            raise TaskTimeoutError(\n                f"{operation_name} timed out."\n            ) from exc\n\n    # Defensive path for callers that already own an event loop. Run the\n    # synchronous bridge in another thread; that thread also gets one stable\n    # runner for the lifetime of its worker invocation.\n    def _run_in_thread() -> Any:\n        return _worker_async_runner().run(_runner())\n\n    with ThreadPoolExecutor(max_workers=1) as executor:\n        future = executor.submit(_run_in_thread)\n        try:\n            return future.result(timeout=timeout_seconds + 5.0)\n        except FutureTimeoutError as exc:\n            future.cancel()\n            raise TaskTimeoutError(\n                f"{operation_name} timed out.",\n                timeout_seconds=timeout_seconds,\n            ) from exc\n'''

text = text[:start] + new_helper + text[end:]
TARGET.write_text(text, encoding="utf-8")

TEST.write_text('''import asyncio\n\nfrom backend.code_builder import task_service\n\n\ndef test_sync_bridge_reuses_one_event_loop_for_worker_thread():\n    seen = []\n\n    async def capture_loop():\n        loop = asyncio.get_running_loop()\n        seen.append(loop)\n        await asyncio.sleep(0)\n        return id(loop)\n\n    first = task_service._run_awaitable_sync(\n        capture_loop(), timeout_seconds=5.0, operation_name="first"\n    )\n    second = task_service._run_awaitable_sync(\n        capture_loop(), timeout_seconds=5.0, operation_name="second"\n    )\n\n    assert first == second\n    assert len(seen) == 2\n    assert seen[0] is seen[1]\n    assert not seen[0].is_closed()\n''', encoding="utf-8")

print("CODE_BUILDER_SINGLE_EVENT_LOOP_PATCH_APPLIED")
