"""Structured browser-verification steps.

A verification scenario is a list of `VerificationStep`. Each step has an
`action` and a set of args. The runner executes them in order against a
Playwright page. Every step produces a `VerificationStepResult` with
`ok`, `error`, and optional `screenshot_path`.

Supported actions:
  open           {url}
  reload         {}
  click          {selector}
  fill           {selector, value}
  select         {selector, value | index}
  submit         {selector}                — submit the form containing selector
  wait           {ms | selector}
  assert_text    {selector?, contains | equals}
  assert_visible {selector}
  assert_url     {contains | equals}
  assert_value   {selector, equals}
  assert_count   {selector, equals | at_least}
  screenshot     {name?}

The planner emits a scenario appropriate to the generated app. If no
scenario is emitted the runner falls back to a minimal "open + read title"
scenario so verification still runs.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import VerificationStep, VerificationStepResult, VerificationScenarioResult


DEFAULT_SCENARIO: List[Dict[str, Any]] = [
    {"action": "open"},
    {"action": "wait", "args": {"ms": 500}},
    {"action": "screenshot", "args": {"name": "landing"}},
]


class ScenarioRunner:
    def __init__(self, artifacts: Path):
        self.artifacts = artifacts

    async def run(
        self,
        url: str,
        steps: List[VerificationStep],
        timeout_ms: int = 20000,
    ) -> VerificationScenarioResult:
        try:
            return await self._run_playwright(url, steps, timeout_ms)
        except Exception as e:  # noqa: BLE001
            return VerificationScenarioResult(
                passed=False,
                steps=[],
                error=f"Playwright unavailable or crashed: {e}",
            )

    async def _run_playwright(
        self, url: str, steps: List[VerificationStep], timeout_ms: int,
    ) -> VerificationScenarioResult:
        from playwright.async_api import async_playwright

        console_errors: List[str] = []
        network_errors: List[str] = []
        results: List[VerificationStepResult] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                ctx = await browser.new_context()
                page = await ctx.new_page()

                page.on("console",
                        lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
                        if msg.type == "error" else None)
                page.on("pageerror",
                        lambda err: console_errors.append(f"pageerror: {err}"))
                page.on("requestfailed",
                        lambda req: network_errors.append(f"{req.method} {req.url} — {req.failure}"))
                page.on("response",
                        lambda resp: network_errors.append(f"{resp.status} {resp.url}")
                        if resp.status >= 400 else None)

                # First step always opens (if the first step is not `open`, we open
                # first with the given url).
                if not steps or steps[0].action != "open":
                    steps = [VerificationStep(action="open")] + list(steps)

                http_status: Optional[int] = None
                title: Optional[str] = None

                for i, step in enumerate(steps, start=1):
                    try:
                        shot = await self._execute(
                            page, step, url, timeout_ms, i,
                        )
                        results.append(VerificationStepResult(
                            index=i, action=step.action, ok=True,
                            screenshot_path=shot,
                            args=step.args,
                        ))
                        if step.action == "open":
                            # capture snapshot data
                            try:
                                title = await page.title()
                            except Exception:  # noqa: BLE001
                                title = None
                    except Exception as e:  # noqa: BLE001
                        results.append(VerificationStepResult(
                            index=i, action=step.action, ok=False,
                            error=f"{type(e).__name__}: {e}",
                            args=step.args,
                        ))
                        break

                # capture final screenshot as evidence
                final_shot = self.artifacts / "screenshot.png"
                with _suppress():
                    await page.screenshot(path=str(final_shot), full_page=False)

                # body snippet
                body_text = ""
                with _suppress():
                    body_text = await page.evaluate(
                        "() => document.body ? document.body.innerText : ''"
                    )

                # HTTP status of the last main navigation
                # (Playwright doesn't expose historic responses cleanly; we
                # rely on the network_errors log for 4xx/5xx signals.)
                passed = (
                    all(r.ok for r in results)
                    and not console_errors
                    and not any(e.startswith(("4", "5")) for e in network_errors)
                )
                return VerificationScenarioResult(
                    passed=passed,
                    steps=results,
                    title=title,
                    http_status=http_status,
                    console_errors=console_errors,
                    network_errors=network_errors,
                    screenshot_path=str(final_shot) if final_shot.exists() else None,
                    rendered_text_snippet=(body_text or "")[:400],
                )
            finally:
                await browser.close()

    async def _execute(
        self,
        page,
        step: VerificationStep,
        default_url: str,
        default_timeout: int,
        index: int,
    ) -> Optional[str]:
        a = step.action
        args = step.args or {}
        if a == "open":
            target = args.get("url") or default_url
            await page.goto(target, timeout=default_timeout, wait_until="load")
            return None
        if a == "reload":
            await page.reload(timeout=default_timeout)
            return None
        if a == "click":
            await page.locator(args["selector"]).first.click(timeout=default_timeout)
            return None
        if a == "fill":
            await page.locator(args["selector"]).first.fill(
                str(args.get("value", "")), timeout=default_timeout,
            )
            return None
        if a == "select":
            loc = page.locator(args["selector"]).first
            if "index" in args:
                await loc.select_option(index=int(args["index"]), timeout=default_timeout)
            else:
                await loc.select_option(value=str(args["value"]), timeout=default_timeout)
            return None
        if a == "submit":
            selector = args.get("selector") or "form"
            # Auto-dismiss any dialog
            page.once("dialog", lambda d: asyncio.create_task(d.dismiss()))
            await page.locator(selector).first.evaluate("(el) => el.closest('form').submit()")
            await page.wait_for_timeout(300)
            return None
        if a == "wait":
            if "selector" in args:
                await page.locator(args["selector"]).first.wait_for(
                    timeout=default_timeout, state=args.get("state", "visible"),
                )
            else:
                await page.wait_for_timeout(int(args.get("ms", 500)))
            return None
        if a == "assert_text":
            selector = args.get("selector") or "body"
            text = (await page.locator(selector).first.inner_text(timeout=default_timeout)) or ""
            if "contains" in args:
                needle = str(args["contains"])
                if needle not in text:
                    raise AssertionError(f"expected text to contain {needle!r}, got {text[:120]!r}")
            elif "equals" in args:
                needle = str(args["equals"])
                if text.strip() != needle:
                    raise AssertionError(f"expected text {needle!r}, got {text[:120]!r}")
            return None
        if a == "assert_visible":
            await page.locator(args["selector"]).first.wait_for(
                state="visible", timeout=default_timeout,
            )
            return None
        if a == "assert_url":
            current = page.url
            if "contains" in args and args["contains"] not in current:
                raise AssertionError(f"url {current!r} does not contain {args['contains']!r}")
            if "equals" in args and args["equals"] != current:
                raise AssertionError(f"url {current!r} != {args['equals']!r}")
            return None
        if a == "assert_value":
            v = await page.locator(args["selector"]).first.input_value(timeout=default_timeout)
            if v != args.get("equals"):
                raise AssertionError(f"expected value {args.get('equals')!r}, got {v!r}")
            return None
        if a == "assert_count":
            n = await page.locator(args["selector"]).count()
            if "equals" in args and n != int(args["equals"]):
                raise AssertionError(f"expected count {args['equals']}, got {n}")
            if "at_least" in args and n < int(args["at_least"]):
                raise AssertionError(f"expected at_least {args['at_least']}, got {n}")
            return None
        if a == "screenshot":
            name = args.get("name") or f"step-{index}"
            shot = self.artifacts / f"screenshot-{name}.png"
            await page.screenshot(path=str(shot), full_page=False)
            return str(shot)
        raise ValueError(f"unknown verification action: {a}")


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return True
