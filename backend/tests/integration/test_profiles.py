"""Integration tests for the Auracles Profile module.

Covers the public, all-roles profile page (the LinkedIn-style canonical
identity surface). Slice 1: public read of curated identity plus role and
KYC badges, with private account fields never exposed.

Maps to: FR-SET-001/002 (public profile identity).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation.models import Attestation, Credential
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework, Review
from app.shared.models.audit_log import AuditLog


class FakeAvatarStorage:
    """S3 storage double for avatar presigned upload and confirm checks."""

    def __init__(self) -> None:
        """Create empty fake object state."""
        self.existing_keys: set[str] = set()

    def presigned_post(
        self,
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Return a deterministic presigned POST payload."""
        del bucket, mime_type, max_size, expires_in
        return {"fields": {"key": key}, "url": "https://s3.test/avatar-upload"}

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return whether the fake S3 object exists."""
        del bucket
        return key in self.existing_keys

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a deterministic signed read URL.

        Profile images live in a private bucket, so every serialized avatar or
        banner is signed on the way out rather than derived from the key.
        """
        del bucket, expires_in
        return f"https://s3.test/signed/{key}"


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
            await session.execute(delete(Review))
            await session.execute(delete(Attestation))
            await session.execute(delete(Framework))
            await session.execute(delete(Credential))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


@pytest.fixture
def avatar_storage(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeAvatarStorage]:
    """Swap the live S3 storage for an in-memory avatar double."""
    from app.integrations import s3

    fake = FakeAvatarStorage()
    monkeypatch.setattr(s3, "storage", fake)
    yield fake


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


