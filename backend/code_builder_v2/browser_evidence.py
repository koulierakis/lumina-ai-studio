from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import BrowserEvidence


@dataclass
class BrowserSession:
    browser: Any = None
    context: Any = None
    page: Any = None
    playwright: Any = None


class BrowserEvidenceCollector:
    def __init__(self, runtime_root: Path, headless: bool = True):
        self.runtime_root = runtime_root
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()

    async def _get_playwright(self):
        from playwright.async_api import async_playwright
        return await async_playwright().start()

    async def create_session(self, session_id: str) -> BrowserSession:
        async with self._lock:
            if session_id in self._sessions:
                await self.close_session(session_id)

            playwright = await self._get_playwright()
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True,
            )
            page = await context.new_page()

            session = BrowserSession(
                browser=browser,
                context=context,
                page=page,
                playwright=playwright,
            )
            self._sessions[session_id] = session
            return session

    async def get_session(self, session_id: str) -> BrowserSession | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            try:
                if session.page:
                    await session.page.close()
                if session.context:
                    await session.context.close()
                if session.browser:
                    await session.browser.close()
                if session.playwright:
                    await session.playwright.stop()
            except Exception:
                pass

    async def collect_evidence(
        self,
        url: str,
        session_id: str | None = None,
        wait_for_selector: str | None = None,
        wait_for_timeout: int = 10000,
        take_screenshot: bool = True,
        expected_text: str | None = None,
    ) -> BrowserEvidence:
        if session_id is None:
            session_id = f"session_{int(time.time() * 1000)}"

        session = await self.create_session(session_id)
        page = session.page
        evidence = BrowserEvidence(page_url=url)
        console_errors: list[str] = []
        network_errors: list[str] = []
        uncaught_exceptions: list[str] = []

        def handle_console(msg):
            if msg.type == "error":
                console_errors.append(f"[{msg.type}] {msg.text}")

        def handle_page_error(error):
            uncaught_exceptions.append(str(error))

        def handle_response(response):
            if response.status >= 400:
                network_errors.append(f"{response.status} {response.url}")

        page.on("console", handle_console)
        page.on("pageerror", handle_page_error)
        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=wait_for_timeout)
            evidence.page_loaded = True

            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=wait_for_timeout)
                except Exception:
                    pass

            await page.wait_for_load_state("networkidle", timeout=wait_for_timeout)

            if expected_text:
                try:
                    await page.wait_for_function(
                        f"document.body.innerText.includes('{expected_text}')",
                        timeout=wait_for_timeout,
                    )
                except Exception:
                    pass

            evidence.console_errors = console_errors
            evidence.network_errors = network_errors
            evidence.uncaught_exceptions = uncaught_exceptions

            if take_screenshot:
                screenshot_dir = self.runtime_root / "screenshots"
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = screenshot_dir / f"{session_id}_{int(time.time())}.png"
                await page.screenshot(path=str(screenshot_path), full_page=True)
                evidence.screenshot_path = str(screenshot_path)

            evidence.page_content = await page.content()

        except Exception as exc:
            evidence.page_loaded = False
            evidence.console_errors = console_errors
            evidence.network_errors = network_errors
            evidence.uncaught_exceptions = uncaught_exceptions + [f"Navigation failed: {exc}"]
        finally:
            await self.close_session(session_id)

        return evidence

    async def interact_and_collect(
        self,
        url: str,
        interactions: list[dict[str, Any]],
        session_id: str | None = None,
        wait_for_timeout: int = 10000,
        take_screenshot: bool = True,
    ) -> BrowserEvidence:
        if session_id is None:
            session_id = f"session_{int(time.time() * 1000)}"

        session = await self.create_session(session_id)
        page = session.page
        evidence = BrowserEvidence(page_url=url)
        console_errors: list[str] = []
        network_errors: list[str] = []
        uncaught_exceptions: list[str] = []

        def handle_console(msg):
            if msg.type == "error":
                console_errors.append(f"[{msg.type}] {msg.text}")

        def handle_page_error(error):
            uncaught_exceptions.append(str(error))

        def handle_response(response):
            if response.status >= 400:
                network_errors.append(f"{response.status} {response.url}")

        page.on("console", handle_console)
        page.on("pageerror", handle_page_error)
        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=wait_for_timeout)
            evidence.page_loaded = True
            await page.wait_for_load_state("networkidle", timeout=wait_for_timeout)

            for interaction in interactions:
                action = interaction.get("action")
                selector = interaction.get("selector")
                value = interaction.get("value")

                if action == "click" and selector:
                    await page.click(selector, timeout=5000)
                elif action == "fill" and selector and value is not None:
                    await page.fill(selector, value, timeout=5000)
                elif action == "wait" and selector:
                    await page.wait_for_selector(selector, timeout=wait_for_timeout)
                elif action == "wait_for_function" and value:
                    await page.wait_for_function(value, timeout=wait_for_timeout)

                await page.wait_for_load_state("networkidle", timeout=3000)

            evidence.console_errors = console_errors
            evidence.network_errors = network_errors
            evidence.uncaught_exceptions = uncaught_exceptions

            if take_screenshot:
                screenshot_dir = self.runtime_root / "screenshots"
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = screenshot_dir / f"{session_id}_{int(time.time())}.png"
                await page.screenshot(path=str(screenshot_path), full_page=True)
                evidence.screenshot_path = str(screenshot_path)

            evidence.page_content = await page.content()

        except Exception as exc:
            evidence.page_loaded = False
            evidence.console_errors = console_errors
            evidence.network_errors = network_errors
            evidence.uncaught_exceptions = uncaught_exceptions + [f"Interaction failed: {exc}"]
        finally:
            await self.close_session(session_id)

        return evidence

    async def cleanup_all(self) -> None:
        session_ids = list(self._sessions.keys())
        for session_id in session_ids:
            await self.close_session(session_id)


def run_browser_check(
    url: str,
    runtime_root: Path,
    headless: bool = True,
    wait_for_selector: str | None = None,
    expected_text: str | None = None,
) -> BrowserEvidence:
    async def _run():
        collector = BrowserEvidenceCollector(runtime_root, headless=headless)
        try:
            return await collector.collect_evidence(
                url=url,
                wait_for_selector=wait_for_selector,
                expected_text=expected_text,
            )
        finally:
            await collector.cleanup_all()

    return asyncio.run(_run())


def run_browser_interaction(
    url: str,
    interactions: list[dict[str, Any]],
    runtime_root: Path,
    headless: bool = True,
) -> BrowserEvidence:
    async def _run():
        collector = BrowserEvidenceCollector(runtime_root, headless=headless)
        try:
            return await collector.interact_and_collect(
                url=url,
                interactions=interactions,
            )
        finally:
            await collector.cleanup_all()

    return asyncio.run(_run())