"""Small, dependency-free login throttle for the single-owner deployment."""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _AttemptBucket:
    failures: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0
    last_seen: float = 0.0


class LoginRateLimiter:
    """Limits failures per client without retaining unbounded client state."""

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: int = 15 * 60,
        block_seconds: int = 15 * 60,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max(1, max_failures)
        self.window_seconds = max(1, window_seconds)
        self.block_seconds = max(1, block_seconds)
        self.max_clients = max(100, max_clients)
        self._clock = clock
        self._buckets: dict[str, _AttemptBucket] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return 0
            bucket.last_seen = now
            if bucket.blocked_until <= now:
                bucket.blocked_until = 0.0
                self._trim(bucket, now)
                if not bucket.failures:
                    self._buckets.pop(key, None)
                return 0
            return max(1, int(bucket.blocked_until - now + 0.999))

    def record_failure(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            self._prune_if_needed(now)
            bucket = self._buckets.setdefault(key, _AttemptBucket())
            bucket.last_seen = now
            self._trim(bucket, now)
            bucket.failures.append(now)
            if len(bucket.failures) >= self.max_failures:
                bucket.blocked_until = now + self.block_seconds
                return self.block_seconds
            return 0

    def record_success(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)

    def _trim(self, bucket: _AttemptBucket, now: float) -> None:
        cutoff = now - self.window_seconds
        while bucket.failures and bucket.failures[0] <= cutoff:
            bucket.failures.popleft()

    def _prune_if_needed(self, now: float) -> None:
        if len(self._buckets) < self.max_clients:
            return
        stale_before = now - max(self.window_seconds, self.block_seconds)
        stale = [
            key for key, bucket in self._buckets.items()
            if bucket.last_seen < stale_before and bucket.blocked_until <= now
        ]
        for key in stale:
            self._buckets.pop(key, None)
        if len(self._buckets) >= self.max_clients:
            oldest = min(self._buckets, key=lambda key: self._buckets[key].last_seen)
            self._buckets.pop(oldest, None)


login_limiter = LoginRateLimiter(
    max_failures=int(os.environ.get("LOGIN_MAX_FAILURES", "5")),
    window_seconds=int(os.environ.get("LOGIN_WINDOW_SECONDS", "900")),
    block_seconds=int(os.environ.get("LOGIN_BLOCK_SECONDS", "900")),
)
