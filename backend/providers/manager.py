"""Provider selection, retry, fallback and usage accounting."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Awaitable, Callable, Type

from .base import (
    ErrorKind,
    GeneratedImage,
    GenerationInput,
    ImageProvider,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRoutingResult,
    ProviderUnsupportedCapabilityError,
)

logger = logging.getLogger("lumina.providers")

DEFAULT_ORDER = "comfyui,fal,bfl,replicate,openai,gemini,local"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_KINDS = {ErrorKind.QUOTA, ErrorKind.RATE_LIMIT, ErrorKind.TIMEOUT, ErrorKind.UNAVAILABLE}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _utc_iso(epoch: float | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class ProviderManager:
    def __init__(self, registry: dict[str, Type[ImageProvider]]) -> None:
        self.registry = registry
        self.usage = Counter()
        self.failures = Counter()
        self._cooldowns: dict[str, float] = {}
        self._last_safe_errors: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    def names(self) -> list[str]:
        return list(self.registry)

    def _order_names(self, requested: str | None = None) -> list[str]:
        seen: set[str] = set()
        names: list[str] = []
        if requested:
            names.append(requested.lower())
        env_order = os.getenv("IMAGE_PROVIDER_ORDER") or os.getenv("IMAGE_PROVIDER_FALLBACKS") or DEFAULT_ORDER
        names.extend(x.strip().lower() for x in env_order.split(",") if x.strip())
        names.extend(sorted(self.registry, key=lambda n: self.registry[n].priority))
        ordered: list[str] = []
        for name in names:
            if name in self.registry and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def configured_names(self) -> list[str]:
        return [name for name in self._order_names() if self.registry[name].is_configured()]

    async def _cooldown_until(self, name: str) -> float | None:
        async with self._lock:
            until = self._cooldowns.get(name)
            if until and until <= time.time():
                self._cooldowns.pop(name, None)
                return None
            return until

    async def _mark_failure(self, exc: ProviderError) -> None:
        self.failures[exc.provider] += 1
        self._last_safe_errors[exc.provider] = exc.safe_summary()
        if not self._is_failover_error(exc):
            return
        seconds = exc.retry_after_seconds or _env_int("IMAGE_PROVIDER_COOLDOWN_SECONDS", 300)
        async with self._lock:
            self._cooldowns[exc.provider] = time.time() + max(0, seconds)

    def _is_failover_error(self, exc: ProviderError) -> bool:
        if exc.status_code in RETRYABLE_STATUS_CODES:
            return True
        if exc.kind in RETRYABLE_KINDS:
            return True
        return bool(exc.retryable)

    def _supports(
        self,
        provider: ImageProvider,
        *,
        operation: str,
        aspect_ratio: str = "1:1",
        reference_count: int = 0,
        has_mask: bool = False,
    ) -> bool:
        caps = provider.capabilities
        if operation == "generate" and not caps.generation:
            return False
        if operation == "edit" and not caps.editing:
            return False
        if aspect_ratio and aspect_ratio not in caps.aspect_ratios:
            return False
        if reference_count and not caps.identity_references:
            return False
        if reference_count and caps.maximum_reference_images and reference_count > caps.maximum_reference_images:
            return False
        if has_mask and not caps.masks:
            return False
        return True

    async def _candidates(
        self,
        requested: str | None,
        *,
        operation: str,
        aspect_ratio: str = "1:1",
        reference_count: int = 0,
        has_mask: bool = False,
    ) -> list[ImageProvider]:
        candidates: list[ImageProvider] = []
        for name in self._order_names(requested):
            cls = self.registry[name]
            provider = cls()
            if not cls.is_configured():
                continue
            if await self._cooldown_until(name):
                continue
            if not self._supports(
                provider,
                operation=operation,
                aspect_ratio=aspect_ratio,
                reference_count=reference_count,
                has_mask=has_mask,
            ):
                continue
            candidates.append(provider)
        return candidates

    async def _route(
        self,
        *,
        operation: str,
        requested: str | None,
        aspect_ratio: str,
        reference_count: int,
        has_mask: bool,
        call: Callable[[ImageProvider], Awaitable[list[GeneratedImage]]],
    ) -> ProviderRoutingResult:
        candidates = await self._candidates(
            requested,
            operation=operation,
            aspect_ratio=aspect_ratio,
            reference_count=reference_count,
            has_mask=has_mask,
        )
        if not candidates:
            raise ProviderUnsupportedCapabilityError(
                "manager",
                f"No configured provider supports {operation} for the requested capabilities.",
            )

        auto_fallback = _env_bool("IMAGE_PROVIDER_AUTO_FALLBACK", True)
        max_attempts = max(1, _env_int("IMAGE_PROVIDER_MAX_ATTEMPTS_PER_PROVIDER", 1))
        started = time.perf_counter()
        attempted: list[str] = []
        failures: list[dict] = []

        for index, provider in enumerate(candidates):
            for attempt in range(max_attempts):
                if provider.name not in attempted:
                    attempted.append(provider.name)
                try:
                    images = await call(provider)
                    if not images or any(not image.data for image in images):
                        raise ProviderInvalidResponseError(provider.name)
                    self.usage[provider.name] += len(images)
                    return ProviderRoutingResult(
                        provider=provider.name,
                        images=images,
                        attempted_providers=attempted,
                        provider_failures=failures,
                        fallback_used=bool(failures),
                        generation_duration_ms=int((time.perf_counter() - started) * 1000),
                    )
                except ProviderError as exc:
                    await self._mark_failure(exc)
                    failures.append(exc.safe_summary())
                    logger.warning("provider=%s kind=%s attempt=%s", provider.name, exc.kind, attempt + 1)
                    retry_same = exc.retryable and attempt + 1 < max_attempts
                    if retry_same:
                        await asyncio.sleep(min(8.0, 0.75 * (2 ** attempt)))
                        continue
                    if not auto_fallback or not self._is_failover_error(exc):
                        raise ProviderError(
                            "manager",
                            exc.public_message(),
                            kind=exc.kind,
                            retryable=False,
                            status_code=exc.status_code,
                            safe_message=exc.public_message(),
                        ) from exc
                    break
                except Exception as exc:
                    wrapped = ProviderError(
                        provider.name,
                        "Provider request failed.",
                        kind=ErrorKind.UNAVAILABLE,
                        retryable=True,
                        safe_message="Provider request failed.",
                    )
                    await self._mark_failure(wrapped)
                    failures.append(wrapped.safe_summary())
                    logger.exception("Unexpected provider failure: %s", provider.name)
                    if not auto_fallback or index == len(candidates) - 1:
                        break

        message = "; ".join(f"{f['provider']}: {f['safe_message']}" for f in failures)
        raise ProviderError(
            "manager",
            message or "All providers failed.",
            kind=ErrorKind.UNAVAILABLE,
            retryable=False,
            safe_message=message or "All providers failed.",
        )

    async def generate_result(self, spec: GenerationInput, requested: str | None = None) -> ProviderRoutingResult:
        return await self._route(
            operation="generate",
            requested=requested,
            aspect_ratio=spec.aspect_ratio or "1:1",
            reference_count=len(spec.reference_images),
            has_mask=False,
            call=lambda provider: provider.generate(spec),
        )

    async def generate(self, spec: GenerationInput, requested: str | None = None) -> tuple[str, list[GeneratedImage]]:
        result = await self.generate_result(spec, requested=requested)
        return result.provider, result.images

    async def edit_result(
        self,
        *,
        source_bytes: bytes,
        source_mime: str,
        instruction: str,
        mask_bytes: bytes | None = None,
        mask_mime: str | None = None,
        identity_refs: list[bytes] | None = None,
        requested: str | None = None,
    ) -> ProviderRoutingResult:
        async def call(provider: ImageProvider) -> list[GeneratedImage]:
            image = await provider.edit(
                source_bytes=source_bytes,
                source_mime=source_mime,
                instruction=instruction,
                mask_bytes=mask_bytes,
                mask_mime=mask_mime,
                identity_refs=identity_refs,
            )
            return [image]

        return await self._route(
            operation="edit",
            requested=requested,
            aspect_ratio="1:1",
            reference_count=len(identity_refs or []),
            has_mask=bool(mask_bytes),
            call=call,
        )

    async def statuses(self) -> list[dict]:
        output: list[dict] = []
        for name in self._order_names():
            provider = self.registry[name]()
            status = await provider.health_check()
            until = await self._cooldown_until(name)
            item = status.as_dict()
            item.update(
                {
                    "priority": self._order_names().index(name),
                    "available": bool(status.configured and status.healthy and not until),
                    "cooldown_until": _utc_iso(until),
                    "last_safe_error": self._last_safe_errors.get(name),
                    "generated": self.usage[name],
                    "failures": self.failures[name],
                }
            )
            output.append(item)
        return output

    async def health_summary(self) -> dict:
        statuses = await self.statuses()
        return {
            "order": self._order_names(),
            "configured": [item["name"] for item in statuses if item["configured"]],
            "available": [item["name"] for item in statuses if item["available"]],
            "auto_fallback": _env_bool("IMAGE_PROVIDER_AUTO_FALLBACK", True),
            "cooldown_seconds": _env_int("IMAGE_PROVIDER_COOLDOWN_SECONDS", 300),
        }
