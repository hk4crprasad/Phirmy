"""Atomic shared sliding windows with a bounded, thread-safe outage fallback."""
from collections import deque
from functools import lru_cache
import hashlib
import hmac
import logging
import math
import secrets
import threading
import time

from fastapi import HTTPException
from redis import Redis
from redis.exceptions import RedisError

from .config import settings

log = logging.getLogger(__name__)

# Use Redis time so different API clocks cannot extend or shorten a window.
WINDOW = """
local clock = redis.call('TIME')
local now = clock[1] * 1000 + math.floor(clock[2] / 1000)
local period = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - period)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return math.max(1, tonumber(oldest[2]) + period - now)
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], period)
return 0
"""


@lru_cache(maxsize=4)
def connection(url):
    return Redis.from_url(url, socket_connect_timeout=.25, socket_timeout=.25,
                          retry_on_timeout=False, max_connections=16)


class RateLimiter:
    def __init__(self):
        self.entries = {}
        self._guard = threading.Lock()
        self._retry_at = 0.0
        self._warn_at = 0.0

    @staticmethod
    def deny(seconds):
        raise HTTPException(429, "Too many requests; retry shortly",
                            headers={"Retry-After": str(max(1, math.ceil(seconds)))})

    def check(self, key, limit=30, period=60):
        if limit < 1 or period <= 0:
            raise ValueError("Rate limits require a positive limit and period")
        # Never put emails, IP addresses, API keys or installation IDs in Redis keys.
        identifier = hmac.new(settings.app_secret.encode(), key.encode(), hashlib.sha256).hexdigest()
        t = time.monotonic()
        if settings.redis_url and t >= self._retry_at:
            try:
                retry_ms = connection(settings.redis_url).eval(
                    WINDOW, 1, "studio:rate:v1:" + identifier,
                    limit, math.ceil(period * 1000), secrets.token_hex(16))
            except (RedisError, OSError, ValueError):
                # A circuit break bounds outage overhead. Never log connection URLs.
                self._retry_at = t + 5
            else:
                if retry_ms:
                    self.deny(retry_ms / 1000)
                return
        with self._guard:
            if t >= self._warn_at:
                log.warning("Shared rate limiting unavailable; using per-process limits")
                self._warn_at = t + 60
            times, window = self.entries.get(identifier, (deque(), period))
            while times and times[0] <= t - period:
                times.popleft()
            if len(times) >= limit:
                self.deny(times[0] + period - t)
            if identifier not in self.entries and len(self.entries) >= 10000:
                self.entries = {k: (v, p) for k, (v, p) in self.entries.items()
                                if v and v[-1] + p > t}
                if len(self.entries) >= 10000:
                    self.deny(period)
            times.append(t)
            self.entries[identifier] = (times, max(window, period))


limiter = RateLimiter()


def cost_limits(request, workspace_id, identity):
    """Independent IP and actor limits; rotating either cannot bypass the other."""
    if request.method != "POST":
        return
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    suffix = path.partition("/workspaces/{workspace_id}")[2]
    limits = {
        "/knowledge": (20, 3600),
        "/knowledge/{kb_id}/recrawls": (20, 3600),
        "/knowledge/{kb_id}/documents": (30, 3600),
        "/agents/generate": (10, 3600),
        "/tools/{tool_id}/test": (30, 3600),
        "/keys": (10, 3600),
        "/invitations": (20, 3600),
        "/payments/orders": (20, 3600),
        "/payments/verify": (30, 3600),
    }
    if suffix not in limits:
        return
    limit, period = limits[suffix]
    ip = request.client.host if request.client else "unknown"
    limiter.check(f"cost:{suffix}:ip:{ip}", limit, period)
    limiter.check(f"cost:{suffix}:actor:{workspace_id}:{identity}", limit, period)
