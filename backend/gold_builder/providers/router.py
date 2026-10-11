"""Provider registry with immediate 429 fallback and bounded transient retries."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from typing import List, Optional

from .anthropic_direct import AnthropicDirect
from .base import (
    CompletionRequest,
    CompletionResponse,
    ImageProvider,
    ImageRequest,
    ImageResponse,
    LLMProvider,
    ProviderError,
    ProviderTimeoutError,
    retry_delay,
    TransientProviderError,
    VideoProvider,
    VideoRequest,
    VideoResponse,
    classify_transient,
    provider_exception,
    provider_failure_guidance,
    provider_identity,
)
from .emergent_llm import EmergentLLM
from .groq_direct import GroqDirect
from .gemini_direct import GeminiDirect
from .gemini_media import Gemini25FlashImageProvider, GeminiFlashLiteImageProvider, GeminiImageProvider
from .nano_banana import NanoBananaImage
from .fal_media import FalImageProvider, FalVideoProvider
from .veo_media import VeoVideoProvider
from .self_hosted_media import SelfHostedImageProvider, SelfHostedVideoProvider
from .openai_media import OpenAIImageProvider
from .pollinations_media import PollinationsImage, PollinationsVideoProvider
from .openai_direct import OpenAIDirect
from .openai_compatible import configured_compatible_providers
from .openhands_llm import configured_openhands_provider

from ..progress import mark

log = logging.getLogger(__name__)


def _env_seconds(name: str, default: float, ceiling: float) -> float:
    """Read a positive, finite, capped timeout from the environment."""
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return min(value, ceiling)



class ProviderRouter:
    def __init__(self):
        # Prefer true provider diversity before spending a second attempt in
        # the same vendor ecosystem. A Gemini quota failure should therefore
        # reach OpenAI/Groq/OpenRouter/Hugging Face before another Gemini model.
        # Unconfigured providers are skipped by available(), so this ordering is
        # safe for partial BYOK deployments.
        compatible = configured_compatible_providers()
        nvidia = [p for p in compatible if p.provider == "nvidia"]
        openrouter = [p for p in compatible if p.provider == "openrouter"]
        cloudflare = [p for p in compatible if p.provider == "cloudflare"]
        sambanova = [p for p in compatible if p.provider == "sambanova"]
        huggingface = [p for p in compatible if p.provider == "huggingface"]
        other_compatible = [p for p in compatible if p.provider not in {"nvidia", "cloudflare", "sambanova", "openrouter", "huggingface"}]
        self._llm: List[LLMProvider] = [
            GeminiDirect(model=os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.8-flash"),
            OpenAIDirect(model=os.environ.get("OPENAI_MODEL", "").strip() or "gpt-4o"),
            GroqDirect(model=os.environ.get("GROQ_MODEL", "").strip() or "openai/gpt-oss-120b"),
            *nvidia,
            *cloudflare,
            *sambanova,
            *openrouter,
            *huggingface,
            GeminiDirect(model=os.environ.get("GEMINI_FALLBACK_MODEL", "").strip() or "gemini-3.5-flash-lite"),
            AnthropicDirect(model="claude-3-5-sonnet-latest"),
            EmergentLLM(provider="anthropic", model="claude-sonnet-4-6"),
            EmergentLLM(provider="openai", model="gpt-5.4"),
            EmergentLLM(provider="gemini", model="gemini-3-flash-preview"),
            *other_compatible,
        ]
        # OpenHands is registered last: a full delegated conversation is slower
        # and costlier than a single completion, so it is the deliberate
        # escalation after the direct vendors, never the default. It is also
        # opted in only when OPENHANDS_API_KEY is set.
        openhands = configured_openhands_provider()
        if openhands is not None:
            self._llm.append(openhands)
        self._image: List[ImageProvider] = [
            OpenAIImageProvider(),
            GeminiImageProvider(),
            GeminiFlashLiteImageProvider(),
            FalImageProvider(),
            Gemini25FlashImageProvider(),
            NanoBananaImage(),
            SelfHostedImageProvider(),
            PollinationsImage(),
        ]
        self._video: List[VideoProvider] = [
            VeoVideoProvider(),
            FalVideoProvider(family="wan"),
            FalVideoProvider(family="kling"),
            SelfHostedVideoProvider(),
            PollinationsVideoProvider(),

        ]
        self.media_attempt_timeout_s = 90.0
        self.media_total_timeout_s = 180.0
        # Retry policy for TransientProviderError on the *same* provider
        self.same_provider_retries = 1
        self.backoff_base = 1.4
        # One deadline includes every attempt, retry wait, and fallback.
        # Bounded and operator-tunable: slower proxied models (Claude/GPT via
        # Emergent) need longer than 30s for a full plan/file completion.
        self.attempt_timeout_s = _env_seconds("GB_PROVIDER_ATTEMPT_TIMEOUT_S", 30.0, 600.0)
        self.total_timeout_s = _env_seconds("GB_PROVIDER_TOTAL_TIMEOUT_S", 120.0, 1800.0)
        self.max_retry_wait_s = 20.0
        # If every otherwise-eligible LLM is temporarily cooling down, wait for
        # the earliest one instead of failing the whole autonomous job.
        self.cooldown_wait_enabled = True
        self.max_cooldown_wait_s = 3600.0
        # Cross-request cooldown prevents repeatedly hammering a provider that
        # has already returned HTTP 429. The router falls back immediately and
        # temporarily skips that provider on subsequent calls.
        self.rate_limit_cooldown_s = 60.0
        self._cooldown_until: dict[str, float] = {}
        self._cooldown_reason: dict[str, str] = {}
        self._last_failure: dict[str, dict] = {}
        self._consecutive_failures: dict[str, int] = {}
        # Last provider/model that actually served each job. Used to prove that
        # an independent reviewer is a genuinely different authority from the
        # implementation. Kept in-memory; persisted review evidence is the
        # authoritative record.
        self._last_success_by_job: dict[str, dict] = {}

    # ---- registration ----
    def register_llm(self, provider: LLMProvider, priority: int = 100) -> None:
        # Insert respecting priority: lower number = higher priority (front)
        self._llm.insert(0 if priority < 100 else len(self._llm), provider)

    def register_image(self, provider: ImageProvider) -> None:
        self._image.append(provider)

    def register_video(self, provider: VideoProvider) -> None:
        self._video.append(provider)

    # ---- listing ----
    def list_llm(self) -> List[LLMProvider]:
        return list(self._llm)

    def list_image(self) -> List[ImageProvider]:
        return list(self._image)

    def list_video(self) -> List[VideoProvider]:
        return list(self._video)


    # --- Role-Based Provider Routing ---
    def set_role_provider(self, role: str, provider_id: str) -> None:
        self._role_map = getattr(self, "_role_map", {})
        self._role_map[role.lower()] = provider_id

    def get_provider_for_role(self, role: str) -> Optional[LLMProvider]:
        self._role_map = getattr(self, "_role_map", {})
        preferred = self._role_map.get(role.lower())
        if preferred:
            for p in self._llm:
                if p.id == preferred and p.available():
                    return p
        # Fallback to default available provider
        for p in self._llm:
            if p.available():
                return p
        return None

    def _cooldown_remaining(self, provider_id: str) -> float:
        until = self._cooldown_until.get(provider_id, 0.0)
        remaining = max(0.0, until - time.monotonic())
        if remaining <= 0:
            self._cooldown_until.pop(provider_id, None)
            self._cooldown_reason.pop(provider_id, None)
        return remaining

    def _mark_rate_limited(self, provider_id: str, retry_after: Optional[float] = None, *, reason: str = "rate_limit") -> None:
        cooldown = retry_after if retry_after and retry_after > 0 else self.rate_limit_cooldown_s
        cooldown = min(max(float(cooldown), 1.0), 3600.0)
        new_until = time.monotonic() + cooldown
        current_until = self._cooldown_until.get(provider_id, 0.0)
        current_reason = self._cooldown_reason.get(provider_id)
        # Never downgrade an explicit 429 Retry-After window because another
        # concurrent request later reports an auth/billing/permission block.
        if current_reason == "rate_limit" and reason != "rate_limit" and current_until > time.monotonic():
            return
        self._cooldown_until[provider_id] = max(current_until, new_until) if reason == current_reason else new_until
        self._cooldown_reason[provider_id] = reason
        mark("PROVIDER COOLDOWN", provider=provider_id, cooldown_s=round(cooldown, 3))

    def _record_success(self, provider_id: str) -> None:
        # A confirmed success clears a stale auth/billing block, but must not
        # override an explicit concurrent 429 Retry-After cooldown.
        if self._cooldown_reason.get(provider_id) == "external_block":
            self._cooldown_until.pop(provider_id, None)
            self._cooldown_reason.pop(provider_id, None)
        self._last_failure.pop(provider_id, None)
        self._consecutive_failures.pop(provider_id, None)

    def _record_failure(self, provider_id: str, reason: str, status_code=None, *, transient=False) -> None:
        count = self._consecutive_failures.get(provider_id, 0) + 1
        self._consecutive_failures[provider_id] = count
        self._last_failure[provider_id] = {
            "reason": reason, "status_code": status_code, "at": time.time(),
        }
        if status_code == 429:
            return
        # Authentication/billing/permission failures are not transient. Keep a
        # bounded cooldown so repeated jobs do not hammer a provider that
        # cannot succeed until its external account state changes.
        if status_code in (401, 402, 403, 410):
            self._mark_rate_limited(provider_id, self.rate_limit_cooldown_s, reason="external_block")
            return
        if transient and count >= 3:
            self._mark_rate_limited(provider_id, self.rate_limit_cooldown_s)

    def provider_status(self, provider: LLMProvider) -> dict:
        try:
            configured = provider.available()
        except Exception:
            configured = False
        remaining = self._cooldown_remaining(provider.id)
        failure = self._last_failure.get(provider.id, {})
        status = "UNAVAILABLE"
        if configured:
            status = "COOLDOWN" if remaining > 0 else ("DEGRADED" if failure else "AVAILABLE")
        code = failure.get("status_code")
        if code in (401, 402, 403, 410):
            status = "EXTERNAL_BLOCKED"
        elif code == 429:
            status = "COOLDOWN" if remaining > 0 else "DEGRADED"
        return {
            "status": status,
            "cooldown_remaining_s": round(remaining, 3),
            "last_failure": failure.get("reason"),
            "consecutive_failures": self._consecutive_failures.get(provider.id, 0),
            "capabilities": sorted(getattr(provider, "capabilities", [])),
        }

    def available_llm(self) -> List[LLMProvider]:
        return [p for p in self._llm if p.available() and self._cooldown_remaining(p.id) <= 0]

    def llm_providers(self) -> List[LLMProvider]:
        """All registered LLM providers, including unavailable/cooling ones.

        Used by the review layer to distinguish a permanent authority gap (no
        provider of the required kind is configured) from a transient external
        boundary (the required provider exists but is blocked/rate-limited).
        """
        return list(self._llm)

    def llm_externally_exhausted(self) -> bool:
        """True when no provider is usable AND at least one is blocked/cooling.

        Distinguishes a genuine external availability boundary (auth/quota/
        rate-limit on the configured fleet) from a misconfigured engine with no
        usable provider at all. A router with zero registered providers returns
        False so a missing provider stays an engine-level failure.
        """
        if not self._llm:
            return False
        if any(p.available() and self._cooldown_remaining(p.id) <= 0 for p in self._llm):
            return False
        return any(
            (not p.available()) or self._cooldown_remaining(p.id) > 0
            for p in self._llm
        )

    def independent_review_externally_exhausted(self, implementation: Optional[dict]) -> bool:
        """True when independent reviewers exist but none is currently usable.

        This is the review-layer boundary: the implementer may be healthy, but
        every provider that would be an independent reviewer is externally
        blocked or cooling down (auth/quota/rate limit). Distinct from having no
        independent provider at all, which is a genuine review gap.
        """
        independent = [
            p for p in self._llm if self.is_independent(p, implementation or {})
        ]
        if not independent:
            return False
        if any(p.available() and self._cooldown_remaining(p.id) <= 0 for p in independent):
            return False
        return any(
            (not p.available()) or self._cooldown_remaining(p.id) > 0
            for p in independent
        )

    def available_image(self) -> List[ImageProvider]:
        return [
            p for p in self._image
            if p.available() and self._cooldown_remaining(p.id) <= 0
        ]

    def available_video(self) -> List[VideoProvider]:
        return [
            p for p in self._video
            if p.available() and self._cooldown_remaining(p.id) <= 0
        ]

    # ---- LLM ----
    async def complete(
        self,
        req: CompletionRequest,
        preferred_id: Optional[str] = None,
        job_id: Optional[str] = None,
        event_callback=None,
    ) -> CompletionResponse:
        # Budget check before spending any tokens
        if job_id:
            try:
                from ..engine.usage import tracker, BudgetExceededError
                tracker.check_budget(job_id)
            except BudgetExceededError as e:
                raise ProviderError(str(e)) from e

        for value in (self.attempt_timeout_s, self.total_timeout_s, self.max_retry_wait_s):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("provider time budgets must be finite and positive")
        if not isinstance(self.same_provider_retries, int) or not 0 <= self.same_provider_retries <= 10:
            raise ValueError("same_provider_retries must be an integer between 0 and 10")
        if not math.isfinite(self.backoff_base) or self.backoff_base <= 0:
            raise ValueError("backoff_base must be finite and positive")
        # A provider that runs a whole conversation (OpenHands) declares a floor;
        # honour it for the attempt and total budgets so it is not cancelled
        # mid-conversation by the default per-completion budget.
        attempt_budget = max(self.attempt_timeout_s, self._provider_floor(preferred_id, "min_attempt_timeout_s"))
        total_budget = max(self.total_timeout_s, self._provider_floor(preferred_id, "min_total_timeout_s"))
        started = time.monotonic()
        try:
            async with asyncio.timeout(total_budget):
                return await self._complete_bounded(req, preferred_id, job_id, started + total_budget, event_callback, attempt_budget)
        except TimeoutError:
            mark("PROVIDER DEADLINE", elapsed_s=round(time.monotonic() - started, 3),
                 budget_s=total_budget)
            raise ProviderTimeoutError(
                f"Provider request deadline exceeded ({total_budget}s across retries and fallback)"
            ) from None

    def _provider_floor(self, provider_id: Optional[str], attribute: str) -> float:
        if not provider_id:
            return 0.0
        for provider in self._llm:
            if provider.id == provider_id:
                try:
                    return float(getattr(provider, attribute, 0.0) or 0.0)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    async def _emit(self, callback, event: str, **metadata):
        mark(event, **metadata)
        if callback:
            result = callback(event, metadata)
            if asyncio.iscoroutine(result):
                await result

    async def _complete_bounded(self, req, preferred_id, job_id, deadline, event_callback=None, attempt_cap=None):
        if attempt_cap is None:
            attempt_cap = self.attempt_timeout_s
        errors: List[str] = []
        candidates = []
        cooling: list[tuple[float, LLMProvider]] = []
        required = getattr(req, "required_capabilities", []) or []
        for p in self._ordered_candidates(preferred_id):
            try:
                available = p.available()
            except Exception:
                available = False
            supports = getattr(p, "supports", lambda _required: True)
            if not available or not supports(required):
                continue
            remaining = self._cooldown_remaining(p.id)
            if remaining > 0:
                cooling.append((remaining, p))
                await self._emit(event_callback, "PROVIDER COOLDOWN SKIP", provider=p.id, remaining_s=round(remaining, 3))
                continue
            candidates.append(p)

        # A temporary quota window is not a terminal build failure. When every
        # configured/capable provider is cooling down, wait for the earliest
        # provider and retry routing within the existing request deadline.
        if not candidates and cooling and self.cooldown_wait_enabled:
            wait_s, provider = min(cooling, key=lambda item: item[0])
            deadline_remaining = max(0.0, deadline - time.monotonic())
            bounded_wait = min(wait_s, self.max_cooldown_wait_s, deadline_remaining)
            if bounded_wait > 0 and bounded_wait + 0.01 < deadline_remaining:
                await self._emit(
                    event_callback,
                    "PROVIDER COOLDOWN WAIT",
                    provider=provider.id,
                    wait_s=round(bounded_wait, 3),
                    next_action="retry_routing",
                )
                await asyncio.sleep(bounded_wait)
                return await self._complete_bounded(req, preferred_id, job_id, deadline, event_callback, attempt_cap)
        for index, p in enumerate(candidates):
            remaining_candidates = len(candidates) - index
            # Reserve a share of the remaining deadline for every fallback.
            # A stalled first provider cannot spend the entire routed budget.
            provider_deadline = time.monotonic() + max(0, deadline - time.monotonic()) / remaining_candidates
            last_exc = None
            for attempt in range(self.same_provider_retries + 1):
                started = time.monotonic()
                if remaining_candidates > 1 and started >= provider_deadline:
                    break
                attempt_budget = min(attempt_cap, max(0, provider_deadline - started))
                await self._emit(event_callback, "PROVIDER REQUEST START", provider=p.id, attempt=attempt + 1,
                     timeout_s=round(attempt_budget, 2), job_id=job_id)
                try:
                    async with asyncio.timeout(attempt_budget):
                        resp = await p.complete(req)
                        if not isinstance(resp, CompletionResponse) or not isinstance(resp.text, str) or not resp.text.strip():
                            raise ProviderError("Malformed or empty provider response")
                        if resp.finish_reason in {"length", "max_tokens", "MAX_TOKENS"}:
                            raise ProviderError("Provider response was truncated at the output limit")
                        if req.json_mode:
                            payload = resp.text.strip()
                            if payload.startswith("```") and payload.endswith("```"):
                                payload = payload.split("\n", 1)[-1][:-3].strip()
                            try:
                                data = json.loads(payload)
                            except (ValueError, TypeError):
                                raise ProviderError("Malformed JSON provider response") from None
                            if not isinstance(data, dict):
                                raise ProviderError("Expected a JSON object provider response")
                except TimeoutError:
                    last_exc = ProviderTimeoutError("provider attempt timed out")
                    await self._emit(event_callback, "PROVIDER REQUEST TIMEOUT", provider=p.id, attempt=attempt + 1,
                         elapsed_s=round(time.monotonic() - started, 3))
                except ProviderError as exc:
                    last_exc = exc
                    rate_limited = (getattr(exc, "status_code", None) == 429
                                    or "429" in str(exc) or "rate limit" in str(exc).lower())
                    await self._emit(event_callback, "PROVIDER RATE LIMIT" if rate_limited else "PROVIDER REQUEST ERROR",
                         provider=p.id, attempt=attempt + 1,
                         error_type=type(exc).__name__,
                         status_code=getattr(exc, "status_code", None),
                         elapsed_s=round(time.monotonic() - started, 3))
                except Exception as exc:
                    last_exc = provider_exception(p.id, exc)
                    await self._emit(event_callback, "PROVIDER REQUEST ERROR", provider=p.id, attempt=attempt + 1,
                         status_code=last_exc.status_code)
                else:
                    await self._emit(event_callback, "PROVIDER RESPONSE", provider=p.id, attempt=attempt + 1,
                         elapsed_s=round(time.monotonic() - started, 3))
                    if job_id:
                        try:
                            from ..engine.usage import tracker
                            tracker.record(job_id, resp.usage, p.provider, p.model)
                        except Exception:  # noqa: BLE001
                            pass
                        self._record_job_success(job_id, p)
                    self._record_success(p.id)
                    return resp
                status = getattr(last_exc, "status_code", None)
                if status in (400, 401, 402, 403, 404, 410, 422):
                    break
                if not (isinstance(last_exc, TransientProviderError)
                        or (isinstance(status, int) and 500 <= status < 600)
                        or classify_transient(last_exc)):
                    break

                # A 429 is a quota/rate-limit signal. Do not hammer the same
                # model repeatedly; immediately fall through to the next
                # available candidate (for Gemini this means the lite model).
                rate_limited = (
                    getattr(last_exc, "status_code", None) == 429
                    or "429" in str(last_exc)
                    or "rate limit" in str(last_exc).lower()
                )
                if rate_limited:
                    self._mark_rate_limited(p.id, getattr(last_exc, "retry_after", None))
                    await self._emit(event_callback, "PROVIDER RATE LIMIT FALLBACK", provider=p.id,
                         next_action="try_next_provider")
                    break

                # Retry other transient failures (timeouts/5xx) with bounded backoff.
                if attempt == self.same_provider_retries:
                    break
                hint = retry_delay(last_exc)
                wait = max(self.backoff_base ** (attempt + 1), hint or 0)
                if (wait > self.max_retry_wait_s
                        or (remaining_candidates > 1 and time.monotonic() + wait >= provider_deadline)):
                    await self._emit(event_callback, "PROVIDER RETRY REFUSED", provider=p.id, requested_wait_s=wait,
                         max_wait_s=self.max_retry_wait_s)
                    break
                await self._emit(event_callback, "PROVIDER RETRY WAIT", provider=p.id, wait_s=wait, next_attempt=attempt + 2)
                await asyncio.sleep(wait)
            reason = type(last_exc).__name__
            status = getattr(last_exc, "status_code", None)
            transient = (
                isinstance(last_exc, TransientProviderError)
                or (isinstance(status, int) and 500 <= status < 600)
                or classify_transient(last_exc)
            )
            self._record_failure(p.id, reason, status, transient=transient)
            errors.append(f"{p.id}: {reason}" + (f" HTTP {status}" if isinstance(status, int) else ""))
            await self._emit(event_callback, "PROVIDER FALLBACK", provider=p.id, reason=reason)
        guidance = provider_failure_guidance(errors)
        raise ProviderError(
            ("All LLM providers failed. " + " | ".join(errors)
             if errors else "No LLM provider available")
            + (f" {guidance}" if guidance else "")
        )

    # ---- Media capability routing ----
    def media_capabilities(self) -> dict:
        image = {
            p.id: {
                "available": bool(p.available()) and self._cooldown_remaining(p.id) <= 0,
                "status": self.provider_status(p)["status"],
                "cooldown_remaining_s": self.provider_status(p)["cooldown_remaining_s"],
                "last_failure": self.provider_status(p)["last_failure"],
                "provider": getattr(p, "provider", ""),
                "model": getattr(p, "model", ""),
                "capabilities": sorted(getattr(p, "capabilities", [])),
            }
            for p in self._image
        }
        video = {
            p.id: {
                "available": bool(p.available()) and self._cooldown_remaining(p.id) <= 0,
                "status": self.provider_status(p)["status"],
                "cooldown_remaining_s": self.provider_status(p)["cooldown_remaining_s"],
                "last_failure": self.provider_status(p)["last_failure"],
                "provider": getattr(p, "provider", ""),
                "model": getattr(p, "model", ""),
                "capabilities": sorted(getattr(p, "capabilities", [])),
            }
            for p in self._video
        }
        return {"image": image, "video": video}

    async def generate_image(self, req: ImageRequest, preferred_id: Optional[str] = None) -> ImageResponse:
        operation = req.operation or ("edit" if req.input_images else "generate")
        errors: List[str] = []
        attempts: list[dict] = []
        candidates = list(self._image)
        if preferred_id:
            candidates.sort(key=lambda p: 0 if p.id == preferred_id else 1)

        eligible: list[ImageProvider] = []
        for p in candidates:
            cooldown = self._cooldown_remaining(p.id)
            if cooldown > 0:
                attempts.append({
                    "provider": p.id,
                    "model": getattr(p, "model", ""),
                    "status": "cooldown",
                    "cooldown_remaining_s": round(cooldown, 3),
                })
                continue
            try:
                if p.available() and p.supports(operation):
                    eligible.append(p)
            except Exception:
                continue

        deadline = time.monotonic() + self.media_total_timeout_s
        for provider_index, p in enumerate(eligible):
            remaining_providers = len(eligible) - provider_index
            remaining_total = max(0.0, deadline - time.monotonic())
            if remaining_total <= 0:
                break

            # Give the current image provider its configured attempt budget when
            # possible, while still reserving a small deterministic slice for
            # later fallbacks. Retries spend only whatever time remains after an
            # early transient failure; the first healthy request is never split
            # in half merely because a retry is allowed.
            fallback_reserve = min(10.0, self.media_attempt_timeout_s)
            requested_reserve = fallback_reserve * max(0, remaining_providers - 1)
            # Never reserve so much that the current provider is effectively
            # skipped under a short total deadline. At most half of the
            # currently available routed budget is held for later fallbacks.
            reserved_for_fallbacks = min(requested_reserve, remaining_total / 2.0)
            provider_budget = min(
                self.media_attempt_timeout_s,
                max(0.001, remaining_total - reserved_for_fallbacks),
            )
            max_attempts = 1 if getattr(p, "billable_async_job", False) else self.same_provider_retries + 1
            provider_deadline = time.monotonic() + provider_budget

            for attempt in range(max_attempts):
                remaining_provider = max(0.0, provider_deadline - time.monotonic())
                if remaining_provider <= 0:
                    break
                attempt_budget = min(self.media_attempt_timeout_s, max(0.001, remaining_provider))
                attempt_started = time.monotonic()
                try:
                    async with asyncio.timeout(attempt_budget):
                        resp = await (p.edit(req) if operation == "edit" else p.generate(req))
                    if not isinstance(resp, ImageResponse) or not resp.images:
                        raise ProviderError("Malformed or empty image response")
                    attempts.append({
                        "provider": p.id,
                        "model": resp.model,
                        "attempt": attempt + 1,
                        "status": "success",
                        "latency_s": round(time.monotonic() - attempt_started, 3),
                    })
                    resp.provider_attempts = attempts
                    self._record_success(p.id)
                    return resp
                except TimeoutError:
                    exc: ProviderError = ProviderTimeoutError(
                        f"{p.id} image attempt timed out after {attempt_budget:.1f}s"
                    )
                except ProviderError as caught:
                    exc = caught
                except Exception as caught:  # noqa: BLE001
                    exc = provider_exception(p.id, caught)

                status = getattr(exc, "status_code", None)
                reason = type(exc).__name__
                transient = (
                    isinstance(exc, TransientProviderError)
                    or (isinstance(status, int) and 500 <= status < 600)
                    or classify_transient(exc)
                )
                attempts.append({
                    "provider": p.id,
                    "model": getattr(p, "model", ""),
                    "attempt": attempt + 1,
                    "status": "failed",
                    "status_code": status,
                    "error_type": reason,
                    "latency_s": round(time.monotonic() - attempt_started, 3),
                })
                self._record_failure(p.id, reason, status, transient=transient)
                errors.append(
                    f"{p.id}: {reason}"
                    + (f" HTTP {status}" if isinstance(status, int) else "")
                )

                if status == 429:
                    self._mark_rate_limited(p.id, retry_delay(exc))
                    break
                if not transient or attempt + 1 >= max_attempts:
                    break

                remaining_provider = max(0.0, provider_deadline - time.monotonic())
                if remaining_provider <= 0.001:
                    break
                requested_wait = min(
                    self.max_retry_wait_s,
                    self.backoff_base ** (attempt + 1),
                )
                # Preserve any positive remainder for the next attempt instead
                # of imposing an arbitrary one-second minimum. This keeps
                # sub-second test/deadline configurations correct.
                if requested_wait >= remaining_provider - 0.001:
                    break
                if requested_wait > 0:
                    await asyncio.sleep(requested_wait)

        capability = "image_to_image" if operation == "edit" else "text_to_image"
        if time.monotonic() >= deadline and eligible:
            errors.append("routed image deadline exhausted")
        suffix = " | ".join(errors)
        guidance = provider_failure_guidance(errors)
        raise ProviderError(
            f"No available image provider supports {capability}."
            + (f" {suffix}" if suffix else "")
            + (f" {guidance}" if guidance else "")
        )

    # ---- Video ----
    async def generate_video(self, req: VideoRequest, preferred_id: Optional[str] = None) -> VideoResponse:
        operation = req.operation or "generate"
        errors: List[str] = []
        attempts: list[dict] = []
        candidates = list(self._video)
        if preferred_id:
            candidates.sort(key=lambda p: 0 if p.id == preferred_id else 1)

        eligible: list[VideoProvider] = []
        for p in candidates:
            cooldown = self._cooldown_remaining(p.id)
            if cooldown > 0:
                attempts.append({
                    "provider": p.id,
                    "model": getattr(p, "model", ""),
                    "status": "cooldown",
                    "cooldown_remaining_s": round(cooldown, 3),
                })
                continue
            try:
                if p.available() and p.supports(operation):
                    eligible.append(p)
            except Exception:
                continue

        deadline = time.monotonic() + self.media_total_timeout_s
        for index, p in enumerate(eligible):
            remaining_providers = len(eligible) - index
            remaining_total = max(0.0, deadline - time.monotonic())
            if remaining_total <= 0:
                break

            # A long-running video submission must never consume the entire
            # routed deadline. Video generation can create billable remote jobs,
            # so each provider is attempted only once and receives a reserved
            # share of the remaining total budget.
            provider_budget = min(
                self.media_attempt_timeout_s,
                max(0.001, remaining_total / max(1, remaining_providers)),
            )
            attempt_started = time.monotonic()
            try:
                async with asyncio.timeout(provider_budget):
                    response = await p.generate(req)
                if not isinstance(response, VideoResponse) or not response.video:
                    raise ProviderError("Malformed or empty video response")
                attempts.append({
                    "provider": p.id,
                    "model": response.model,
                    "attempt": 1,
                    "status": "success",
                    "latency_s": round(time.monotonic() - attempt_started, 3),
                })
                response.provider_attempts = attempts
                self._record_success(p.id)
                return response
            except TimeoutError:
                exc: ProviderError = ProviderTimeoutError(
                    f"{p.id} video attempt timed out after {provider_budget:.1f}s"
                )
            except ProviderError as caught:
                exc = caught
            except Exception as caught:  # noqa: BLE001
                exc = provider_exception(p.id, caught)

            status = getattr(exc, "status_code", None)
            reason = type(exc).__name__
            transient = (
                isinstance(exc, TransientProviderError)
                or (isinstance(status, int) and 500 <= status < 600)
                or classify_transient(exc)
            )
            attempts.append({
                "provider": p.id,
                "model": getattr(p, "model", ""),
                "attempt": 1,
                "status": "failed",
                "status_code": status,
                "error_type": reason,
                "latency_s": round(time.monotonic() - attempt_started, 3),
            })
            self._record_failure(p.id, reason, status, transient=transient)
            errors.append(
                f"{p.id}: {reason}"
                + (f" HTTP {status}" if isinstance(status, int) else "")
            )
            if status == 429:
                self._mark_rate_limited(p.id, retry_delay(exc))

        mapping = {
            "generate": "text_to_video",
            "animate": "image_to_video",
            "text_image": "text_image_to_video",
            "transform": "video_to_video",
        }
        capability = mapping.get(operation, operation)
        if time.monotonic() >= deadline and eligible:
            errors.append("routed video deadline exhausted")
        guidance = provider_failure_guidance(errors)
        raise ProviderError(
            f"No available video provider supports {capability}. "
            "Configure GEMINI_API_KEY for Veo or FAL_KEY for Wan/Kling."
            + (f" {' | '.join(errors)}" if errors else "")
            + (f" {guidance}" if guidance else "")
        )

    def _ordered_candidates(self, preferred_id: Optional[str]) -> List[LLMProvider]:
        if not preferred_id:
            return self._llm
        preferred = [p for p in self._llm if p.id == preferred_id]
        rest = [p for p in self._llm if p.id != preferred_id]
        return preferred + rest

    # ---- review-layer provider independence ----
    def _record_job_success(self, job_id: str, provider: LLMProvider) -> None:
        if not job_id:
            return
        vendor, model = provider_identity(provider)
        self._last_success_by_job[job_id] = {
            "id": provider.id, "provider": vendor, "model": model,
        }

    def last_success_for(self, job_id: str) -> Optional[dict]:
        """Last provider/model that served ``job_id`` (in-memory routing proof)."""
        if not job_id:
            return None
        return self._last_success_by_job.get(job_id)

    def clear_job_routing(self, job_id: str) -> None:
        self._last_success_by_job.pop(job_id, None)

    def provider_identity_for(self, provider_id: Optional[str]) -> Optional[dict]:
        for p in self._llm:
            if p.id == provider_id:
                vendor, model = provider_identity(p)
                return {"id": p.id, "provider": vendor, "model": model}
        return None

    def is_independent(self, candidate: LLMProvider, implementation: dict) -> bool:
        """True when ``candidate`` is a different authority from ``implementation``.

        Independence requires a different provider/model pair: the implementer's
        exact model can never review its own work. A missing implementation
        identity cannot be proven independent, so it returns False (fail closed).
        """
        impl_vendor = str((implementation or {}).get("provider", "")).strip().lower()
        impl_model = str((implementation or {}).get("model", "")).strip().lower()
        if not impl_vendor and not impl_model:
            return False
        vendor, model = provider_identity(candidate)
        if not vendor and not model:
            return False
        return (vendor, model) != (impl_vendor, impl_model)

    def is_cross_vendor(self, candidate: LLMProvider, implementation: dict) -> bool:
        """True when ``candidate``'s vendor differs from the authority's vendor.

        Strict review prefers true vendor separation: another model from the
        same vendor is not treated as equivalent independent authority.
        """
        impl_vendor = str((implementation or {}).get("provider", "")).strip().lower()
        vendor, _ = provider_identity(candidate)
        if not impl_vendor or not vendor:
            return False
        return vendor != impl_vendor

    def reviewer_candidates(
        self, implementation: Optional[dict], preferred_ids: Optional[List[str]] = None,
        *, exclude: Optional[List[dict]] = None,
    ) -> List[LLMProvider]:
        """Healthy providers that differ from every excluded authority.

        ``implementation`` drives ordering (cross-vendor preferred) and is always
        excluded. ``exclude`` adds further authorities that must not review the
        change (e.g. the original implementer plus the latest repair author).
        Providers that are cooling down or unavailable are excluded.
        """
        impl_vendor = str((implementation or {}).get("provider", "")).strip().lower()
        exclusions = [implementation or {}]
        for extra in (exclude or []):
            if extra and (extra.get("provider") or extra.get("model")):
                exclusions.append(extra)
        candidates = [
            p for p in self._llm
            if p.available() and self._cooldown_remaining(p.id) <= 0
        ]
        independent = [
            p for p in candidates
            if all(self.is_independent(p, e) for e in exclusions)
        ]
        if preferred_ids:
            rank = {pid: i for i, pid in enumerate(preferred_ids)}
            independent.sort(key=lambda p: rank.get(p.id, len(rank)))
        else:
            # Prefer a genuinely different vendor over another model of the same
            # vendor; keep the configured order as the stable tie-break.
            independent.sort(key=lambda p: 0 if provider_identity(p)[0] != impl_vendor else 1)
        return independent

    async def complete_with_provider(
        self,
        req: CompletionRequest,
        provider: LLMProvider,
        job_id: Optional[str] = None,
        event_callback=None,
        *,
        max_attempts: Optional[int] = None,
    ) -> CompletionResponse:
        """Call ONE explicit provider, without falling back to another.

        This is the reviewer path: the caller has already proven that
        ``provider`` is independent of the implementation, so a silent failover
        to the implementer's own provider would defeat the separation. Transient
        failures retry on the same provider only (bounded); a terminal failure
        raises so the caller can pick a different independent reviewer.
        """
        attempts = self.same_provider_retries + 1 if max_attempts is None else max(1, int(max_attempts))
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            started = time.monotonic()
            await self._emit(event_callback, "PROVIDER REQUEST START", provider=provider.id,
                             attempt=attempt + 1, timeout_s=round(self.attempt_timeout_s, 2),
                             job_id=job_id)
            try:
                async with asyncio.timeout(self.attempt_timeout_s):
                    resp = await provider.complete(req)
                    if (not isinstance(resp, CompletionResponse)
                            or not isinstance(resp.text, str) or not resp.text.strip()):
                        raise ProviderError("Malformed or empty provider response")
                    if resp.finish_reason in {"length", "max_tokens", "MAX_TOKENS"}:
                        raise ProviderError("Provider response was truncated at the output limit")
                    # JSON validity is deliberately NOT enforced here: a
                    # malformed reviewer body must reach the review parser so it
                    # is classified as malformed output (never an approval),
                    # rather than being masked as a provider outage.
            except TimeoutError:
                last_exc = ProviderTimeoutError("provider attempt timed out")
                await self._emit(event_callback, "PROVIDER REQUEST TIMEOUT", provider=provider.id,
                                 attempt=attempt + 1, elapsed_s=round(time.monotonic() - started, 3))
            except ProviderError as exc:
                last_exc = exc
                await self._emit(event_callback, "PROVIDER REQUEST ERROR", provider=provider.id,
                                 attempt=attempt + 1, error_type=type(exc).__name__,
                                 status_code=getattr(exc, "status_code", None))
            except Exception as exc:  # noqa: BLE001
                last_exc = provider_exception(provider.id, exc)
                await self._emit(event_callback, "PROVIDER REQUEST ERROR", provider=provider.id,
                                 attempt=attempt + 1, status_code=last_exc.status_code)
            else:
                await self._emit(event_callback, "PROVIDER RESPONSE", provider=provider.id,
                                 attempt=attempt + 1, elapsed_s=round(time.monotonic() - started, 3))
                if job_id:
                    try:
                        from ..engine.usage import tracker
                        tracker.record(job_id, resp.usage, provider.provider, provider.model)
                    except Exception:  # noqa: BLE001
                        pass
                self._record_success(provider.id)
                return resp

            status = getattr(last_exc, "status_code", None)
            transient = (
                isinstance(last_exc, TransientProviderError)
                or (isinstance(status, int) and 500 <= status < 600)
                or classify_transient(last_exc)
            )
            if status == 429:
                self._mark_rate_limited(provider.id, getattr(last_exc, "retry_after", None))
                break
            if isinstance(status, int) and status in (401, 402, 403, 410):
                # Record the external account block on the same cooldown channel
                # as a rate limit. Otherwise the provider keeps reporting
                # ``available()`` and the router looks like it has a healthy
                # authority when it is in fact externally blocked.
                self._mark_rate_limited(provider.id, reason="external_block")
                break
            if not transient or attempt + 1 >= attempts:
                break
            hint = retry_delay(last_exc)
            wait = max(self.backoff_base ** (attempt + 1), hint or 0)
            if wait > self.max_retry_wait_s:
                break
            await asyncio.sleep(wait)
        reason = type(last_exc).__name__ if last_exc else "unknown"
        status = getattr(last_exc, "status_code", None)
        raise ProviderError(
            f"reviewer provider {provider.id} failed: {reason}"
            + (f" HTTP {status}" if isinstance(status, int) else ""),
            status_code=status if isinstance(status, int) else None,
        )


# Module-level singleton
router = ProviderRouter()


