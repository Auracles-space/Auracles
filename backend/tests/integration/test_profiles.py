"""Integration tests for the Auracles Profile module.

Covers the public, all-roles profile page (the LinkedIn-style canonical
identity surface). Slice 1: public read of curated identity plus role and
KYC badges, with private account fields never exposed.

Maps to: FR-SET-001/002 (public profile identity).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure all tables exist before the profile endpoint tests run."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def profile_test_context() -> AsyncIterator[None]:
    """Reset profile-related rows around each test for isolation."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in dependency order so tests stay isolated."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def create_user(
    email: str,
    roles: list[str],
    *,
    display_name: str | None = None,
    bio: str | None = None,
    location: str | None = None,
    website: str | None = None,
    kyc_status: str = "verified",
    suspended: bool = False,
    deactivated: bool = False,
) -> UUID:
    """Create an email-verified test user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=display_name or email.split("@")[0],
                email_verified=True,
                kyc_status=kyc_status,
                bio=bio,
                location=location,
                website=website,
                suspended_at=datetime.now(UTC) if suspended else None,
                deactivated_at=datetime.now(UTC) if deactivated else None,
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_public_profile_returns_curated_identity(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Public profile read returns curated identity, role + KYC badges.

    Private account fields (email, kyc status internals, security) must never
    appear in the public payload.
    """
    user_id = await create_user(
        "profile-public@auracles.space",
        ["contributor"],
        display_name="Ada Public",
        bio="Risk frameworks for fintech.",
        location="Lagos, NG",
        website="https://ada.example",
    )

    response = await client.get(f"/v1/profiles/{user_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["display_name"] == "Ada Public"
    assert body["bio"] == "Risk frameworks for fintech."
    assert body["location"] == "Lagos, NG"
    assert body["website"] == "https://ada.example"
    assert body["roles"] == ["contributor"]
    assert body["kyc_verified"] is True
    assert body["is_deactivated"] is False
    # Private fields never exposed on a public profile.
    assert "email" not in body
    assert "kyc_status" not in body
    assert "totp_secret" not in body
    assert "password_hash" not in body


async def test_public_profile_for_unknown_user_returns_404(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A profile request for a non-existent user id returns 404."""
    response = await client.get(f"/v1/profiles/{uuid4()}")

    assert response.status_code == 404


async def test_suspended_account_returns_limited_profile_not_404(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A suspended user's profile is limited, not removed.

    Safe identity (name, roles) stays visible, but discretionary content
    (bio, location, website) is withheld and the profile is flagged limited.
    Suspension is a moderation state, not a 404.
    """
    user_id = await create_user(
        "profile-suspended@auracles.space",
        ["contributor"],
        display_name="Suspended User",
        bio="Should be hidden.",
        location="Hidden City",
        website="https://hidden.example",
        suspended=True,
    )

    response = await client.get(f"/v1/profiles/{user_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["display_name"] == "Suspended User"
    assert body["roles"] == ["contributor"]
    assert body["is_limited"] is True
    # Discretionary content withheld while limited.
    assert body["bio"] is None
    assert body["location"] is None
    assert body["website"] is None


async def test_me_returns_own_profile(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """The authenticated owner reads their own profile via /profiles/me."""
    user_id = await create_user(
        "profile-me@auracles.space",
        ["operator", "contributor"],
        display_name="Owner Self",
        bio="My own bio.",
    )

    response = await client.get(
        "/v1/profiles/me",
        headers=auth_headers(user_id, ["operator", "contributor"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["display_name"] == "Owner Self"
    assert body["bio"] == "My own bio."
    assert sorted(body["roles"]) == ["contributor", "operator"]


async def test_me_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Reading /profiles/me without a token is rejected with 401."""
    response = await client.get("/v1/profiles/me")

    assert response.status_code == 401
