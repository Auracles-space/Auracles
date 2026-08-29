"""Client network metadata helpers.

Behind a managed edge (an AWS ALB) the TCP peer is the load balancer, so
`request.client.host` is the proxy address for every request. Rate limiting and
audit logging need the real client address, which the trusted proxy supplies in
`X-Forwarded-For`. Parsing that header is gated on an explicit setting and
defaults off, because without a trusted edge in front the header is attacker
controlled outright.
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings, get_settings


def client_ip(request: Request, settings: Settings | None = None) -> str | None:
    """Return the originating client IP, honouring a trusted proxy header.

    When `TRUST_PROXY_HEADERS` is enabled the **right-most** `X-Forwarded-For`
    entry is used, because load balancers append the peer they observed instead
    of replacing the header. Everything to the left of that final entry was
    supplied by the caller and is forgeable: trusting the left-most value would
    let anyone rotate a fake address per request and walk through every per-IP
    auth rate limit. Without the setting the direct TCP peer is returned.

    This assumes exactly one trusted hop (ALB). Putting a CDN in front adds a
    hop, and the real client then sits one position further left — revisit this
    function rather than the edge config if that changes.

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
            trusted_hop = forwarded.split(",")[-1].strip()
            if trusted_hop:
                return trusted_hop
    return request.client.host if request.client else None
