"""In-process per-IP rate limiting.

Cloudflare sits in front of the deployment and absorbs most abuse, but the API
does not depend on that: every visitor gets a sliding-window budget per process.
The limitation (per process, not per cluster) is documented in the README and
threat model rather than hidden.
"""

from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int, *, max_keys: int = 20000) -> None:
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._checks = 0

    def check(self, key: str) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        self._checks += 1
        if self._checks % 512 == 0:
            self._evict(now)
        bucket = self._hits.get(key)
        if bucket is None:
            if len(self._hits) >= self.max_keys:
                self._evict(now, force=True)
            bucket = deque()
            self._hits[key] = bucket
        cutoff = now - self.window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = max(1, int(bucket[0] + self.window - now) + 1)
            return False, retry_after
        bucket.append(now)
        return True, 0

    def _evict(self, now: float, *, force: bool = False) -> None:
        cutoff = now - self.window
        stale = [key for key, bucket in self._hits.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            self._hits.pop(key, None)
        if force and len(self._hits) >= self.max_keys:
            # Drop the oldest half as a last resort so memory stays bounded.
            ordered = sorted(self._hits.items(), key=lambda item: item[1][-1])
            for key, _bucket in ordered[: len(ordered) // 2]:
                self._hits.pop(key, None)
