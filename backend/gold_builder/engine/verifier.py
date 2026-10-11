from __future__ import annotations
"""Real browser verification (Playwright) — Canonical Verification System.

Executes Playwright-based autonomous verifications with:
- Structured multi-step scenario actions (open, reload, click, fill, select, submit, wait, assert_text, assert_element, assert_visible, screenshot)
- Browser telemetry (console errors, page unhandled exceptions, network 4xx/5xx failures)
- Image and video asset load assertions (media_broken detection)
- Automated screenshot evidence saving
- Graceful HTTP fallback if Playwright / headless browser is not provisioned
"""

import asyncio
import ipaddress
import os
import re
import shutil
import socket
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Any, Dict, Iterable, List, Optional

from ..progress import mark, traced
from ..models import Plan, VerificationResult, VerificationStepResult
from .semantic_acceptance import contract_verification_applies, semantic_verification_applies, validate_contract
from .verification_planner import plan_verification_scenario


def _is_executable_file(path: str | Path | None) -> bool:
    if not path:
        return False
    try:
        p = Path(path).expanduser()
        return p.is_file() and os.access(p, os.X_OK)
    except OSError:
        return False


def _chromium_candidates(playwright_default: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get("GB_CHROMIUM_EXECUTABLE")
    if explicit:
        candidates.append(Path(explicit))

    if playwright_default:
        candidates.append(Path(playwright_default))

    roots: list[Path] = []
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured and configured != "0":
        roots.append(Path(configured))
    roots.extend([
        Path.cwd() / ".playwright-browsers",
        Path("/opt/render/project/src/.playwright-browsers"),
        Path("/opt/render/.cache/ms-playwright"),
        Path.home() / ".cache/ms-playwright",
    ])

    patterns = (
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-linux64/chrome",
        "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        "chromium_headless_shell-*/chrome-headless-shell-linux/chrome-headless-shell",
    )
    for root in roots:
        for pattern in patterns:
            try:
                candidates.extend(sorted(root.glob(pattern), reverse=True))
            except OSError:
                pass

    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    # Preserve order but avoid duplicate diagnostics.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _resolve_chromium_executable(playwright_default: str | None = None) -> tuple[str, list[str]]:
    candidates = _chromium_candidates(playwright_default)
    searched = [str(p) for p in candidates]
    for candidate in candidates:
        if _is_executable_file(candidate):
            return str(candidate.resolve()), searched
    raise RuntimeError(
        "Chromium executable not found. Searched: " + ", ".join(searched)
        if searched else "Chromium executable not found; no candidate paths were available"
    )


async def _public_http_target(url: str) -> bool:
    """Resolve an HTTP(S) URL and reject loopback/private/link-local targets."""
    parsed = urlparse(url)
    if parsed.scheme in {"data", "blob", "about"}:
        return True
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return False

    def _resolve() -> list[str]:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]

    try:
        addresses = await asyncio.to_thread(_resolve)
    except (socket.gaierror, OSError):
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    return True


async def _document_declares_icon(url: str) -> bool:
    """Inspect the served document before Chromium's implicit favicon request.

    Browsers synthesize /favicon.ico when no icon is declared. That request is
    browser chrome behaviour, not an application defect. Preflighting the HTML
    lets us suppress only that implicit request while preserving failures for
    icons explicitly declared by the application.
    """
    def _read() -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "GoldBuilder/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read(262144).decode("utf-8", errors="ignore")

    try:
        html = await asyncio.to_thread(_read)
    except Exception:
        return False
    return bool(re.search(
        r"<link\b[^>]*\brel\s*=\s*['\"][^'\"]*\b(?:shortcut\s+)?icon\b[^'\"]*['\"]",
        html,
        flags=re.IGNORECASE,
    ))


def _resolve_navigation_target(preview_url: str, requested: str | None) -> str:
    if not requested:
        return preview_url
    target = urljoin(preview_url, str(requested))
    base = urlparse(preview_url)
    parsed = urlparse(target)

    # Planner contracts commonly contain localhost URLs. Resolve those paths
    # against the actual running preview rather than escaping to another server.
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        suffix = parsed.path or "/"
        if parsed.query:
            suffix += f"?{parsed.query}"
        if parsed.fragment:
            suffix += f"#{parsed.fragment}"
        return urljoin(preview_url, suffix)

    if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
        raise ValueError(f"verification navigation escaped preview origin: {target}")
    return target


