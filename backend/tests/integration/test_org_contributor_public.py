"""Integration tests for public org-contributor marketplace surfaces."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    Review,
)
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgContributorProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog
from tests.integration.test_explore_endpoints import (
    FakeExploreStorage,
    FakeRedis,
    auth_headers,
    create_user,
    migrated_database,
)

pytestmark = pytest.mark.asyncio
__all__ = ["migrated_database"]


@pytest.fixture
async def org_contributor_public_context() -> AsyncIterator[dict[str, Any]]:
    """Reset public org-contributor state and install fake preview dependencies."""
    from app.integrations import s3

    fake_redis = FakeRedis()
    fake_storage = FakeExploreStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK-safe order so public-surface tests stay isolated."""
        async with async_session_factory() as session:
            await session.execute(update(Framework).values(preview_artifact_id=None))
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(License))
            await session.execute(delete(ArtifactRarityAudit))
            await session.execute(delete(ArtifactPiiAudit))
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgContributorProfile))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    original_storage = s3.storage
    s3.storage = fake_storage
    try:
        yield {"redis": fake_redis, "storage": fake_storage}
    finally:
        s3.storage = original_storage
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_org_framework(
    *,
    owner_id: UUID,
    org_slug: str,
    org_name: str,
    framework_title: str,
    verification_level: int = 2,
    reputation_score: Decimal | None = Decimal("92.50"),
    capability_status: str = "active",
) -> tuple[UUID, UUID]:
    """Create one org seller, contributor profile, and published Framework."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                id=uuid4(),
                slug=org_slug,
                name=org_name,
                country="US",
                created_by=owner_id,
            )
            session.add(organization)
            await session.flush()
            member = OrgMember(
                id=uuid4(),
                org_id=organization.id,
                user_id=owner_id,
                role="owner",
            )
            session.add(member)
            await session.flush()
            session.add(
                OrgCapability(
                    org_id=organization.id,
                    capability="contributor",
                    status=capability_status,
                    activated_at=datetime.now(UTC),
                )
            )
            session.add(
                OrgContributorProfile(
                    org_id=organization.id,
                    active=True,
                    verification_level=verification_level,
                    activated_at=datetime.now(UTC),
                    reputation_score=reputation_score,
                )
            )
            framework = Framework(
                id=uuid4(),
                contributor_id=None,
                contributor_org_id=organization.id,
                authoring_member_id=member.id,
                title=framework_title,
                description=f"{framework_title} implementation playbook.",
                version="1.0.0",
                status="published",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk", "governance"],
                tags_text="risk governance",
                jurisdiction="US",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            return organization.id, framework.id


async def test_explore_catalog_resolves_org_seller_identity(
    client: AsyncClient,
    migrated_database: None,
    org_contributor_public_context: dict[str, Any],
) -> None:
    """Explore cards show org seller identity for org-owned Frameworks."""
    del migrated_database, org_contributor_public_context
    individual_id = await create_user(
        "individual-catalog@auracles.space",
        ["contributor"],
        display_name="Individual Contributor",
    )
    owner_id = await create_user(
        "org-catalog-owner@auracles.space",
        ["contributor"],
        display_name="Org Owner",
    )

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Framework(
                    id=uuid4(),
                    contributor_id=individual_id,
                    title="Individual Framework",
                    description="Individual Framework implementation playbook.",
                    version="1.0.0",
                    status="published",
                    category="framework",
                    sector="financial_services",
                    industry="fund_management",
                    business_function="risk_management",
                    tags=["risk", "governance"],
                    tags_text="risk governance",
                    jurisdiction="US",
                    complexity=3,
                    org_size="mid_market",
                    lifecycle_stage="scale",
                    price=Decimal("499.00"),
                    currency="USD",
                    license_types=["single_user"],
                    published_at=datetime.now(UTC),
                )
            )
    org_id, org_framework_id = await _create_org_framework(
        owner_id=owner_id,
        org_slug="catalog-org",
        org_name="Catalog Org",
        framework_title="Organization Framework",
        verification_level=3,
        reputation_score=Decimal("87.50"),
    )

    response = await client.get("/v1/explore/frameworks")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    by_title = {item["title"]: item for item in body["items"]}

    individual = by_title["Individual Framework"]
    assert individual["contributor_id"] == str(individual_id)
    assert individual["contributor_org_id"] is None
    assert individual["contributor_name"] == "Individual Contributor"
    assert individual["contributor_slug"] is None
    assert individual["contributor_verification_level"] is None
    assert individual["contributor_reputation_score"] is None

    org_item = by_title["Organization Framework"]
    assert org_item["id"] == str(org_framework_id)
    assert org_item["contributor_id"] is None
    assert org_item["contributor_org_id"] == str(org_id)
    assert org_item["contributor_name"] == "Catalog Org"
    assert org_item["contributor_slug"] == "catalog-org"
    assert org_item["contributor_verification_level"] == 3
    assert org_item["contributor_reputation_score"] == "87.50"


async def test_suspended_org_framework_is_hidden_but_licensed_detail_still_resolves(
    client: AsyncClient,
    migrated_database: None,
    org_contributor_public_context: dict[str, Any],
) -> None:
    """Suspended contributor org Frameworks hide from Explore but keep buyer access."""
    del migrated_database, org_contributor_public_context
    owner_id = await create_user(
        "org-hidden-owner@auracles.space",
        ["contributor"],
        display_name="Org Hidden Owner",
    )
    operator_id = await create_user("licensed-operator@auracles.space", ["operator"])
    org_id, framework_id = await _create_org_framework(
        owner_id=owner_id,
        org_slug="hidden-org",
        org_name="Hidden Org",
        framework_title="Licensed Organization Framework",
    )

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                License(
                    id=uuid4(),
                    framework_id=framework_id,
                    operator_id=operator_id,
                    license_type="single_user",
                    status="active",
                    version_at_grant="1.0.0",
                )
            )
            capability = await session.scalar(
                select(OrgCapability).where(
                    OrgCapability.org_id == org_id,
                    OrgCapability.capability == "contributor",
                )
            )
            assert capability is not None
            capability.status = "suspended"

    catalog_response = await client.get("/v1/explore/frameworks")
    detail_response = await client.get(
        f"/v1/explore/frameworks/{framework_id}",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert catalog_response.status_code == 200, catalog_response.text
    assert all(
        item["id"] != str(framework_id) for item in catalog_response.json()["items"]
    )
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["id"] == str(framework_id)
    assert detail["owned"] is True
    assert detail["contributor_id"] is None
    assert detail["contributor_org_id"] == str(org_id)
    assert detail["contributor_name"] == "Hidden Org"


async def test_public_contributor_directory_lists_org_identity_without_member_leaks(
    client: AsyncClient,
    migrated_database: None,
    org_contributor_public_context: dict[str, Any],
) -> None:
    """The public directory exposes org identity and aggregate counts only."""
    del migrated_database, org_contributor_public_context
    owner_id = await create_user(
        "directory-public-owner@auracles.space",
        ["contributor"],
        display_name="Directory Owner",
    )
    member_id = await create_user(
        "directory-public-member@auracles.space",
        ["contributor"],
        display_name="Directory Member",
    )
    org_id, _ = await _create_org_framework(
        owner_id=owner_id,
        org_slug="directory-org",
        org_name="Directory Org",
        verification_level=4,
        reputation_score=Decimal("90.10"),
        framework_title="Directory Framework",
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgMember(
                    org_id=org_id,
                    user_id=member_id,
                    role="member",
                )
            )

    list_response = await client.get("/v1/contributors")
    detail_response = await client.get("/v1/contributors/directory-org")

    assert list_response.status_code == 200, list_response.text
    assert detail_response.status_code == 200, detail_response.text

    contributors = list_response.json()["contributors"]
    assert len(contributors) == 1
    entry = contributors[0]
    assert entry["org_id"] == str(org_id)
    assert entry["name"] == "Directory Org"
    assert entry["slug"] == "directory-org"
    assert entry["verification_level"] == 4
    assert entry["published_framework_count"] == 1
    assert entry["member_count"] == 2
    assert entry["reputation"] == "90.10"

    detail = detail_response.json()
    assert detail["org_id"] == str(org_id)
    assert detail["slug"] == "directory-org"

    serialized = f"{list_response.text}{detail_response.text}".lower()
    assert "authoring_member_id" not in serialized
    assert "user_id" not in serialized
    assert "email" not in serialized
