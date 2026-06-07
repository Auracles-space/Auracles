"""Integration tests for contributor Framework draft CRUD.

These tests exercise the public `/v1/frameworks` API introduced in Phase 2
Slice 2. They intentionally verify observable behavior through FastAPI instead
of coupling to service internals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, func, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework, FrameworkVersion, License, Review
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Minimal Redis override for authenticated framework routes."""


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 2 marketplace tables exist for endpoint tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def framework_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset framework/auth state and install lightweight dependency overrides."""
    await engine.dispose()
    async def cleanup() -> None:
        """Remove marketplace rows before deleting users in test isolation."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(License))
            await session.execute(delete(ArtifactRarityAudit))
            await session.execute(delete(ArtifactPiiAudit))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()

    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    try:
        yield {}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def create_user_with_roles(
    email: str,
    roles: list[str],
    *,
    kyc_status: str = "verified",
    display_name: str | None = None,
) -> UUID:
    """Create an email-verified user with approved non-attestor roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=(
                    display_name if display_name is not None else email.split("@")[0]
                ),
                email_verified=True,
                kyc_status=kyc_status,
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


def valid_framework_payload() -> dict[str, Any]:
    """Return a valid draft Framework creation payload."""
    return {
        "title": "Board Risk Operating System",
        "description": "A board-ready governance framework for risk operations.",
        "category": "Governance",
        "sector": "Financial Services",
        "industry": "Banking",
        "function": "Risk",
        "tags": ["risk", "board", "governance"],
        "jurisdiction": "US",
        "complexity": 3,
        "org_size": "mid_market",
        "lifecycle_stage": "scale",
        "pricing": {
            "price": "499.00",
            "currency": "USD",
            "license_types": ["single_user", "team"],
            "commercial_rights": "Internal commercial use allowed.",
            "usage_restrictions": "No resale.",
        },
    }


async def test_verified_contributor_can_create_draft_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Verified Contributors can create Framework drafts."""
    contributor_id = await create_user_with_roles(
        "creator@auracles.space",
        ["contributor"],
    )

    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Board Risk Operating System"
    assert body["status"] == "draft"
    assert body["version"] == "1.0.0"
    assert body["contributor_id"] == str(contributor_id)
    assert body["pricing"]["price"] == "499.00"
    assert body["pricing"]["license_types"] == ["single_user", "team"]


@pytest.mark.parametrize("kyc_status", ["unverified", "pending"])
async def test_kyc_incomplete_contributor_cannot_create_framework(
    kyc_status: str,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Unverified and pending KYC Contributors are blocked from draft create."""
    contributor_id = await create_user_with_roles(
        f"{kyc_status}@auracles.space",
        ["contributor"],
        kyc_status=kyc_status,
    )

    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "kyc_required",
        "onboarding_url": "/settings/onboarding",
    }


async def test_non_contributor_cannot_create_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Authenticated users without Contributor role cannot create Frameworks."""
    operator_id = await create_user_with_roles(
        "operator-create@auracles.space",
        ["operator"],
    )

    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "role_required",
        "onboarding_url": "/settings/onboarding",
    }


@pytest.mark.parametrize(
    ("pricing_patch", "expected_field"),
    [
        ({"price": "0.00"}, "price"),
        ({"license_types": []}, "license_types"),
    ],
)
async def test_framework_create_validates_pricing_payload(
    pricing_patch: dict[str, Any],
    expected_field: str,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Invalid price and empty license type selections are rejected with 422."""
    contributor_id = await create_user_with_roles(
        "invalid-pricing@auracles.space",
        ["contributor"],
    )
    payload = valid_framework_payload()
    payload["pricing"] = {**payload["pricing"], **pricing_patch}

    response = await client.post(
        "/v1/frameworks",
        json=payload,
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 422
    assert expected_field in str(response.json()["detail"])


async def test_contributor_can_view_list_update_and_delete_draft_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors can manage their own draft Framework metadata."""
    contributor_id = await create_user_with_roles(
        "draft-owner@auracles.space",
        ["contributor"],
    )
    headers = auth_headers(contributor_id, ["contributor"])
    created = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=headers,
    )
    framework_id = created.json()["id"]

    fetched = await client.get(f"/v1/frameworks/{framework_id}", headers=headers)
    updated = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={
            "title": "Board Risk Operating System v2",
            "tags": ["risk", "controls"],
            "pricing": {
                "price": "699.00",
                "currency": "usd",
                "license_types": ["enterprise"],
            },
        },
        headers=headers,
    )
    listed = await client.get("/v1/frameworks", headers=headers)
    deleted = await client.delete(f"/v1/frameworks/{framework_id}", headers=headers)
    after_delete = await client.get(f"/v1/frameworks/{framework_id}", headers=headers)

    assert fetched.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["title"] == "Board Risk Operating System v2"
    assert updated.json()["tags"] == ["risk", "controls"]
    assert updated.json()["pricing"]["price"] == "699.00"
    assert updated.json()["pricing"]["currency"] == "USD"
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == framework_id
    assert deleted.status_code == 204
    assert after_delete.status_code == 404


async def test_unauthenticated_create_returns_401_and_creates_no_draft(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Visitors who click Create Framework are sent to auth with no draft write."""
    response = await client.post("/v1/frameworks", json=valid_framework_payload())

    async with async_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Framework))

    assert response.status_code == 401
    assert count == 0


async def test_blank_profile_contributor_is_routed_to_onboarding(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors with incomplete profile data cannot create Frameworks."""
    contributor_id = await create_user_with_roles(
        "blank-profile@auracles.space",
        ["contributor"],
        display_name="",
    )

    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "profile_required",
        "onboarding_url": "/settings/onboarding",
    }


async def test_contributor_cannot_read_or_mutate_another_contributors_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributor endpoints are scoped to the owning Contributor."""
    owner_id = await create_user_with_roles("owner@auracles.space", ["contributor"])
    other_id = await create_user_with_roles("other@auracles.space", ["contributor"])
    created = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(owner_id, ["contributor"]),
    )
    framework_id = created.json()["id"]
    other_headers = auth_headers(other_id, ["contributor"])

    fetched = await client.get(f"/v1/frameworks/{framework_id}", headers=other_headers)
    updated = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={"title": "Stolen draft"},
        headers=other_headers,
    )
    deleted = await client.delete(
        f"/v1/frameworks/{framework_id}",
        headers=other_headers,
    )

    assert fetched.status_code == 404
    assert updated.status_code == 404
    assert deleted.status_code == 404


@pytest.mark.parametrize("framework_status", ["submitted", "published"])
async def test_non_draft_framework_cannot_be_updated_or_deleted(
    framework_status: str,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Submitted and published Frameworks are locked from draft mutations."""
    contributor_id = await create_user_with_roles(
        f"{framework_status}-owner@auracles.space",
        ["contributor"],
    )
    headers = auth_headers(contributor_id, ["contributor"])
    created = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=headers,
    )
    framework_id = created.json()["id"]
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = framework_status
        await session.commit()

    updated = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={"title": "Locked"},
        headers=headers,
    )
    deleted = await client.delete(f"/v1/frameworks/{framework_id}", headers=headers)

    assert updated.status_code == 409
    assert deleted.status_code == 409
