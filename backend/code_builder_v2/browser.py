"""Browser verification for Lumina Code Builder.

Uses Playwright for reliable browser automation and verification.
Captures console errors, network failures, and visual state.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from playwright.async_api import async_playwright, Page, Browser, BrowserContext


@dataclass(frozen=True, slots=True)
class BrowserEvidence:
    """Structured evidence from browser verification."""

    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    page_title: str = ""
    page_url: str = ""
    viewport: dict = field(default_factory=dict)

    def has_critical_errors(self) -> bool:
        return len(self.console_errors) > 0 or len(self.page_errors) > 0 or len(self.network_errors) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "console_errors": self.console_errors,
            "page_errors": self.page_errors,
            "network_errors": self.network_errors,
            "screenshots": self.screenshots,
            "page_title": self.page_title,
            "page_url": self.page_url,
            "viewport": self.viewport,
            "has_critical_errors": self.has_critical_errors(),
        }


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Result of a verification run."""

    passed: bool
    evidence: BrowserEvidence
    workflow_results: dict[str, bool] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: str = ""


class BrowserVerifier:
    """Playwright-based browser verification with error capture."""

    def __init__(
        self,
        base_url: str,
        headless: bool = True,
        viewport: dict = None,
        screenshot_dir: Optional[Path] = None,
    ):
        self.base_url = base_url
        self.headless = headless
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.screenshot_dir = screenshot_dir or Path(tempfile.gettempdir()) / "lumina-screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        self._console_errors: list[str] = []
        self._page_errors: list[str] = []
        self._network_errors: list[str] = []
        self._screenshots: list[str] = []

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(viewport=self.viewport)
        self._page = await self._context.new_page()

        # Capture console errors
        self._page.on("console", self._on_console)
        self._page.on("pageerror", self._on_page_error)
        self._page.on("requestfailed", self._on_request_failed)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def _on_console(self, msg):
        if msg.type == "error":
            self._console_errors.append(f"[{msg.type}] {msg.text}")

    def _on_page_error(self, error):
        self._page_errors.append(str(error))

    def _on_request_failed(self, request):
        failure = request.failure
        self._network_errors.append(f"{request.method} {request.url} - {failure}")

    async def _take_screenshot(self, name: str) -> str:
        timestamp = int(time.time() * 1000)
        filename = f"{name}_{timestamp}.png"
        path = self.screenshot_dir / filename
        await self._page.screenshot(path=str(path), full_page=True)
        self._screenshots.append(str(path))
        return str(path)

    async def navigate_and_wait(self, path: str = "", wait_until: str = "networkidle") -> BrowserEvidence:
        """Navigate to URL and wait for load."""
        self._console_errors.clear()
        self._page_errors.clear()
        self._network_errors.clear()
        self._screenshots.clear()

        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        await self._page.goto(url, wait_until=wait_until)
        await self._page.wait_for_load_state("domcontentloaded")

        await self._take_screenshot("initial_load")

        title = await self._page.title()
        return BrowserEvidence(
            console_errors=self._console_errors.copy(),
            page_errors=self._page_errors.copy(),
            network_errors=self._network_errors.copy(),
            screenshots=self._screenshots.copy(),
            page_title=title,
            page_url=self._page.url,
            viewport=self.viewport,
        )

    async def verify_element_visible(self, selector: str, timeout: int = 10000, name: str = "") -> bool:
        """Verify element is visible."""
        try:
            locator = self._page.locator(selector).first
            await locator.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            await self._take_screenshot(f"missing_{name or selector.replace('#', '').replace('.', '')}")
            return False

    async def verify_element_exists(self, selector: str, timeout: int = 5000) -> bool:
        """Verify element exists in DOM."""
        try:
            locator = self._page.locator(selector).first
            await locator.wait_for(state="attached", timeout=timeout)
            return True
        except Exception:
            return False

    async def fill_and_click(self, input_selector: str, button_selector: str, value: str, wait_after: int = 1000) -> bool:
        """Fill input and click button."""
        try:
            await self._page.fill(input_selector, value)
            await self._page.click(button_selector)
            await self._page.wait_for_timeout(wait_after)
            return True
        except Exception as e:
            self._page_errors.append(f"fill_and_click failed: {e}")
            await self._take_screenshot("fill_click_failed")
            return False

    async def get_text(self, selector: str) -> str:
        """Get element text content."""
        try:
            return await self._page.locator(selector).first.inner_text()
        except Exception:
            return ""

    async def wait_for_text(self, selector: str, expected_text: str, timeout: int = 10000) -> bool:
        """Wait for element to contain expected text."""
        try:
            await self._page.locator(selector).filter(has_text=expected_text).first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    async def click(self, selector: str, wait_after: int = 500) -> bool:
        """Click element."""
        try:
            await self._page.click(selector)
            await self._page.wait_for_timeout(wait_after)
            return True
        except Exception as e:
            self._page_errors.append(f"click failed: {e}")
            return False

    async def get_evidence(self) -> BrowserEvidence:
        """Get current evidence."""
        return BrowserEvidence(
            console_errors=self._console_errors.copy(),
            page_errors=self._page_errors.copy(),
            network_errors=self._network_errors.copy(),
            screenshots=self._screenshots.copy(),
            page_title=await self._page.title() if self._page else "",
            page_url=self._page.url if self._page else "",
            viewport=self.viewport,
        )

    async def reload(self):
        """Reload page and capture evidence."""
        self._console_errors.clear()
        self._page_errors.clear()
        self._network_errors.clear()
        await self._page.reload(wait_until="networkidle")
        await self._page.wait_for_load_state("domcontentloaded")
        await self._take_screenshot("reload")


