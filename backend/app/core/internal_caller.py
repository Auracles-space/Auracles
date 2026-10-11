"""Recognising our own server-side renderer as a distinct rate-limit caller.

Every server-rendered page fetches the API from the frontend host, so the API
sees one address for all of them no matter how many real visitors there are.
Per-IP limiting therefore cannot separate one visitor from another, and a
single noisy source consumes the bucket every visitor's render depends on.
That is not hypothetical: GPTBot crawling `/explore`'s filter facets drained
it on 2026-10-11 and the marketplace page told real visitors the catalog was
unavailable.

The header proves origin, not identity, and grants exactly one thing: a
separate bucket. It must never gate access to data, because anyone who learns
the secret would otherwise gain more than a higher request ceiling.
"""

from __future__ import annotations

import secrets

from fastapi import Request

from app.core.config import Settings, get_settings

INTERNAL_CALLER_HEADER = "x-internal-caller"


def is_internal_caller(request: Request, settings: Settings | None = None) -> bool:
    """Report whether a request carries our server renderer's shared secret.

    Compared in constant time, and false whenever the secret is unset so an
    unconfigured deployment trusts nobody instead of trusting everybody.

    Args:
        request: Incoming request, read for the internal-caller header.
        settings: Settings override, for tests.

    Returns:
        True when the header matches the configured secret.
    """
    resolved = settings or get_settings()
    expected = resolved.internal_api_secret
    if expected is None:
        return False
    presented = request.headers.get(INTERNAL_CALLER_HEADER)
    if not presented:
        return False
    return secrets.compare_digest(presented, expected.get_secret_value())
