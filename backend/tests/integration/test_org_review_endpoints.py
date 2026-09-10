"""Integration tests for organization-authored Framework review endpoints.

Task 8 adds an org-scoped review write surface that keeps the public review
identity on the organization while retaining the authoring member internally.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework, License, Review
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.shared.models.audit_log import AuditLog
from tests.conftest import verify_org_kyb
from tests.integration.test_financials_payment_methods import FakeRedis

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org review endpoint tests."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def org_review_context() -> AsyncIterator[None]:
    """Reset org review rows around each endpoint test."""
    fake_redis = FakeRedis()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete review-linked rows in FK-safe order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(License))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> UUID:
    """Create one verified user and return its id."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            return user.id


def _auth_headers(user_id: UUID) -> dict[str, str]:
    """Return bearer auth headers for one user."""
    token = create_access_token(user_id=user_id, roles=[])
    return {"Authorization": f"Bearer {token}"}


async def _create_org(
    client: AsyncClient,
    owner_id: UUID,
    prefix: str,
) -> dict[str, str]:
    """Create one organization through the API."""
    response = await client.post(
        "/v1/orgs",
        json={"slug": f"{prefix}-{uuid4().hex[:6]}", "name": prefix, "country": "US"},
        headers=_auth_headers(owner_id),
    )
    assert response.status_code == 201
    body = response.json()
    # An unverified org is a shell; tests want a usable one.
    await verify_org_kyb(({"id": body["id"], "slug": body["slug"]})["id"])
    return {"id": body["id"], "slug": body["slug"]}


async def _add_member(org_id: UUID, user_id: UUID, *, role: str = "member") -> UUID:
    """Insert one org membership row directly and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return member.id


async def _activate_operator_capability(
    client: AsyncClient,
    *,
    org_id: str,
    owner_id: UUID,
) -> None:
    """Activate the operator capability through the org route."""
    await verify_org_kyb(org_id)
    response = await client.post(
        f"/v1/orgs/{org_id}/operator-capability/activate",
        headers=_auth_headers(owner_id),
    )
    assert response.status_code == 200


async def _create_framework(contributor_id: UUID) -> UUID:
    """Create a published Framework available for review."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                contributor_org_id=None,
                title="Org Endpoint Review Framework",
                description="A framework row for org endpoint review tests.",
                version="1.0.0",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["org-review"],
                tags_text="org-review",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("299.00"),
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            return framework.id


async def _grant_org_license(framework_id: UUID, org_id: UUID) -> None:
    """Grant one org-owned License to satisfy the review precondition."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                License(
                    framework_id=framework_id,
                    operator_id=None,
                    licensee_org_id=org_id,
                    license_type="team",
                    status="active",
                    version_at_grant="1.0.0",
                )
            )


async def test_org_admin_can_create_framework_review(
    client: AsyncClient,
    migrated_database: None,
    org_review_context: None,
) -> None:
    """An org admin can write one public review under org identity."""
    del migrated_database, org_review_context
    contributor_id = await _create_user("org-review-endpoint-contributor")
    owner_id = await _create_user("org-review-endpoint-owner")
    org = await _create_org(client, owner_id, "review-endpoint-org")
    await _activate_operator_capability(client, org_id=org["id"], owner_id=owner_id)
    framework_id = await _create_framework(contributor_id)
    await _grant_org_license(framework_id, UUID(org["id"]))

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/review",
        json={"score": 5, "body": "Strong organizational playbook."},
        headers=_auth_headers(owner_id),
    )

    async with async_session_factory() as session:
        review = await session.scalar(
            select(Review).where(Review.framework_id == framework_id)
        )

    assert response.status_code == 201
    body = response.json()
    assert body["operator_id"] is None
    assert body["reviewer_org_id"] == org["id"]
    assert "reviewing_member_id" not in body
    assert review is not None
    assert review.reviewer_org_id == UUID(org["id"])


async def test_org_review_route_enforces_auth_scope_and_uniqueness(
    client: AsyncClient,
    migrated_database: None,
    org_review_context: None,
) -> None:
    """Org review write enforces auth, admin scope, active license, and uniqueness."""
    del migrated_database, org_review_context
    contributor_id = await _create_user("org-review-errors-contributor")
    owner_id = await _create_user("org-review-errors-owner")
    member_id = await _create_user("org-review-errors-member")
    outsider_id = await _create_user("org-review-errors-outsider")
    org = await _create_org(client, owner_id, "review-errors-org")
    await _add_member(UUID(org["id"]), member_id, role="member")
    await _activate_operator_capability(client, org_id=org["id"], owner_id=owner_id)
    licensed_framework_id = await _create_framework(contributor_id)
    unlicensed_framework_id = await _create_framework(contributor_id)
    await _grant_org_license(licensed_framework_id, UUID(org["id"]))

    unauthenticated = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{licensed_framework_id}/review",
        json={"score": 5, "body": "Blocked anonymously."},
    )
    member_forbidden = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{licensed_framework_id}/review",
        json={"score": 5, "body": "Blocked member."},
        headers=_auth_headers(member_id),
    )
    outsider_forbidden = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{licensed_framework_id}/review",
        json={"score": 5, "body": "Blocked outsider."},
        headers=_auth_headers(outsider_id),
    )
    no_license = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{unlicensed_framework_id}/review",
        json={"score": 4, "body": "No org license."},
        headers=_auth_headers(owner_id),
    )
    first = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{licensed_framework_id}/review",
        json={"score": 5, "body": "First org review."},
        headers=_auth_headers(owner_id),
    )
    duplicate = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{licensed_framework_id}/review",
        json={"score": 3, "body": "Duplicate org review."},
        headers=_auth_headers(owner_id),
    )

    assert unauthenticated.status_code == 401
    assert member_forbidden.status_code == 403
    assert outsider_forbidden.status_code == 403
    assert no_license.status_code == 403
    assert first.status_code == 201
    assert duplicate.status_code == 409
