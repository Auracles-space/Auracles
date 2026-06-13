"""Client network metadata helpers.

Behind a managed edge (Render in Phase 1, ALB in Phase 2) the TCP peer is the
proxy, so `request.client.host` is the proxy address for every request. Rate
limiting and audit logging need the real client address, which the trusted
proxy supplies in `X-Forwarded-For`. Parsing that header is only safe when we
know a trusted proxy overwrites any client-supplied value, so it is gated on an
explicit setting and defaults off.
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings, get_settings


def client_ip(request: Request, settings: Settings | None = None) -> str | None:
    """Return the originating client IP, honouring a trusted proxy header.

    When `TRUST_PROXY_HEADERS` is enabled, the left-most `X-Forwarded-For` entry
    (the original client as recorded by the trusted edge) is used. Otherwise the
    direct TCP peer is returned. Never trust the header without the setting:
    a client can forge `X-Forwarded-For` to spoof rate-limit and audit keys.

    Args:
        request: The incoming request.
        settings: Optional settings override (defaults to cached settings).

    Returns:
        The client IP string, or None when no address is available.
    """
    resolved_settings = settings or get_settings()
    if resolved_settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first_hop = forwarded.split(",")[0].strip()
            if first_hop:
                return first_hop
    return request.client.host if request.client else None