async def test_owner_updates_editable_profile_fields(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """The owner edits headline/bio/location/website via PATCH /profiles/me.

    The update response and a subsequent public read both reflect the change.
    """
    user_id = await create_user(
        "profile-edit@auracles.space",
        ["contributor"],
        display_name="Editor User",
    )

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "headline": "Compliance frameworks for fintech",
            "bio": "Updated bio.",
            "location": "Abuja, NG",
            "website": "https://editor.example",
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["headline"] == "Compliance frameworks for fintech"
    assert body["bio"] == "Updated bio."
    assert body["location"] == "Abuja, NG"
    assert body["website"] == "https://editor.example"

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["headline"] == "Compliance frameworks for fintech"


async def test_owner_sets_specializations_shown_on_public_profile(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Specializations set via PATCH appear on the public profile."""
    user_id = await create_user("profile-spec@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={"specializations": ["Fintech Risk", "AML Compliance"]},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["specializations"] == ["Fintech Risk", "AML Compliance"]

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["specializations"] == ["Fintech Risk", "AML Compliance"]


async def test_specializations_patch_replaces_whole_list(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Setting specializations replaces the prior list (not append)."""
    user_id = await create_user("profile-spec2@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    await client.patch(
        "/v1/profiles/me",
        json={"specializations": ["One", "Two"]},
        headers=headers,
    )
    response = await client.patch(
        "/v1/profiles/me",
        json={"specializations": ["Three"]},
        headers=headers,
    )

    assert response.json()["specializations"] == ["Three"]


async def test_specializations_omitted_leaves_them_untouched(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A PATCH without specializations does not clear existing ones."""
    user_id = await create_user("profile-spec3@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    await client.patch(
        "/v1/profiles/me",
        json={"specializations": ["Kept"]},
        headers=headers,
    )
    response = await client.patch(
        "/v1/profiles/me",
        json={"headline": "Unrelated change"},
        headers=headers,
    )

    assert response.json()["specializations"] == ["Kept"]


async def test_specializations_empty_list_clears_them(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """An explicit empty list clears specializations."""
    user_id = await create_user("profile-spec4@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    await client.patch(
        "/v1/profiles/me",
        json={"specializations": ["Gone"]},
        headers=headers,
    )
    response = await client.patch(
        "/v1/profiles/me",
        json={"specializations": []},
        headers=headers,
    )

    assert response.json()["specializations"] == []


async def test_specializations_are_trimmed_and_deduplicated(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Whitespace is trimmed, blanks dropped, and duplicates removed in order."""
    user_id = await create_user("profile-spec5@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={"specializations": ["  Risk  ", "Risk", "", "AML"]},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.json()["specializations"] == ["Risk", "AML"]


async def test_too_many_specializations_rejected(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """More than the cap of specializations is rejected with 422."""
    user_id = await create_user("profile-spec6@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={"specializations": [f"Skill {i}" for i in range(25)]},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_suspended_profile_withholds_specializations(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A suspended account's specializations are withheld from the public read."""
    user_id = await create_user("profile-spec7@auracles.space", ["contributor"])
    await client.patch(
        "/v1/profiles/me",
        json={"specializations": ["Hidden Skill"]},
        headers=auth_headers(user_id, ["contributor"]),
    )
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.suspended_at = datetime.now(UTC)
        await session.commit()

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["specializations"] == []


async def _add_credential(
    user_id: UUID,
    *,
    title: str,
    verification_status: str,
) -> None:
    """Insert a credential row for a user with the given verification status."""
    from datetime import date

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Credential(
                    user_id=user_id,
                    title=title,
                    issuer="Issuer Co",
                    issued_date=date(2024, 1, 1),
                    verification_status=verification_status,
                )
            )


async def test_public_profile_includes_only_verified_credentials(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """The public profile lists verified credentials and hides unverified ones."""
    user_id = await create_user("profile-cred@auracles.space", ["contributor"])
    await _add_credential(user_id, title="CFA", verification_status="verified")
    await _add_credential(user_id, title="Pending One", verification_status="pending")

    public = await client.get(f"/v1/profiles/{user_id}")

    assert public.status_code == 200
    titles = [c["title"] for c in public.json()["verified_credentials"]]
    assert titles == ["CFA"]


async def test_suspended_profile_withholds_credentials(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A suspended account's credentials are withheld from the public read."""
    user_id = await create_user("profile-cred2@auracles.space", ["contributor"])
    await _add_credential(user_id, title="Hidden CFA", verification_status="verified")
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.suspended_at = datetime.now(UTC)
        await session.commit()

    public = await client.get(f"/v1/profiles/{user_id}")

    assert public.json()["verified_credentials"] == []


async def test_owner_sets_portfolio_links_shown_on_public_profile(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Portfolio links set via PATCH appear on the public profile."""
    user_id = await create_user("profile-links@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "links": [
                {"label": "GitHub", "url": "https://github.com/ada"},
                {"label": "Site", "url": "https://ada.example"},
            ]
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 200
    links = response.json()["links"]
    assert links == [
        {"label": "GitHub", "url": "https://github.com/ada"},
        {"label": "Site", "url": "https://ada.example"},
    ]

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["links"] == links


async def test_links_patch_replaces_whole_list(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Setting links replaces the prior list (not append)."""
    user_id = await create_user("profile-links2@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    await client.patch(
        "/v1/profiles/me",
        json={"links": [{"label": "Old", "url": "https://old.example"}]},
        headers=headers,
    )
    response = await client.patch(
        "/v1/profiles/me",
        json={"links": [{"label": "New", "url": "https://new.example"}]},
        headers=headers,
    )

    assert response.json()["links"] == [{"label": "New", "url": "https://new.example"}]


async def test_links_omitted_leaves_them_untouched(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A PATCH without links does not clear existing ones."""
    user_id = await create_user("profile-links3@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    await client.patch(
        "/v1/profiles/me",
        json={"links": [{"label": "Keep", "url": "https://keep.example"}]},
        headers=headers,
    )
    response = await client.patch(
        "/v1/profiles/me",
        json={"headline": "Unrelated"},
        headers=headers,
    )

    assert response.json()["links"] == [
        {"label": "Keep", "url": "https://keep.example"}
    ]


async def test_links_reject_unsafe_url_scheme(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A link with a non-http(s) URL is rejected with 422."""
    user_id = await create_user("profile-links4@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={"links": [{"label": "Bad", "url": "javascript:alert(1)"}]},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_too_many_links_rejected(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """More than the cap of links is rejected with 422."""
    user_id = await create_user("profile-links5@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "links": [
                {"label": f"L{i}", "url": f"https://x{i}.example"} for i in range(15)
            ]
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_suspended_profile_withholds_links(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A suspended account's links are withheld from the public read."""
    user_id = await create_user("profile-links6@auracles.space", ["contributor"])
    await client.patch(
        "/v1/profiles/me",
        json={"links": [{"label": "Hidden", "url": "https://hidden.example"}]},
        headers=auth_headers(user_id, ["contributor"]),
    )
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.suspended_at = datetime.now(UTC)
        await session.commit()

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["links"] == []


async def test_owner_sets_social_links_shown_on_public_profile(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Typed social links set via PATCH appear on the public profile."""
    user_id = await create_user("profile-social@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "social_links": [
                {"platform": "x", "url": "https://x.com/ada"},
                {"platform": "github", "url": "https://github.com/ada"},
            ]
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 200
    social_links = response.json()["social_links"]
    assert social_links == [
        {"platform": "x", "url": "https://x.com/ada"},
        {"platform": "github", "url": "https://github.com/ada"},
    ]

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["social_links"] == social_links


async def test_social_links_patch_replaces_whole_list(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Setting social links replaces the prior list (not append)."""
    user_id = await create_user("profile-social2@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    await client.patch(
        "/v1/profiles/me",
        json={"social_links": [{"platform": "x", "url": "https://x.com/old"}]},
        headers=headers,
    )
    response = await client.patch(
        "/v1/profiles/me",
        json={
            "social_links": [
                {"platform": "linkedin", "url": "https://linkedin.com/in/new"}
            ]
        },
        headers=headers,
    )

    assert response.json()["social_links"] == [
        {"platform": "linkedin", "url": "https://linkedin.com/in/new"}
    ]


async def test_social_links_omitted_leaves_them_untouched(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A PATCH without social_links does not clear existing ones."""
    user_id = await create_user("profile-social3@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    await client.patch(
        "/v1/profiles/me",
        json={
            "social_links": [{"platform": "github", "url": "https://github.com/keep"}]
        },
        headers=headers,
    )
    response = await client.patch(
        "/v1/profiles/me",
        json={"headline": "Unrelated"},
        headers=headers,
    )

    assert response.json()["social_links"] == [
        {"platform": "github", "url": "https://github.com/keep"}
    ]


async def test_social_links_reject_unsafe_url_scheme(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A social link with a non-http(s) URL is rejected with 422."""
    user_id = await create_user("profile-social4@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={"social_links": [{"platform": "x", "url": "javascript:alert(1)"}]},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_social_links_reject_unknown_platform(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A social link for a platform outside the allow-list is rejected with 422."""
    user_id = await create_user("profile-social5@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "social_links": [{"platform": "myspace", "url": "https://myspace.com/ada"}]
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_social_links_reject_duplicate_platform(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Two entries for the same platform are rejected with 422."""
    user_id = await create_user("profile-social6@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "social_links": [
                {"platform": "x", "url": "https://x.com/one"},
                {"platform": "x", "url": "https://x.com/two"},
            ]
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_suspended_profile_withholds_social_links(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A suspended account's social links are withheld from the public read."""
    user_id = await create_user("profile-social7@auracles.space", ["contributor"])
    await client.patch(
        "/v1/profiles/me",
        json={"social_links": [{"platform": "x", "url": "https://x.com/hidden"}]},
        headers=auth_headers(user_id, ["contributor"]),
    )
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.suspended_at = datetime.now(UTC)
        await session.commit()

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["social_links"] == []


async def test_profile_stats_zero_for_fresh_user(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A user with no marketplace activity reports zeroed stats."""
    user_id = await create_user("profile-stats0@auracles.space", ["contributor"])

    stats = (await client.get(f"/v1/profiles/{user_id}")).json()["stats"]

    assert stats["frameworks_published"] == 0
    assert stats["reviews_received"] == 0
    assert stats["average_rating"] is None
    # Attestation is credited to the attestor org, not advertised on user
    # profiles (Task 9); the field is gone from ProfileStats.
    assert "attestations_performed" not in stats


async def test_profile_stats_counts_published_frameworks_only(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Stats count published Frameworks; attestation is not advertised here."""
    from decimal import Decimal

    user_id = await create_user("profile-stats@auracles.space", ["contributor"])
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Framework(
                    contributor_id=user_id,
                    title="Published One",
                    description="d",
                    category="security",
                    price=Decimal("10"),
                    status="published",
                    license_types=["single_user"],
                )
            )
            session.add(
                Framework(
                    contributor_id=user_id,
                    title="Draft One",
                    description="d",
                    category="security",
                    price=Decimal("10"),
                    status="draft",
                    license_types=["single_user"],
                )
            )

    stats = (await client.get(f"/v1/profiles/{user_id}")).json()["stats"]

    assert stats["frameworks_published"] == 1
    assert "attestations_performed" not in stats


async def test_suspended_profile_withholds_stats(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A suspended account's stats are zeroed in the public read."""
    from decimal import Decimal

    user_id = await create_user("profile-stats2@auracles.space", ["contributor"])
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Framework(
                    contributor_id=user_id,
                    title="Pub",
                    description="d",
                    category="security",
                    price=Decimal("10"),
                    status="published",
                    license_types=["single_user"],
                )
            )
        user = await session.get(User, user_id)
        assert user is not None
        user.suspended_at = datetime.now(UTC)
        await session.commit()

    stats = (await client.get(f"/v1/profiles/{user_id}")).json()["stats"]
    assert stats["frameworks_published"] == 0


async def test_owner_sets_featured_shown_publicly(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Featured spotlights set via PATCH appear on the public profile."""
    user_id = await create_user("profile-feat@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "featured": [
                {
                    "title": "SOC 2 Readiness Kit",
                    "description": "My flagship framework.",
                    "url": "https://auracles.space/explore/x",
                }
            ]
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["featured"][0]["title"] == "SOC 2 Readiness Kit"

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["featured"][0]["description"] == "My flagship framework."


async def test_featured_can_pin_own_published_framework(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Pinning the owner's published Framework resolves to a live card."""
    from decimal import Decimal

    user_id = await create_user("feat-pin@auracles.space", ["contributor"])
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=user_id,
                title="Flagship Kit",
                description="d",
                category="security",
                price=Decimal("10"),
                status="published",
                license_types=["single_user"],
            )
            session.add(framework)
        framework_id = framework.id

    response = await client.patch(
        "/v1/profiles/me",
        json={"featured": [{"framework_id": str(framework_id)}]},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 200
    item = response.json()["featured"][0]
    assert item["framework_id"] == str(framework_id)
    assert item["framework"] is not None
    assert item["framework"]["title"] == "Flagship Kit"


async def test_featured_rejects_pinning_unowned_framework(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Pinning a Framework that is not the owner's published one is rejected."""
    user_id = await create_user("feat-pin2@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={"featured": [{"framework_id": str(uuid4())}]},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_featured_rejects_duplicate_framework(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Pinning the same Framework in two featured items is rejected."""
    from decimal import Decimal

    user_id = await create_user("feat-dup@auracles.space", ["contributor"])
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=user_id,
                title="Dup Kit",
                description="d",
                category="security",
                price=Decimal("10"),
                status="published",
                license_types=["single_user"],
            )
            session.add(framework)
        framework_id = framework.id

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "featured": [
                {"framework_id": str(framework_id)},
                {"framework_id": str(framework_id)},
            ]
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_featured_requires_title_or_framework(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A featured item with neither title nor framework is rejected."""
    user_id = await create_user("feat-empty@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={"featured": [{"description": "orphan"}]},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_featured_rejects_unsafe_url_and_caps_count(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A featured item with an unsafe URL, or too many items, is rejected."""
    user_id = await create_user("profile-feat2@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    unsafe = await client.patch(
        "/v1/profiles/me",
        json={"featured": [{"title": "Bad", "url": "javascript:alert(1)"}]},
        headers=headers,
    )
    assert unsafe.status_code == 422

    too_many = await client.patch(
        "/v1/profiles/me",
        json={"featured": [{"title": f"F{i}"} for i in range(5)]},
        headers=headers,
    )
    assert too_many.status_code == 422


async def test_suspended_profile_withholds_featured(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A suspended account's featured spotlights are withheld publicly."""
    user_id = await create_user("profile-feat3@auracles.space", ["contributor"])
    await client.patch(
        "/v1/profiles/me",
        json={"featured": [{"title": "Hidden flagship"}]},
        headers=auth_headers(user_id, ["contributor"]),
    )
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.suspended_at = datetime.now(UTC)
        await session.commit()

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["featured"] == []


async def test_owner_sets_experience_and_education_shown_publicly(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Experience and education set via PATCH appear on the public profile."""
    user_id = await create_user("profile-cv@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "experience": [
                {
                    "title": "Lead Architect",
                    "company": "Stripe",
                    "start": "2019",
                    "end": "2023",
                    "current": False,
                    "description": "Led payments platform.",
                }
            ],
            "education": [
                {
                    "school": "MIT",
                    "degree": "BSc",
                    "field": "Computer Science",
                    "start_year": 2011,
                    "end_year": 2015,
                }
            ],
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["experience"][0]["title"] == "Lead Architect"
    assert body["education"][0]["school"] == "MIT"

    public = await client.get(f"/v1/profiles/{user_id}")
    pub = public.json()
    assert pub["experience"][0]["company"] == "Stripe"
    assert pub["education"][0]["end_year"] == 2015


async def test_experience_patch_replaces_whole_list(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Setting experience replaces the prior list (not append)."""
    user_id = await create_user("profile-cv2@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    await client.patch(
        "/v1/profiles/me",
        json={"experience": [{"title": "Old", "company": "A"}]},
        headers=headers,
    )
    response = await client.patch(
        "/v1/profiles/me",
        json={"experience": [{"title": "New", "company": "B"}]},
        headers=headers,
    )

    body = response.json()
    assert len(body["experience"]) == 1
    assert body["experience"][0]["title"] == "New"


async def test_too_many_experience_entries_rejected(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """More than the experience cap is rejected with 422."""
    user_id = await create_user("profile-cv3@auracles.space", ["contributor"])

    response = await client.patch(
        "/v1/profiles/me",
        json={
            "experience": [{"title": f"Role {i}", "company": "Co"} for i in range(25)]
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_suspended_profile_withholds_experience_education_banner(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A suspended account's CV sections and banner are withheld publicly."""
    user_id = await create_user("profile-cv4@auracles.space", ["contributor"])
    await client.patch(
        "/v1/profiles/me",
        json={
            "experience": [{"title": "Hidden", "company": "Co"}],
            "education": [{"school": "Hidden U"}],
        },
        headers=auth_headers(user_id, ["contributor"]),
    )
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.banner_url = "https://x/banner.png"
        user.suspended_at = datetime.now(UTC)
        await session.commit()

    public = await client.get(f"/v1/profiles/{user_id}")
    body = public.json()
    assert body["experience"] == []
    assert body["education"] == []
    assert body["banner_url"] is None


async def test_banner_upload_url_and_confirm_sets_banner(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
    avatar_storage: FakeAvatarStorage,
) -> None:
    """Banner upload-url namespaces the key and confirm publishes the banner."""
    user_id = await create_user("profile-banner@auracles.space", ["contributor"])
    headers = auth_headers(user_id, ["contributor"])

    presign = await client.post(
        "/v1/profiles/me/banner/upload-url",
        json={"filename": "b.png", "mime_type": "image/png", "file_size": 80_000},
        headers=headers,
    )
    assert presign.status_code == 200
    file_key = presign.json()["file_key"]
    assert file_key.startswith(f"banners/{user_id}/")
    avatar_storage.existing_keys.add(file_key)

    confirm = await client.post(
        "/v1/profiles/me/banner/confirm",
        json={"file_key": file_key},
        headers=headers,
    )
    assert confirm.status_code == 200
    assert confirm.json()["banner_url"]

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["banner_url"] == confirm.json()["banner_url"]


async def test_banner_confirm_rejects_foreign_key(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
    avatar_storage: FakeAvatarStorage,
) -> None:
    """A user cannot confirm a banner key under another user's id."""
    owner_id = await create_user("banner-owner@auracles.space", ["contributor"])
    attacker_id = await create_user("banner-attacker@auracles.space", ["contributor"])

    foreign_key = f"banners/{owner_id}/{uuid4()}.png"
    avatar_storage.existing_keys.add(foreign_key)

    confirm = await client.post(
        "/v1/profiles/me/banner/confirm",
        json={"file_key": foreign_key},
        headers=auth_headers(attacker_id, ["contributor"]),
    )

    assert confirm.status_code == 403


async def test_profile_update_only_changes_provided_fields(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A partial PATCH leaves omitted fields untouched."""
    user_id = await create_user(
        "profile-partial@auracles.space",
        ["operator"],
        bio="Keep me.",
    )

    response = await client.patch(
        "/v1/profiles/me",
        json={"headline": "Only headline set"},
        headers=auth_headers(user_id, ["operator"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["headline"] == "Only headline set"
    assert body["bio"] == "Keep me."


async def test_profile_update_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Editing the profile without a token is rejected with 401."""
    response = await client.patch("/v1/profiles/me", json={"headline": "x"})

    assert response.status_code == 401


async def test_profile_update_rejects_unsafe_website_scheme(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """A non-http(s) website URL is rejected at the write boundary with 422."""
    user_id = await create_user(
        "profile-badurl@auracles.space",
        ["contributor"],
    )

    response = await client.patch(
        "/v1/profiles/me",
        json={"website": "javascript:alert(1)"},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 422


async def test_avatar_upload_url_returns_presigned_target(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
    avatar_storage: FakeAvatarStorage,
) -> None:
    """Requesting an avatar upload URL returns a presigned POST target.

    The object key is namespaced under the owner's id so one user can never
    overwrite another's avatar object.
    """
    user_id = await create_user("avatar-url@auracles.space", ["contributor"])

    response = await client.post(
        "/v1/profiles/me/avatar/upload-url",
        json={
            "filename": "me.png",
            "mime_type": "image/png",
            "file_size": 50_000,
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["upload_url"]
    assert body["file_key"].startswith(f"avatars/{user_id}/")
    assert body["fields"]["key"] == body["file_key"]


async def test_avatar_upload_url_rejects_non_image_mime(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
    avatar_storage: FakeAvatarStorage,
) -> None:
    """A non-image MIME type is rejected with 415."""
    user_id = await create_user("avatar-badmime@auracles.space", ["contributor"])

    response = await client.post(
        "/v1/profiles/me/avatar/upload-url",
        json={
            "filename": "doc.pdf",
            "mime_type": "application/pdf",
            "file_size": 50_000,
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 415


async def test_avatar_upload_url_rejects_oversized_file(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
    avatar_storage: FakeAvatarStorage,
) -> None:
    """An avatar larger than the size cap is rejected with 413."""
    user_id = await create_user("avatar-big@auracles.space", ["contributor"])

    response = await client.post(
        "/v1/profiles/me/avatar/upload-url",
        json={
            "filename": "huge.png",
            "mime_type": "image/png",
            "file_size": 50 * 1024 * 1024,
        },
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert response.status_code == 413


async def test_avatar_upload_url_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
) -> None:
    """Requesting an avatar upload URL without a token is rejected with 401."""
    response = await client.post(
        "/v1/profiles/me/avatar/upload-url",
        json={"filename": "me.png", "mime_type": "image/png", "file_size": 1000},
    )

    assert response.status_code == 401


async def test_avatar_confirm_sets_avatar_on_profile(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
    avatar_storage: FakeAvatarStorage,
) -> None:
    """Confirming an uploaded avatar publishes it on the public profile."""
    user_id = await create_user("avatar-confirm@auracles.space", ["contributor"])

    presign = await client.post(
        "/v1/profiles/me/avatar/upload-url",
        json={
            "filename": "me.png",
            "mime_type": "image/png",
            "file_size": 50_000,
        },
        headers=auth_headers(user_id, ["contributor"]),
    )
    file_key = presign.json()["file_key"]
    # Simulate the client completing the upload to the presigned target.
    avatar_storage.existing_keys.add(file_key)

    confirm = await client.post(
        "/v1/profiles/me/avatar/confirm",
        json={"file_key": file_key},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert confirm.status_code == 200
    assert confirm.json()["avatar_url"]

    public = await client.get(f"/v1/profiles/{user_id}")
    assert public.json()["avatar_url"] == confirm.json()["avatar_url"]


async def test_avatar_confirm_rejects_missing_object(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
    avatar_storage: FakeAvatarStorage,
) -> None:
    """Confirming before the upload completes is rejected with 409.

    Guards against persisting an avatar_url whose object does not exist, which
    would render as a broken image on every profile view.
    """
    user_id = await create_user("avatar-noobj@auracles.space", ["contributor"])

    presign = await client.post(
        "/v1/profiles/me/avatar/upload-url",
        json={
            "filename": "me.png",
            "mime_type": "image/png",
            "file_size": 50_000,
        },
        headers=auth_headers(user_id, ["contributor"]),
    )
    file_key = presign.json()["file_key"]

    confirm = await client.post(
        "/v1/profiles/me/avatar/confirm",
        json={"file_key": file_key},
        headers=auth_headers(user_id, ["contributor"]),
    )

    assert confirm.status_code == 409


async def test_avatar_confirm_rejects_foreign_key(
    client: AsyncClient,
    migrated_database: None,
    profile_test_context: None,
    avatar_storage: FakeAvatarStorage,
) -> None:
    """A user cannot confirm a key namespaced under another user's id."""
    owner_id = await create_user("avatar-owner@auracles.space", ["contributor"])
    attacker_id = await create_user("avatar-attacker@auracles.space", ["contributor"])

    foreign_key = f"avatars/{owner_id}/{uuid4()}.png"
    avatar_storage.existing_keys.add(foreign_key)

    confirm = await client.post(
        "/v1/profiles/me/avatar/confirm",
        json={"file_key": foreign_key},
        headers=auth_headers(attacker_id, ["contributor"]),
    )

    assert confirm.status_code == 403
