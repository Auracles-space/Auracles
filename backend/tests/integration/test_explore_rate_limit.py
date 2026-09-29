"""Rate limits on the public, unauthenticated Explore search surface.

`/explore/demand` was limited from the start, with a comment naming it "a
scraping target". Its far more expensive siblings — the list-and-filter
endpoints that run full-text search across thirteen facets — were not, and on
2026-09-29 staging was absorbing roughly six requests a second of unexplained
randomised-filter traffic against `/explore/catalog`.

Every one of these is reachable without a token, so the client IP is the only
identity there is.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.database import engine
from app.core.redis import get_redis
from app.modules.explore.router import SEARCH_RATE_LIMITER

SEARCH_PATHS = (
    "/v1/explore/catalog",
    "/v1/explore/frameworks",
    "/v1/explore/collections",
)


@pytest.fixture(autouse=True)
async def _clear_limiter_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Isolate this test's rate-limit keys and make the client IP real.

    `client_ip` only reads `X-Forwarded-For` when `TRUST_PROXY_HEADERS` is set,
    which is how staging runs behind the ALB. Without it every request here
    would resolve to the same ASGI peer and share one counter — which would
    make the per-client test pass for the wrong reason, and would be the real
    behaviour of any environment that forgets the setting.
    """
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()
    await engine.dispose()
    get_redis.cache_clear()
    redis = get_redis()
    async for key in redis.scan_iter(f"rate_limit:{SEARCH_RATE_LIMITER.namespace}:*"):
        await redis.delete(key)
    yield
    async for key in redis.scan_iter(f"rate_limit:{SEARCH_RATE_LIMITER.namespace}:*"):
        await redis.delete(key)
    monkeypatch.undo()
    get_settings.cache_clear()
    get_redis.cache_clear()


@pytest.mark.parametrize("path", SEARCH_PATHS)
async def test_search_endpoint_refuses_a_scraper(
    client: AsyncClient,
    path: str,
) -> None:
    """Each public search endpoint must stop one IP past its window.

    Asserted per path rather than for `/catalog` alone: the three take the same
    filters over the same index, so a limit on one is bypassed by changing a
    single path segment.
    """
    headers = {"X-Forwarded-For": "203.0.113.77"}
    for _ in range(SEARCH_RATE_LIMITER.limit):
        allowed = await client.get(path, headers=headers)
        assert allowed.status_code == 200, allowed.text

    refused = await client.get(path, headers=headers)

    assert refused.status_code == 429
    assert "try again" in refused.text


async def test_the_limit_is_per_client_not_global(client: AsyncClient) -> None:
    """One noisy IP must not lock every other visitor out of Explore.

    A global counter would turn a single scraper into an outage for real
    buyers, which is worse than the scraping.
    """
    noisy = {"X-Forwarded-For": "203.0.113.78"}
    for _ in range(SEARCH_RATE_LIMITER.limit + 1):
        await client.get("/v1/explore/catalog", headers=noisy)

    bystander = await client.get(
        "/v1/explore/catalog",
        headers={"X-Forwarded-For": "203.0.113.79"},
    )

    assert bystander.status_code == 200
