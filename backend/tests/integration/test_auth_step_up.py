"""Integration tests for the step-up 2FA session endpoints.

A step-up session is a short Redis window opened by one TOTP (or backup code)
verification. Sensitive endpoints require an active window instead of a
per-request ``totp_code``. See
``docs/superpowers/specs/2026-09-13-step-up-and-admin-console-design.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pyotp
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.auth.service import step_up_key
from app.shared.models.audit_log import AuditLog
from tests.integration import test_auth_totp as totp_fixtures
from tests.integration.test_auth_totp import (
    auth_headers,
    create_verified_user,
    secret_from_uri,
    setup_and_enable_totp,
)

migrated_database = totp_fixtures.migrated_database
totp_test_context = totp_fixtures.totp_test_context


async def test_step_up_is_inactive_before_verification(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """A user with 2FA enabled but no verification this window has no step-up."""
    user_id = await create_verified_user("stepup-none@auracles.space", "CorrectHorse9")
    await setup_and_enable_totp(client, user_id)

    response = await client.get("/v1/auth/step-up", headers=auth_headers(user_id))

    assert response.status_code == 200
    assert response.json() == {"active": False, "verified_until": None}


async def test_valid_code_opens_a_step_up_window(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """A current TOTP code opens a window whose expiry is reported back and audited."""
    user_id = await create_verified_user("stepup-ok@auracles.space", "CorrectHorse9")
    setup = await setup_and_enable_totp(client, user_id)
    secret = secret_from_uri(setup["provisioning_uri"])
    # Enabling 2FA already consumed the current step; move one step ahead.
    code = pyotp.TOTP(secret).at(int(datetime.now(UTC).timestamp()) + 30)

    response = await client.post(
        "/v1/auth/step-up",
        json={"code": code},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200
    verified_until = datetime.fromisoformat(response.json()["verified_until"])
    assert verified_until > datetime.now(UTC)

    status = await client.get("/v1/auth/step-up", headers=auth_headers(user_id))
    assert status.json()["active"] is True
    assert totp_test_context["redis"].ttls[step_up_key(user_id)] == 600

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == "step_up_verified",
            )
        )
    assert audit is not None


async def test_wrong_code_is_rejected_and_opens_nothing(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """An invalid code returns 422 and leaves the window closed."""
    user_id = await create_verified_user("stepup-bad@auracles.space", "CorrectHorse9")
    await setup_and_enable_totp(client, user_id)

    response = await client.post(
        "/v1/auth/step-up",
        json={"code": "000000"},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 422
    status = await client.get("/v1/auth/step-up", headers=auth_headers(user_id))
    assert status.json()["active"] is False


async def test_backup_code_opens_a_step_up_window(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """A backup code (``xxxx-xxxx``) is accepted, so a lost phone is not a lockout."""
    user_id = await create_verified_user(
        "stepup-backup@auracles.space", "CorrectHorse9"
    )
    setup = await setup_and_enable_totp(client, user_id)

    response = await client.post(
        "/v1/auth/step-up",
        json={"code": setup["backup_codes"][0]},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200


async def test_step_up_requires_two_factor_enabled(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """Without 2FA enrolled the endpoint points the user at security settings."""
    user_id = await create_verified_user("stepup-no2fa@auracles.space", "CorrectHorse9")

    response = await client.post(
        "/v1/auth/step-up",
        json={"code": "123456"},
        headers=auth_headers(user_id),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "totp_setup_required"


async def test_logout_closes_the_step_up_window(
    client: AsyncClient,
    migrated_database: None,
    totp_test_context: dict[str, Any],
) -> None:
    """Logging out revokes the step-up so a reused browser cannot inherit it."""
    user_id = await create_verified_user(
        "stepup-logout@auracles.space", "CorrectHorse9"
    )
    setup = await setup_and_enable_totp(client, user_id)
    secret = secret_from_uri(setup["provisioning_uri"])
    code = pyotp.TOTP(secret).at(int(datetime.now(UTC).timestamp()) + 30)
    opened = await client.post(
        "/v1/auth/step-up", json={"code": code}, headers=auth_headers(user_id)
    )
    assert opened.status_code == 200

    logged_out = await client.post("/v1/auth/logout", headers=auth_headers(user_id))
    assert logged_out.status_code in (200, 204)

    status = await client.get("/v1/auth/step-up", headers=auth_headers(user_id))
    assert status.json()["active"] is False