def _ensure_responsive_contract(
    scenario: Optional[List[Dict[str, Any]]],
    app_requirements: str,
    requirements: Iterable[Any] = (),
) -> List[Dict[str, Any]]:
    steps = [dict(step) for step in (scenario or [])]
    responsive = bool(re.search(r"\b(mobile|responsive|phone|tablet|small screen|desktop)\b", app_requirements or "", re.I))
    responsive_id = None
    for req in requirements or []:
        kind = (req.get("kind", "") if isinstance(req, dict) else getattr(req, "kind", "")).lower()
        text = req.get("text", "") if isinstance(req, dict) else getattr(req, "text", "")
        if kind == "responsive" or re.search(r"\b(mobile|responsive|phone|tablet|small screen|desktop)\b", text or "", re.I):
            responsive = True
            responsive_id = req.get("id") if isinstance(req, dict) else getattr(req, "id", None)
            break
    if not responsive:
        return steps
    widths = []
    for step in steps:
        if str(step.get("action", "")).lower() == "set_viewport":
            args = step.get("args") or step
            try:
                widths.append(int(args.get("width")))
            except (TypeError, ValueError):
                pass
    if not any(w >= 1024 for w in widths):
        steps.extend([
            {"action": "set_viewport", "args": {"width": 1440, "height": 900}},
            {"action": "assert_no_overflow", "args": {}, "requirement_id": responsive_id},
            {"action": "screenshot", "args": {"name": "desktop-layout"}},
        ])
    if not any(w <= 480 for w in widths):
        steps.extend([
            {"action": "set_viewport", "args": {"width": 390, "height": 844}},
            {"action": "assert_no_overflow", "args": {}, "requirement_id": responsive_id},
            {"action": "screenshot", "args": {"name": "mobile-layout"}},
        ])
    return steps


_LOCAL_PREVIEW_ORIGIN = re.compile(r"https?://(?:127\.0\.0\.1|localhost):\d+", re.I)


def _runtime_fingerprint(value: str) -> str:
    normalized = _LOCAL_PREVIEW_ORIGIN.sub("http://<preview>", value or "")
    # Existing apps often append cache-busting timestamps/nonces to the same
    # endpoint. Compare the stable local-preview path so a new nonce is not
    # misclassified as a new regression, while a different endpoint remains
    # blocking.
    normalized = re.sub(r"(http://<preview>/[^?\s)]+)\?[^\s)]+", r"\1?<query>", normalized)
    return normalized


def _subtract_baseline_errors(current: list[str], baseline: list[str]) -> tuple[list[str], list[str]]:
    """Remove only matching pre-existing runtime errors using multiset fingerprints."""
    remaining_baseline = Counter(_runtime_fingerprint(x) for x in baseline)
    kept: list[str] = []
    ignored: list[str] = []
    for item in current:
        fp = _runtime_fingerprint(item)
        if remaining_baseline.get(fp, 0) > 0:
            remaining_baseline[fp] -= 1
            ignored.append(item)
        else:
            kept.append(item)
    return kept, ignored


def _apply_runtime_baseline(result: VerificationResult, baseline: Optional[VerificationResult]) -> VerificationResult:
    if not baseline:
        return result

    result.network_errors, ignored_network = _subtract_baseline_errors(
        list(result.network_errors), list(baseline.network_errors)
    )
    result.console_errors, ignored_console = _subtract_baseline_errors(
        list(result.console_errors), list(baseline.console_errors)
    )
    result.page_errors, ignored_page = _subtract_baseline_errors(
        list(result.page_errors), list(baseline.page_errors)
    )

    details = dict(result.details or {})
    details["baseline_ignored_runtime_errors"] = {
        "network": ignored_network,
        "console": ignored_console,
        "page": ignored_page,
    }
    result.details = details

    scenario_failed = any(not step.ok for step in result.steps)
    http_failed = result.http_status is None or result.http_status >= 400
    media_failed = bool(result.media_broken)
    result.passed = not (
        scenario_failed
        or bool(result.network_errors)
        or bool(result.console_errors)
        or bool(result.page_errors)
        or http_failed
        or media_failed
        or bool(result.error)
    )
    if result.semantic_required:
        result.semantic_passed = result.passed
    return result


