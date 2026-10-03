"""Rate-limit counter double for direct service-layer calls.

Service functions that rate-limit take the counter as an argument, so a test
calling one directly has to supply something. Every suite that needed this
previously grew its own `FakeRedis`; that is how `ttl` came to be missing from
thirteen of them at once.
"""

from __future__ import annotations


class InMemoryRateCounter:
    """Minimal in-memory `RedisCounter`.

    Counts in a dict and never expires, which is all a test asserting on the
    path *below* a limit requires. A test asserting on the limit itself should
    drive the endpoint against the real client instead.
    """

    def __init__(self) -> None:
        """Start with no counted keys."""
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        """Increment and return the count for ``key``."""
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        """Accept an expiry and keep the key, since nothing here expires."""
        del key, seconds
        return True

    async def ttl(self, key: str) -> int:
        """Report a live window so the limiter never repairs the key."""
        del key
        return 3600
