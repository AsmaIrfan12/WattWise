"""Security utilities for runtime protection controls."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta


class SlidingWindowRateLimiter:
    """
    Async-safe sliding window rate limiter.
    Uses asyncio.Lock instead of threading.Lock to prevent deadlocks
    in FastAPI's async event loop.
    """

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    def _prune(self, key: str, now: datetime) -> None:
        window_start = now - timedelta(seconds=self.window_seconds)
        attempts = self._attempts[key]
        while attempts and attempts[0] < window_start:
            attempts.popleft()

    async def record_failure(self, key: str) -> None:
        now = datetime.utcnow()
        async with self._lock:
            self._prune(key, now)
            self._attempts[key].append(now)

    async def is_limited(self, key: str) -> bool:
        now = datetime.utcnow()
        async with self._lock:
            self._prune(key, now)
            return len(self._attempts[key]) >= self.max_attempts

    async def retry_after_seconds(self, key: str) -> int:
        now = datetime.utcnow()
        async with self._lock:
            self._prune(key, now)
            attempts = self._attempts[key]
            if len(attempts) < self.max_attempts:
                return 0
            oldest = attempts[0]
            retry_after = int(
                (oldest + timedelta(seconds=self.window_seconds) - now).total_seconds()
            )
            return max(retry_after, 1)

    async def reset(self, key: str) -> None:
        async with self._lock:
            self._attempts.pop(key, None)