@traced("SEMANTIC VERIFICATION")
async def verify_url(
    url: str,
    artifacts: Path,
    timeout_ms: int = 20000,
    click_selectors: Optional[List[str]] = None,
    fill_form: bool = True,
    check_media: bool = True,
    scenario: Optional[List[Dict[str, Any]]] = None,
    project_dir: Optional[Path] = None,
    plan: Optional[Plan] = None,
    app_requirements: str = "",
    restrict_public_network: bool = False,
    runtime_baseline: Optional[VerificationResult] = None,
) -> VerificationResult:
    """Unified entry point for browser verification."""
    # If no scenario explicitly passed but project_dir is known, plan the application-specific scenario
    if scenario is None and project_dir is not None:
        try:
            scenario = plan_verification_scenario(
                project_dir=project_dir,
                plan=plan,
                app_requirements=app_requirements,
            )
        except Exception:
            scenario = None

    semantic_required = semantic_verification_applies(app_requirements)
    requirements = list(getattr(plan, "requirements", []) or []) if plan else []
    scenario = _ensure_responsive_contract(scenario, app_requirements, requirements)
    contract_required = contract_verification_applies(app_requirements, requirements)
    # Caller-owned exact browser contracts are themselves the acceptance proof.
    # Keep every semantic/persistence/responsive check active, but do not require
    # planner-generated requirement IDs to be embedded into caller-owned steps.
    coverage_requirements = [] if (plan and plan.acceptance_contract_authoritative) else requirements
    contract_ok, contract_errors = validate_contract(
        scenario or [], app_requirements, coverage_requirements
    )
    if contract_required and not contract_ok:
        return VerificationResult(
            passed=False, semantic_required=True, semantic_passed=False,
            error="; ".join(contract_errors),
            details={"contract_errors": contract_errors, "scenario_steps": []},
        )

    # A browser operation can occasionally wedge below Playwright's per-action
    # timeout (browser process/transport shutdown, route callback, screenshot).
    # Bound the *entire* verification so an autonomous job can diagnose/retry
    # instead of remaining forever at VERIFY START.
    watchdog_s = float(os.environ.get("GB_VERIFY_WATCHDOG_S", "90"))
    if not 5 <= watchdog_s <= 600:
        watchdog_s = 90.0
    mark("VERIFY WATCHDOG", timeout_s=watchdog_s)
    try:
        async with asyncio.timeout(watchdog_s):
            result = await _verify_playwright(
                url,
                artifacts,
                timeout_ms=timeout_ms,
                click_selectors=click_selectors or [],
                fill_form=fill_form,
                check_media=check_media,
                scenario=scenario,
                restrict_public_network=restrict_public_network,
            )
        result.semantic_required = semantic_required
        result.semantic_passed = result.passed if semantic_required else None
        result = _apply_runtime_baseline(result, runtime_baseline)
        mark("SEMANTIC VERIFICATION RESULT", passed=result.passed,
             semantic_passed=result.semantic_passed, steps=len(result.steps))
        return result
    except Exception as e:  # noqa: BLE001
        fallback = await _verify_http_fallback(url, str(e))
        fallback.semantic_required = semantic_required
        fallback.semantic_passed = False if semantic_required else None
        return fallback


