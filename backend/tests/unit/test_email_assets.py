"""Email templates: where assets load from versus where actions link to.

These are different questions with different answers. Action links carry
tokens and must point at the application origin — even one that is not yet
serving, since the token is minted for it. Static assets (the logo) only need
*some* host that exists, and in environments whose frontend is not deployed
yet, that host is the apex waitlist site. Staging's first real email
(2026-09-02) rendered with a broken logo for exactly this reason.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.integrations import resend as resend_integration


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Setting env vars must be visible through the cached settings object."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_logo_uses_asset_base_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EMAIL_ASSET_BASE_URL redirects images without touching action links.

    Staging sets this to the live apex so email logos render while the
    staging frontend does not exist yet; the verification link must keep
    pointing at the staging origin regardless.
    """
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://staging.auracles.space")
    monkeypatch.setenv("EMAIL_ASSET_BASE_URL", "https://auracles.space")

    html = resend_integration._render_email_html(
        title="Verify",
        content_html="<p>hi</p>",
        action_url="https://staging.auracles.space/verify-email?token=t",
        action_text="Verify",
    )

    assert "https://auracles.space/images/logo-text-black.png" in html
    assert "https://staging.auracles.space/verify-email?token=t" in html


def test_logo_falls_back_to_frontend_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the override, assets come from the frontend origin as before."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://auracles.space")
    monkeypatch.delenv("EMAIL_ASSET_BASE_URL", raising=False)

    html = resend_integration._render_email_html(
        title="Verify",
        content_html="<p>hi</p>",
    )

    assert "https://auracles.space/images/logo-text-black.png" in html
