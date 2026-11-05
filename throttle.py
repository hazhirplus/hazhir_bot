"""Per-user anti-flood guard (sliding-window rate limiter).

Pure in-memory: no DB, no persistence. When a user exceeds their window,
updates are dropped silently except for one polite warning per
`warn_cooldown` seconds, so a spamming client gets feedback without the bot
spamming back. Admins get a higher limit (broadcasts/admin menus are bursty).
"""
from __future__ import annotations
import time
from collections import deque


class FloodGuard:
    def __init__(self, limit: int = 30, window: float = 60.0,
                 admin_limit: int = 120, warn_cooldown: float = 120.0):
        self.limit = limit
        self.window = window
        self.admin_limit = admin_limit
        self.warn_cooldown = warn_cooldown
        self._hits: dict[int, deque[float]] = {}
        self._last_warn: dict[int, float] = {}

    def _prune(self, user_id: int, now: float) -> deque:
        dq = self._hits.get(user_id)
        if dq is None:
            dq = self._hits[user_id] = deque()
        cutoff = now - self.window
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if not dq:
            del self._hits[user_id]
            dq = deque()
        return dq

    def allow(self, user_id: int, admin: bool = False,
              now: float | None = None) -> bool:
        """True if the update may proceed (and records the hit)."""
        now = time.monotonic() if now is None else now
        dq = self._prune(user_id, now)
        limit = self.admin_limit if admin else self.limit
        if len(dq) >= limit:
            return False
        dq.append(now)
        self._hits[user_id] = dq
        return True

    def warn_due(self, user_id: int, now: float | None = None) -> bool:
        """True at most once per `warn_cooldown` per user — gates the warning text."""
        now = time.monotonic() if now is None else now
        last = self._last_warn.get(user_id, 0.0)
        if now - last >= self.warn_cooldown:
            self._last_warn[user_id] = now
            return True
        return False