async def _verify_playwright(
    url: str,
    artifacts: Path,
    timeout_ms: int,
    click_selectors: List[str],
    fill_form: bool,
    check_media: bool,
    scenario: Optional[List[Dict[str, Any]]] = None,
    restrict_public_network: bool = False,
) -> VerificationResult:
    from playwright.async_api import async_playwright

    console_errors: list[str] = []
    page_errors: list[str] = []
    network_errors: list[str] = []
    http_status: Optional[int] = None
    step_results: list[dict] = []
    nonblocking_network_errors: list[str] = []
    favicon_404s: list[str] = []
    browser_details: dict[str, Any] = {"browser_executed": False}
    declared_icon = await _document_declares_icon(url)

    artifacts.mkdir(parents=True, exist_ok=True)
    shot_path = artifacts / "verification.png"

    async with async_playwright() as p:
        mark("CHROMIUM START")
        executable_path, searched_paths = _resolve_chromium_executable(
            getattr(p.chromium, "executable_path", None)
        )
        browser_details.update({
            "executable_path": executable_path,
            "searched_paths": searched_paths,
        })
        browser = await p.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        browser_details["browser_executed"] = True
        mark("CHROMIUM READY", executable_path=executable_path)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        if restrict_public_network:
            host_cache: dict[str, bool] = {}

            async def _guard_public_requests(route):
                request_url = route.request.url
                parsed = urlparse(request_url)
                if (not declared_icon and parsed.path == "/favicon.ico"):
                    await route.fulfill(status=204, body="")
                    return
                cache_key = f"{parsed.scheme}://{parsed.hostname or ''}:{parsed.port or ''}"
                allowed = host_cache.get(cache_key)
                if allowed is None:
                    allowed = await _public_http_target(request_url)
                    host_cache[cache_key] = allowed
                if not allowed:
                    network_errors.append(f"blocked private/non-public request: {request_url}")
                    await route.abort("blockedbyclient")
                    return
                await route.continue_()

            await context.route("**/*", _guard_public_requests)
        elif not declared_icon:
            async def _fulfill_implicit_favicon(route):
                await route.fulfill(status=204, body="")
            await context.route("**/favicon.ico", _fulfill_implicit_favicon)
        page = await context.new_page()

        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        def handle_response(resp):
            nonlocal http_status
            if resp.url == url or resp.url == url.rstrip("/") or resp.url.startswith(url):
                if http_status is None:
                    http_status = resp.status
            if resp.status >= 400:
                parsed = urlparse(resp.url)
                if resp.status == 404 and parsed.path == "/favicon.ico":
                    # Chromium requests /favicon.ico implicitly even when the
                    # application declares no icon. Defer classification until
                    # after navigation so explicitly declared icons still block.
                    favicon_404s.append(f"{resp.status} {resp.url}")
                else:
                    network_errors.append(f"{resp.status} {resp.url}")

        page.on("response", handle_response)
        page.on("requestfailed", lambda request: network_errors.append(
            f"request failed: {request.url} ({request.failure})"))

        # 1. Navigation
        resp = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        if resp and http_status is None:
            http_status = resp.status

        # 2. Structured scenario execution if supplied
        if scenario:
            for idx, step in enumerate(scenario):
                action = step.get("action", "")
                args = step.get("args") or {}
                selector = step.get("selector") or args.get("selector")
                value = step.get("value") or args.get("value")
                ms = step.get("ms") or args.get("ms") or 500
                name = step.get("name") or args.get("name") or f"step_{idx}"

                try:
                    if action == "open":
                        target = _resolve_navigation_target(url, str(value) if value is not None else url)
                        await page.goto(target, timeout=timeout_ms, wait_until="domcontentloaded")
                    elif action == "navigate":
                        raw_target = value if value is not None else args.get("url")
                        target = _resolve_navigation_target(url, str(raw_target) if raw_target is not None else url)
                        await page.goto(target, timeout=timeout_ms, wait_until="domcontentloaded")
                    elif action == "reload":
                        await page.reload(timeout=timeout_ms, wait_until="domcontentloaded")
                    elif action == "click" and selector:
                        await page.wait_for_selector(selector, timeout=5000)
                        await page.click(selector)
                        await page.wait_for_timeout(300)
                    elif action == "fill" and selector:
                        await page.wait_for_selector(selector, timeout=5000)
                        await page.fill(selector, str(value if value is not None else "Test input"))
                    elif action == "select" and selector:
                        await page.wait_for_selector(selector, timeout=5000)
                        await page.select_option(selector, value=str(value or ""))
                    elif action == "check" and selector:
                        await page.locator(selector).first.check(timeout=timeout_ms)
                    elif action == "submit" and selector:
                        loc = page.locator(selector)
                        if await loc.count() > 0:
                            await loc.first.press("Enter")
                        else:
                            await page.keyboard.press("Enter")
                        await page.wait_for_timeout(500)
                    elif action == "wait":
                        await page.wait_for_timeout(int(ms))
                    elif action == "set_viewport":
                        width = int(args.get("width", 1280))
                        height = int(args.get("height", 800))
                        if width < 240 or height < 320 or width > 3840 or height > 2160:
                            raise ValueError(f"invalid viewport {width}x{height}")
                        await page.set_viewport_size({"width": width, "height": height})
                        await page.wait_for_timeout(150)
                    elif action == "assert_no_overflow":
                        overflow = await page.evaluate("""() => {
                            const vw = document.documentElement.clientWidth;
                            const offenders = [];
                            const interactiveOffenders = [];
                            const nodes = Array.from(document.querySelectorAll('body *'));
                            for (const el of nodes) {
                                const style = getComputedStyle(el);
                                if (style.position === 'fixed' && style.display === 'none') continue;
                                if (style.visibility === 'hidden' || style.display === 'none') continue;
                                const r = el.getBoundingClientRect();
                                if (r.width > 0 && (r.right > vw + 2 || r.left < -2)) {
                                    const item = {tag: el.tagName, id: el.id || '', cls: String(el.className || '').slice(0,80), left: r.left, right: r.right, vw};
                                    offenders.push(item);
                                    if (el.matches('a,button,input,select,textarea,[role="button"],[tabindex]:not([tabindex="-1"])')) {
                                        interactiveOffenders.push(item);
                                    }
                                    if (offenders.length >= 20) break;
                                }
                            }
                            const rootOverflow = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0) > vw + 2;
                            return {rootOverflow, offenders, interactiveOffenders};
                        }""")
                        # Only document-level horizontal scrolling is a layout failure.
                        # Wide decorative children (hero cover images, marquees/tickers)
                        # are legitimate when their container clips them and the page
                        # itself does not become horizontally scrollable.
                        if overflow.get("rootOverflow"):
                            raise AssertionError(f"horizontal overflow detected: {overflow}")
                        if overflow.get("interactiveOffenders"):
                            raise AssertionError(f"interactive control clipped outside viewport: {overflow}")
                    elif action == "assert_in_viewport" and selector:
                        visible = await page.locator(selector).first.evaluate("""el => {
                            const r = el.getBoundingClientRect();
                            const vw = document.documentElement.clientWidth;
                            const vh = document.documentElement.clientHeight;
                            return r.width > 0 && r.height > 0 && r.left >= 0 && r.top >= 0 && r.right <= vw && r.bottom <= vh;
                        }""")
                        if not visible:
                            raise AssertionError(f"element is outside viewport: {selector}")
                    elif action in ("assert_text", "assert_not_text"):
                        expected = args.get("contains", value)
                        loc = page.locator(selector or "body").first
                        if action == "assert_not_text":
                            # Snapshot the first match atomically: absence is a valid
                            # negative outcome, not a reason to wait for attachment.
                            # Selector/browser errors propagate to the failed step.
                            content = await loc.evaluate_all(
                                "(elements) => elements.length ? elements[0].innerText : null"
                            )
                        else:
                            content = await loc.inner_text(timeout=timeout_ms)
                        found = content is not None and str(expected) in content
                        if (action == "assert_text" and not found) or (action == "assert_not_text" and found):
                            observed = content[:200] if isinstance(content, str) else content
                            raise AssertionError(f"expected {action} {expected!r}; observed {observed!r}")
                    elif action in ("assert_visible", "assert_element") and selector:
                        await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
                    elif action == "assert_hidden" and selector:
                        await page.locator(selector).first.wait_for(state="hidden", timeout=timeout_ms)
                    elif action == "assert_url":
                        expected = args.get("equals", args.get("contains", value))
                        if "equals" in args and page.url != str(expected):
                            raise AssertionError(f"expected URL {expected!r}; observed {page.url!r}")
                        if "equals" not in args and str(expected) not in page.url:
                            raise AssertionError(f"expected URL containing {expected!r}; observed {page.url!r}")
                    elif action == "assert_count" and selector:
                        observed = await page.locator(selector).count()
                        expected = args.get("equals")
                        minimum = args.get("at_least")
                        if expected is not None and observed != int(expected):
                            raise AssertionError(f"expected count {expected}; observed {observed}")
                        if minimum is not None and observed < int(minimum):
                            raise AssertionError(f"expected count >= {minimum}; observed {observed}")
                    elif action == "screenshot":
                        step_shot = artifacts / f"{name}.png"
                        await page.screenshot(path=str(step_shot), full_page=True)
                    else:
                        raise ValueError(f"unsupported or incomplete verification action: {action}")
                    
                    step_results.append({"step": idx, "action": action, "selector": selector, "passed": True, "requirement_id": step.get("requirement_id")})
                except Exception as step_exc:
                    failure_shot = artifacts / f"failed-step-{idx}-{action}.png"
                    try:
                        await page.screenshot(path=str(failure_shot), full_page=True)
                    except Exception:
                        failure_shot = None
                    step_results.append({"step": idx, "action": action, "selector": selector, "passed": False, "error": str(step_exc), "screenshot_path": str(failure_shot) if failure_shot else None, "requirement_id": step.get("requirement_id")})
                    break
        else:
            # Fallback interaction if no explicit scenario
            for sel in click_selectors:
                try:
                    await page.wait_for_selector(sel, timeout=3000)
                    await page.click(sel)
                    await page.wait_for_timeout(300)
                except Exception:
                    pass

            if fill_form:
                try:
                    inputs = await page.query_selector_all("input:not([type=hidden]):not([type=submit]), textarea")
                    for inp in inputs[:4]:
                        try:
                            await inp.fill("Test User")
                        except Exception:
                            pass
                except Exception:
                    pass

        # Headless Chromium may never request declared favicons automatically.
        # Load each declared icon inside the real page so missing assets remain
        # blocking independently of browser chrome behaviour.
        broken_icons = await page.evaluate("""async () => {
            const icons = Array.from(document.querySelectorAll('link[rel~="icon"]'));
            return (await Promise.all(icons.map(link => new Promise(resolve => {
                const image = new Image();
                const timer = setTimeout(() => resolve(link.href), 5000);
                image.onload = () => { clearTimeout(timer); resolve(null); };
                image.onerror = () => { clearTimeout(timer); resolve(link.href); };
                image.src = link.href;
            })))).filter(Boolean);
        }""")
        network_errors.extend(f"declared icon failed: {icon}" for icon in broken_icons)

        # 3. Media assets check
        media_broken = 0
        media_loaded = 0
        if check_media:
            try:
                media_eval = await page.evaluate("""() => {
                    const imgs = Array.from(document.querySelectorAll('img'));
                    let broken = 0;
                    let loaded = 0;
                    for (const img of imgs) {
                        if (!img.complete || img.naturalWidth === 0) {
                            broken++;
                        } else {
                            loaded++;
                        }
                    }
                    return { broken, loaded };
                }""")
                media_broken = media_eval.get("broken", 0)
                media_loaded = media_eval.get("loaded", 0)
            except Exception:
                pass

        # 4. Final verification screenshot
        await page.screenshot(path=str(shot_path), full_page=True)
        rendered_text = (await page.inner_text("body"))[:2000] if await page.query_selector("body") else ""

        # Chromium may request /favicon.ico after DOMContentLoaded. Classify it
        # here, after the scenario, so timing cannot turn an implicit browser
        # request into a false application failure.
        if favicon_404s:
            if declared_icon:
                network_errors.extend(favicon_404s)
            else:
                nonblocking_network_errors.extend(favicon_404s)
                generic_resource_error = (
                    "[error] Failed to load resource: the server responded "
                    "with a status of 404 (File not found)"
                )
                for _ in favicon_404s:
                    try:
                        console_errors.remove(generic_resource_error)
                    except ValueError:
                        break

        await browser.close()

    scenario_failed = any(not s.get("passed", True) for s in step_results)
    network_failed = len(network_errors) > 0
    media_failed = media_broken > 0
    console_failed = len(console_errors) > 0
    page_failed = len(page_errors) > 0
    http_failed = (http_status is None or http_status >= 400)

    passed = not (
        scenario_failed
        or network_failed
        or media_failed
        or console_failed
        or page_failed
        or http_failed
    )

    return VerificationResult(
        passed=passed,
        http_status=http_status,
        console_errors=console_errors,
        page_errors=page_errors,
        network_errors=network_errors,
        screenshot_path=str(shot_path),
        rendered_text=rendered_text,
        media_loaded=([f"{media_loaded} media asset(s) loaded"] if media_loaded else []),
        media_broken=([f"{media_broken} media asset(s) failed to load"] if media_broken else []),
        steps=[VerificationStepResult(index=s["step"] + 1, action=s["action"], ok=s["passed"], error=s.get("error"), screenshot_path=s.get("screenshot_path"), args={**((scenario[s["step"]].get("args") or {}) if scenario else {}), **({"requirement_id": s.get("requirement_id")} if s.get("requirement_id") else {})}) for s in step_results],
        details={
            "scenario_steps": step_results,
            "browser": browser_details,
            "browser_executed": bool(browser_details.get("browser_executed")),
            "final_url": url,
            "nonblocking_network_errors": nonblocking_network_errors,
        },
    )


async def _verify_http_fallback(url: str, error: str) -> VerificationResult:
    """Fail closed when browser verification is unavailable.

    A server-side HTTP response cannot establish browser or semantic behavior,
    and fetching a caller-provided URL from the backend would create an SSRF
    path. Keep the failure details without making a second network request.
    """
    return VerificationResult(
        passed=False,
        http_status=None,
        console_errors=[f"Browser verification fallback: {error}"],
        page_errors=[],
        network_errors=[],
        screenshot_path=None,
        rendered_text="HTTP fallback skipped; browser verification is unavailable.",
        error=f"Browser verification unavailable: {error}",
        media_loaded=[],
        media_broken=[],
        details={
            "browser": {"browser_executed": False, "launch_error": error},
            "browser_executed": False,
            "final_url": url,
        },
    )
