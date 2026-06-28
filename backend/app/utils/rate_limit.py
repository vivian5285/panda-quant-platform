import threading
import time
from collections import defaultdict


class SlidingWindowRateLimiter:
    """In-memory rate limiter for auth/webhook endpoints."""

    def __init__(self):
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits[key]
            self._hits[key] = [t for t in bucket if t >= cutoff]
            if len(self._hits[key]) >= limit:
                return False
            self._hits[key].append(now)
            return True


rate_limiter = SlidingWindowRateLimiter()
