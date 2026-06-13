"""Unit tests for trusted-proxy client IP resolution."""

from __future__ import annotations

from app.core.config import Settings
from app.core.network import client_ip


class _FakeClient:
    """Minimal stand-in for Starlette's request.client."""

    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Minimal stand-in exposing only headers and client for client_ip."""

    def __init__(self, *, headers: dict[str, str], client_host: str | None) -> None:
        self.headers = headers
        self.client = _FakeClient(client_host) if client_host is not None else None


def _settings(*, trust: bool) -> Settings:
    """Build settings with proxy trust toggled."""
    return Settings(TRUST_PROXY_HEADERS=trust)


def test_client_ip_ignores_forwarded_header_when_untrusted() -> None:
    """A forged X-Forwarded-For must not override the peer when trust is off."""
    request = _FakeRequest(
        headers={"x-forwarded-for": "1.2.3.4"},
        client_host="10.0.0.1",
    )
    assert client_ip(request, _settings(trust=False)) == "10.0.0.1"


def test_client_ip_uses_first_forwarded_hop_when_trusted() -> None:
    """The left-most forwarded hop is the client when a trusted proxy is set."""
    request = _FakeRequest(
        headers={"x-forwarded-for": "1.2.3.4, 10.0.0.2, 10.0.0.1"},
        client_host="10.0.0.1",
    )
    assert client_ip(request, _settings(trust=True)) == "1.2.3.4"


def test_client_ip_falls_back_to_peer_without_forwarded_header() -> None:
    """With trust on but no header, the direct peer address is returned."""
    request = _FakeRequest(headers={}, client_host="10.0.0.1")
    assert client_ip(request, _settings(trust=True)) == "10.0.0.1"


def test_client_ip_returns_none_when_no_peer() -> None:
    """A missing client and no header yields None rather than raising."""
    request = _FakeRequest(headers={}, client_host=None)
    assert client_ip(request, _settings(trust=True)) is None