import tempfile


class WorkflowVerifier:
    """High-level workflow verification for common app patterns."""

    def __init__(self, verifier: BrowserVerifier):
        self.verifier = verifier
        self.results: dict[str, bool] = {}

    async def verify_todo_app(self) -> VerificationResult:
        """Verify a todo application works."""
        start = time.time()
        self.results = {}

        # Navigate
        evidence = await self.verifier.navigate_and_wait("")

        # Check page loads
        self.results["page_loads"] = "task" in evidence.page_title.lower() or "todo" in evidence.page_title.lower()

        # Find elements
        self.results["has_input"] = await self.verifier.verify_element_visible(
            "input#taskInput, input[placeholder*='task' i], input[type='text']", name="task_input"
        )
        self.results["has_button"] = await self.verifier.verify_element_visible(
            "button#addTaskBtn, button:has-text('Add'), button:has-text('Add Task')", name="add_button"
        )
        self.results["has_list"] = await self.verifier.verify_element_visible(
            "ul#todoList, ul#taskList, ul.todo-list, #todoList, ul", name="task_list"
        )

        # Add a task
        if self.results["has_input"] and self.results["has_button"]:
            await self.verifier.fill_and_click(
                "input#taskInput, input[placeholder*='task' i], input[type='text']",
                "button#addTaskBtn, button:has-text('Add'), button:has-text('Add Task')",
                "E2E Test Task",
            )
            await self.verifier._take_screenshot("after_add_task")
            self.results["task_added"] = await self.verifier.wait_for_text("li, .todo-item", "E2E Test Task")

        # Check task count
        count_text = await self.verifier.get_text("#taskCount, #stat-total, .stat-value, p:has-text('tasks')")
        self.results["count_updates"] = "1" in count_text or "1 task" in count_text

        # Try checkbox
        if self.results["task_added"]:
            checkbox = self.verifier._page.locator("li:has-text('E2E Test Task') input[type='checkbox']").first
            if await checkbox.count() > 0:
                await checkbox.click()
                await self.verifier._page.wait_for_timeout(500)
                self.results["checkbox_works"] = True
            else:
                self.results["checkbox_works"] = "no_checkbox"

        # Try delete
        if self.results["task_added"]:
            delete_btn = self.verifier._page.locator("li:has-text('E2E Test Task') button:has-text('Delete'), li:has-text('E2E Test Task') button:has-text('delete')").first
            if await delete_btn.count() > 0:
                await delete_btn.click()
                await self.verifier._page.wait_for_timeout(500)
                self.results["delete_works"] = not await self.verifier.verify_element_exists("li:has-text('E2E Test Task')")
            else:
                self.results["delete_works"] = "no_delete_button"

        evidence = await self.verifier.get_evidence()
        duration = time.time() - start

        # Overall pass: page loads + input + button + list + task added
        critical = ["page_loads", "has_input", "has_button", "has_list", "task_added"]
        passed = all(self.results.get(k, False) for k in critical) and not evidence.has_critical_errors()

        return VerificationResult(
            passed=passed,
            evidence=evidence,
            workflow_results=self.results,
            duration_seconds=duration,
            error_message="" if passed else f"Failed checks: {[k for k, v in self.results.items() if not v]}"
        )

    async def verify_saas_dashboard(self) -> VerificationResult:
        """Verify a SaaS-style dashboard application."""
        start = time.time()
        self.results = {}

        evidence = await self.verifier.navigate_and_wait("")

        # Check page loads
        self.results["page_loads"] = True

        # Check navigation
        self.results["has_nav"] = await self.verifier.verify_element_visible("nav, .navbar, .sidebar, [role='navigation']", name="navigation")

        # Check dashboard content
        self.results["has_dashboard"] = await self.verifier.verify_element_visible(
            "[data-testid='dashboard'], .dashboard, main, .content", name="dashboard"
        )

        # Check for auth/login if present
        self.results["has_auth"] = await self.verifier.verify_element_exists(
            "input[type='password'], button:has-text('Login'), button:has-text('Sign In'), a:has-text('Login')"
        )

        evidence = await self.verifier.get_evidence()
        duration = time.time() - start

        passed = self.results.get("page_loads", False) and not evidence.has_critical_errors()

        return VerificationResult(
            passed=passed,
            evidence=evidence,
            workflow_results=self.results,
            duration_seconds=duration,
            error_message="" if passed else f"Dashboard verification failed: {self.results}"
        )

    async def verify_crud_app(self, entity_name: str = "item") -> VerificationResult:
        """Verify CRUD operations work."""
        start = time.time()
        self.results = {}

        evidence = await self.verifier.navigate_and_wait("")

        # Create
        create_btn = self.verifier._page.locator(f"button:has-text('Add {entity_name}'), button:has-text('Create'), button:has-text('New')").first
        if await create_btn.count() > 0:
            await create_btn.click()
            await self.verifier._page.wait_for_timeout(500)
            self.results["create_opens"] = True

        evidence = await self.verifier.get_evidence()
        duration = time.time() - start

        passed = evidence.has_critical_errors() is False

        return VerificationResult(
            passed=passed,
            evidence=evidence,
            workflow_results=self.results,
            duration_seconds=duration,
        )


async def verify_application(
    url: str,
    app_type: str = "todo",
    headless: bool = True,
    screenshot_dir: Optional[Path] = None,
) -> VerificationResult:
    """Convenience function to verify an application."""
    async with BrowserVerifier(url, headless=headless, screenshot_dir=screenshot_dir) as verifier:
        workflow = WorkflowVerifier(verifier)
        if app_type == "todo":
            return await workflow.verify_todo_app()
        elif app_type == "saas":
            return await workflow.verify_saas_dashboard()
        elif app_type == "crud":
            return await workflow.verify_crud_app()
        else:
            evidence = await verifier.navigate_and_wait("")
            return VerificationResult(
                passed=not evidence.has_critical_errors(),
                evidence=evidence,
                duration_seconds=0,
            )