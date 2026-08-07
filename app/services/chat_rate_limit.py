"""In-memory rate limiter for DRUVO Chat (per client IP)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class ChatRateLimiter:
    def __init__(self, max_requests: int = 30, window_seconds: int = 3600) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, client_key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            bucket = self._hits[client_key]
            self._hits[client_key] = [t for t in bucket if t > cutoff]
            if len(self._hits[client_key]) >= self._max:
                oldest = min(self._hits[client_key])
                retry_after = max(1, int(self._window - (now - oldest)))
                return False, retry_after
            self._hits[client_key].append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter: ChatRateLimiter | None = None


def get_chat_rate_limiter(max_requests: int = 30, window_seconds: int = 3600) -> ChatRateLimiter:
    global _limiter
    if _limiter is None or _limiter._max != max_requests or _limiter._window != window_seconds:
        _limiter = ChatRateLimiter(max_requests, window_seconds)
    return _limiter
