"""In-memory sliding-window rate limit, per API process (a single container serves the site)."""

import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import Request


class RateLimiter:
    def __init__(self, limit: int, window: timedelta):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: datetime) -> bool:
        """Count one attempt for `key`; False when it is over the limit (the refused attempt is not counted)."""
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(request: Request) -> str:
    """Set by Caddy from the address it trusts (deploy/Caddyfile); the API is not reachable without it."""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
