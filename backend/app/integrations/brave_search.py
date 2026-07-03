"""Brave Search API client.

The Artifact pipeline uses Brave's Web Search endpoint to estimate whether
important extracted phrases already appear on the public web. This adapter
keeps API-key handling, retries, and response parsing outside worker logic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings

BRAVE_RETRY_STATUSES = {429, 500, 502, 503, 504}
BRAVE_TIMEOUT_SECONDS = 15.0


class BraveSearchError(RuntimeError):
    """Raised when Brave Search cannot return a usable response."""


@dataclass(frozen=True)
class BraveSearchResult:
    """Normalized Brave Search response used by rarity scoring."""

    query: str
    total_hits: int
    results: list[dict[str, Any]]


async def _default_sleep(seconds: float) -> None:
    """Sleep between transient Brave retry attempts."""
    await asyncio.sleep(seconds)


def _parse_total_hits(payload: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """Return the best available web hit count from a Brave response payload."""
    web_payload = payload.get("web") or {}
    if not isinstance(web_payload, dict):
        return 0, []
    raw_results = web_payload.get("results") or []
    results = (
        [result for result in raw_results if isinstance(result, dict)]
        if isinstance(raw_results, list)
        else []
    )
    raw_total = web_payload.get("total") or web_payload.get("total_count")
    if isinstance(raw_total, int):
        return max(raw_total, len(results)), results
    return len(results), results


async def search_web(
    query: str,
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] = _default_sleep,
) -> BraveSearchResult:
    """Search Brave Web Search API and return normalized web-result counts."""
    resolved_settings = settings or get_settings()
    api_key = resolved_settings.brave_search_api_key
    if api_key is None:
        raise BraveSearchError("BRAVE_SEARCH_API_KEY is not configured.")

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key.get_secret_value(),
    }
    params: dict[str, str | int] = {
        "q": query,
        "count": 20,
        "result_filter": "web",
        "search_lang": "en",
        "country": "US",
    }

    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(timeout=BRAVE_TIMEOUT_SECONDS)
    try:
        for attempt in range(3):
            try:
                response = await resolved_client.get(
                    resolved_settings.brave_search_base_url,
                    params=params,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise BraveSearchError("Brave Search request failed.") from exc
                await sleep(2.0**attempt)
                continue

            if response.status_code in BRAVE_RETRY_STATUSES:
                if attempt == 2:
                    raise BraveSearchError(
                        f"Brave Search returned {response.status_code}."
                    )
                await sleep(2.0**attempt)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise BraveSearchError(
                    f"Brave Search returned {response.status_code}."
                ) from exc

            payload = response.json()
            if not isinstance(payload, dict):
                raise BraveSearchError("Brave Search returned malformed JSON.")
            total_hits, results = _parse_total_hits(payload)
            return BraveSearchResult(
                query=query,
                total_hits=total_hits,
                results=results,
            )
    finally:
        if owns_client:
            await resolved_client.aclose()

    raise BraveSearchError("Brave Search request failed.")
