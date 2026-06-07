"""Tests for the Brave Search integration adapter."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.integrations.brave_search import BraveSearchError, search_web


async def no_sleep(_: float) -> None:
    """Avoid retry delays in tests."""


@pytest.mark.asyncio
async def test_brave_search_sends_token_and_parses_web_results() -> None:
    """The adapter sends Brave auth headers and normalizes web hit counts."""
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a small Brave-like web response."""
        seen_headers["token"] = request.headers["X-Subscription-Token"]
        assert request.url.params["q"] == '"vendor risk workflow"'
        assert request.url.params["count"] == "20"
        return httpx.Response(
            200,
            json={
                "type": "search",
                "web": {
                    "results": [
                        {"title": "One", "url": "https://example.com/one"},
                        {"title": "Two", "url": "https://example.com/two"},
                    ]
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=15,
    ) as client:
        result = await search_web(
            '"vendor risk workflow"',
            settings=Settings(BRAVE_SEARCH_API_KEY="secret-token"),
            client=client,
            sleep=no_sleep,
        )

    assert seen_headers["token"] == "secret-token"
    assert result.total_hits == 2
    assert len(result.results) == 2


@pytest.mark.asyncio
async def test_brave_search_retries_429_then_degrades() -> None:
    """Rate-limit responses are retried before raising a provider error."""
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        """Return a Brave rate-limit response."""
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"type": "error", "error": {}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=15,
    ) as client:
        with pytest.raises(BraveSearchError):
            await search_web(
                '"vendor risk workflow"',
                settings=Settings(BRAVE_SEARCH_API_KEY="secret-token"),
                client=client,
                sleep=no_sleep,
            )

    assert attempts == 3
