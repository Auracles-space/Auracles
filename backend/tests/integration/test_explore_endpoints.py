"""Integration tests for public marketplace Explore endpoints.

These tests exercise the public `/v1/explore` API introduced in Phase 2 Slice
10. They verify catalog visibility, filters, public preview access, and related
Framework selection through HTTP requests rather than service internals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, update

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
)
from app.modules.auth.models import User, UserRole
from app.modules.collections.models import CollectionFramework, FrameworkCollection
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
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for preview fixed-window rate limiting."""

    def __init__(self) -> None:
        """Create empty in-memory counter state."""
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        """Increment and return an integer counter."""
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        """Record a key expiry request."""
        self.expirations[key] = seconds
        return True


class FakeExploreStorage:
    """S3 storage test double for public preview URLs."""

    def __init__(self) -> None:
        """Create empty fake S3 state."""
        self.presigned_get_requests: list[tuple[str, str, int]] = []

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a deterministic fake preview URL."""
        self.presigned_get_requests.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}?signature=fake"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure marketplace tables exist for Explore endpoint tests."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def explore_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset marketplace rows and install lightweight dependency overrides."""
    from app.integrations import s3

    fake_redis = FakeRedis()
    fake_storage = FakeExploreStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in dependency order so tests stay isolated."""
        async with async_session_factory() as session:
            await session.execute(update(Framework).values(preview_artifact_id=None))
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(License))
            await session.execute(delete(CollectionFramework))
            await session.execute(delete(FrameworkCollection))
            await session.execute(delete(ArtifactRarityAudit))
            await session.execute(delete(ArtifactPiiAudit))
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    original_s3_storage = s3.storage
    s3.storage = fake_storage
    try:
        yield {"redis": fake_redis, "storage": fake_storage}
    finally:
        s3.storage = original_s3_storage
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def create_user(
    email: str,
    roles: list[str],
    *,
    kyc_status: str = "verified",
    display_name: str | None = None,
    avatar_url: str | None = None,
    bio: str | None = None,
    location: str | None = None,
    website: str | None = None,
    deactivated_at: datetime | None = None,
) -> UUID:
    """Create an email-verified user for Explore tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=(
                    display_name if display_name is not None else email.split("@")[0]
                ),
                avatar_url=avatar_url,
                bio=bio,
                location=location,
                website=website,
                deactivated_at=deactivated_at,
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


async def suspend_user(user_id: UUID) -> None:
    """Mark one user suspended for Explore visibility tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.suspended_at = datetime.now(UTC)


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def create_framework(
    contributor_id: UUID,
    *,
    title: str,
    status: str = "published",
    category: str = "framework",
    sector: str = "financial_services",
    industry: str = "fund_management",
    function: str = "risk_management",
    tags: list[str] | None = None,
    jurisdiction: str = "us",
    complexity: int = 3,
    org_size: str = "mid_market",
    lifecycle_stage: str = "scale",
    price: Decimal = Decimal("499.00"),
    thumbnail_key: str | None = None,
    with_preview: bool = False,
) -> tuple[UUID, UUID | None]:
    """Create a Framework and optional preview Artifact directly in the DB."""
    async with async_session_factory() as session:
        framework = Framework(
            id=uuid4(),
            contributor_id=contributor_id,
            title=title,
            description=f"{title} implementation playbook.",
            version="1.0.0",
            status=status,
            category=category,
            sector=sector,
            industry=industry,
            business_function=function,
            tags=tags or ["risk", "governance"],
            tags_text=" ".join(tags or ["risk", "governance"]),
            jurisdiction=jurisdiction,
            complexity=complexity,
            org_size=org_size,
            lifecycle_stage=lifecycle_stage,
            price=price,
            currency="USD",
            license_types=["single_user", "team"],
            thumbnail_key=thumbnail_key,
            published_at=datetime.now(UTC) if status == "published" else None,
        )
        session.add(framework)
        preview_artifact_id: UUID | None = None
        if with_preview:
            artifact = Artifact(
                id=uuid4(),
                framework_id=framework.id,
                name="preview.pdf",
                file_key=f"frameworks/{framework.id}/artifacts/preview.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="processed",
                current_for_framework=True,
                rarity_score=Decimal("0.9000"),
            )
            session.add(artifact)
            await session.flush()
            framework.preview_artifact_id = artifact.id
            preview_artifact_id = artifact.id
        await session.commit()
        return framework.id, preview_artifact_id


async def create_collection(
    contributor_id: UUID,
    *,
    title: str,
    framework_ids: list[UUID],
    bundle_price: Decimal,
    status: str = "published",
) -> UUID:
    """Create a Collection and member joins directly in the DB."""
    async with async_session_factory() as session:
        async with session.begin():
            collection = FrameworkCollection(
                id=uuid4(),
                contributor_id=contributor_id,
                title=title,
                description=f"{title} bundle.",
                bundle_price=bundle_price,
                currency="USD",
                status=status,
            )
            session.add(collection)
            await session.flush()
            for framework_id in framework_ids:
                session.add(
                    CollectionFramework(
                        collection_id=collection.id,
                        framework_id=framework_id,
                    )
                )
            return collection.id


async def create_framework_attestation(
    *,
    framework_id: UUID,
    requestor_id: UUID,
    attestor_id: UUID,
    status: str = "report_submitted",
    outcome: str = "approved",
    issued_at: datetime | None = None,
) -> UUID:
    """Create a public Framework-target Attestation report for Explore tests."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=framework_id,
                requestor_id=requestor_id,
                attestor_id=attestor_id,
                status=status,
                outcome=outcome,
                requested_specializations=["governance"],
                requested_jurisdictions=["US"],
                summary="Independent review completed.",
                scope="Review of implementation method and artifacts.",
                evidence_references={},
                report_key=f"attestation-reports/{uuid4()}/report.pdf",
                fee_amount=Decimal("250.00"),
                currency="USD",
                issued_at=issued_at or datetime.now(UTC),
            )
            session.add(attestation)
            await session.flush()
            return attestation.id


async def create_contributor_attestation(
    *,
    contributor_id: UUID,
    requestor_id: UUID,
    attestor_id: UUID,
    status: str = "closed",
    outcome: str = "approved",
    issued_at: datetime | None = None,
) -> UUID:
    """Create a public Contributor-target Attestation report for Explore tests."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="contributor",
                target_id=contributor_id,
                requestor_id=requestor_id,
                attestor_id=attestor_id,
                status=status,
                outcome=outcome,
                requested_specializations=["governance"],
                requested_jurisdictions=["US"],
                summary="Contributor profile review completed.",
                scope="Review of contributor expertise and published work.",
                evidence_references={},
                report_key=f"attestation-reports/{uuid4()}/report.pdf",
                fee_amount=Decimal("300.00"),
                currency="USD",
                issued_at=issued_at or datetime.now(UTC),
            )
            session.add(attestation)
            await session.flush()
            return attestation.id


async def test_public_catalog_search_filters_and_visibility(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Explore lists only published Frameworks matching search and filters."""
    contributor_id = await create_user("seller@auracles.space", ["contributor"])
    await create_framework(
        contributor_id,
        title="Board Risk Operating System",
        tags=["board", "risk", "governance"],
        price=Decimal("499.00"),
    )
    await create_framework(
        contributor_id,
        title="People Operations Toolkit",
        category="toolkit",
        sector="technology",
        tags=["people", "operations"],
        price=Decimal("199.00"),
    )
    await create_framework(
        contributor_id,
        title="Hidden Risk Draft",
        status="draft",
        tags=["risk"],
    )

    response = await client.get(
        "/v1/explore/frameworks",
        params={
            "q": "risk",
            "sector": "financial_services",
            "category": "framework",
            "price_min": "400.00",
            "price_max": "600.00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Board Risk Operating System"
    assert body["items"][0]["contributor_id"] == str(contributor_id)
    assert body["items"][0]["contributor_name"] == "seller"
    assert body["items"][0]["category"] == "framework"
    assert body["items"][0]["sector"] == "financial_services"
    assert body["items"][0]["industry"] == "fund_management"
    assert body["items"][0]["function"] == "risk_management"
    assert body["items"][0]["org_size"] == "mid_market"
    assert body["items"][0]["owned"] is False


async def test_public_collection_list_and_detail_show_members_and_savings(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Explore exposes published Collections with member summaries and savings."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "collection-explore-seller@auracles.space",
        ["contributor"],
        display_name="Collection Seller",
    )
    first_id, _ = await create_framework(
        contributor_id,
        title="Risk Register Kit",
        price=Decimal("500.00"),
    )
    second_id, _ = await create_framework(
        contributor_id,
        title="Board Reporting Kit",
        price=Decimal("700.00"),
    )
    published_collection_id = await create_collection(
        contributor_id,
        title="Risk Governance Bundle",
        framework_ids=[first_id, second_id],
        bundle_price=Decimal("900.00"),
    )
    await create_collection(
        contributor_id,
        title="Hidden Draft Bundle",
        framework_ids=[first_id, second_id],
        bundle_price=Decimal("800.00"),
        status="draft",
    )

    list_response = await client.get("/v1/explore/collections")
    detail_response = await client.get(
        f"/v1/explore/collections/{published_collection_id}"
    )

    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body["total"] == 1
    item = list_body["items"][0]
    assert item["item_type"] == "collection"
    assert item["id"] == str(published_collection_id)
    assert item["contributor_name"] == "Collection Seller"
    assert item["bundle_price"] == "900.00"
    assert item["member_price_sum"] == "1200.00"
    assert item["savings_amount"] == "300.00"
    assert item["savings_percent"] == "25.00"
    assert item["member_count"] == 2
    assert [member["title"] for member in item["members"]] == [
        "Board Reporting Kit",
        "Risk Register Kit",
    ]
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["id"] == str(published_collection_id)
    assert detail_body["already_owned_member_ids"] == []
    assert detail_body["members"][0]["framework_id"] == str(second_id)


async def test_mixed_catalog_returns_framework_and_collection_items(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """The mixed catalog returns typed Framework and Collection cards together."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "mixed-catalog-seller@auracles.space",
        ["contributor"],
    )
    framework_id, _ = await create_framework(
        contributor_id,
        title="Standalone Risk System",
        price=Decimal("500.00"),
    )
    second_id, _ = await create_framework(
        contributor_id,
        title="Governance Companion",
        price=Decimal("600.00"),
        tags=["governance", "board"],
    )
    collection_id = await create_collection(
        contributor_id,
        title="Mixed Risk Bundle",
        framework_ids=[framework_id, second_id],
        bundle_price=Decimal("800.00"),
    )

    response = await client.get("/v1/explore/catalog", params={"q": "risk"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    item_types = {item["item_type"] for item in body["items"]}
    item_ids = {item["id"] for item in body["items"]}
    assert item_types == {"framework", "collection"}
    assert str(framework_id) in item_ids
    assert str(collection_id) in item_ids


async def test_mixed_catalog_taxonomy_filter_narrows_frameworks_and_hides_collections(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """A Framework taxonomy filter narrows frameworks and drops collections.

    Collections carry no taxonomy, so any sector/industry/category/etc. filter
    on the mixed feed excludes bundles entirely (product decision) while still
    filtering the Framework cards.
    """
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "mixed-filter-seller@auracles.space",
        ["contributor"],
    )
    healthcare_id, _ = await create_framework(
        contributor_id,
        title="Healthcare Risk System",
        sector="healthcare",
    )
    finance_id, _ = await create_framework(
        contributor_id,
        title="Finance Risk System",
        sector="financial_services",
    )
    await create_collection(
        contributor_id,
        title="Risk Bundle",
        framework_ids=[healthcare_id, finance_id],
        bundle_price=Decimal("800.00"),
    )

    response = await client.get(
        "/v1/explore/catalog",
        params={"sector": "healthcare"},
    )

    assert response.status_code == 200
    body = response.json()
    item_types = {item["item_type"] for item in body["items"]}
    item_ids = {item["id"] for item in body["items"]}
    assert item_types == {"framework"}
    assert str(healthcare_id) in item_ids
    assert str(finance_id) not in item_ids
    assert body["total"] == 1


async def test_mixed_catalog_price_filter_applies_to_both_item_types(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Price filters narrow both Frameworks and Collections, keeping bundles."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "mixed-price-seller@auracles.space",
        ["contributor"],
    )
    cheap_id, _ = await create_framework(
        contributor_id,
        title="Cheap Framework",
        price=Decimal("100.00"),
    )
    expensive_id, _ = await create_framework(
        contributor_id,
        title="Expensive Framework",
        price=Decimal("900.00"),
    )
    collection_id = await create_collection(
        contributor_id,
        title="Affordable Bundle",
        framework_ids=[cheap_id, expensive_id],
        bundle_price=Decimal("150.00"),
    )

    response = await client.get(
        "/v1/explore/catalog",
        params={"price_max": "200"},
    )

    assert response.status_code == 200
    item_ids = {item["id"] for item in response.json()["items"]}
    assert str(cheap_id) in item_ids
    assert str(collection_id) in item_ids
    assert str(expensive_id) not in item_ids


async def test_public_catalog_returns_and_filters_framework_attestation_badges(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Explore exposes public Framework attestation badges and filters by them."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "attested-seller@auracles.space",
        ["contributor"],
    )
    requestor_id = await create_user(
        "attestation-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "public-attestor@auracles.space",
        ["attestor"],
    )
    attested_framework_id, _ = await create_framework(
        contributor_id,
        title="Attested Board Framework",
    )
    await create_framework(
        contributor_id,
        title="Unattested Board Framework",
    )
    attestation_id = await create_framework_attestation(
        framework_id=attested_framework_id,
        requestor_id=requestor_id,
        attestor_id=attestor_id,
    )

    catalog_response = await client.get("/v1/explore/frameworks")
    filtered_response = await client.get(
        "/v1/explore/frameworks",
        params={"attestation_status": "pending_acceptance"},
    )
    unattested_response = await client.get(
        "/v1/explore/frameworks",
        params={"attestation_status": "none"},
    )
    detail_response = await client.get(
        f"/v1/explore/frameworks/{attested_framework_id}"
    )

    assert catalog_response.status_code == 200
    catalog_items = catalog_response.json()["items"]
    attested_item = next(
        item for item in catalog_items if item["id"] == str(attested_framework_id)
    )
    unattested_item = next(
        item for item in catalog_items if item["id"] != str(attested_framework_id)
    )
    assert attested_item["attestation_badge"] == {
        "id": str(attestation_id),
        "status": "pending_acceptance",
        "outcome": "approved",
        "report_key": attested_item["attestation_badge"]["report_key"],
        "issued_at": attested_item["attestation_badge"]["issued_at"],
        "attestation_count": 1,
    }
    assert attested_item["attestation_badge"]["report_key"].startswith(
        "attestation-reports/"
    )
    assert unattested_item["attestation_badge"] is None
    assert filtered_response.status_code == 200
    assert filtered_response.json()["total"] == 1
    assert filtered_response.json()["items"][0]["id"] == str(attested_framework_id)
    assert unattested_response.status_code == 200
    assert unattested_response.json()["total"] == 1
    assert unattested_response.json()["items"][0]["title"] == (
        "Unattested Board Framework"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["attestation_badge"]["id"] == str(attestation_id)
    assert detail_response.json()["contributor_id"] == str(contributor_id)
    assert detail_response.json()["contributor_name"] == "attested-seller"


async def test_rejected_framework_attestation_does_not_render_positive_badge(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Rejected public reports must not appear as positive Explore badges."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "rejected-attestation-seller@auracles.space",
        ["contributor"],
    )
    requestor_id = await create_user(
        "rejected-attestation-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "rejected-public-attestor@auracles.space",
        ["attestor"],
    )
    framework_id, _ = await create_framework(
        contributor_id,
        title="Rejected Attestation Framework",
    )
    await create_framework_attestation(
        framework_id=framework_id,
        requestor_id=requestor_id,
        attestor_id=attestor_id,
        status="closed",
        outcome="rejected",
    )

    catalog_response = await client.get("/v1/explore/frameworks")
    attested_response = await client.get(
        "/v1/explore/frameworks",
        params={"attestation_status": "attested"},
    )
    none_response = await client.get(
        "/v1/explore/frameworks",
        params={"attestation_status": "none"},
    )
    detail_response = await client.get(f"/v1/explore/frameworks/{framework_id}")

    assert catalog_response.status_code == 200
    catalog_item = catalog_response.json()["items"][0]
    assert catalog_item["id"] == str(framework_id)
    assert catalog_item["attestation_badge"] is None
    assert attested_response.status_code == 200
    assert attested_response.json()["total"] == 0
    assert none_response.status_code == 200
    assert none_response.json()["total"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["attestation_badge"] is None


async def test_conditionally_attested_framework_filter_and_badge(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Conditional closed reports render and filter as conditionally attested."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "conditional-attestation-seller@auracles.space",
        ["contributor"],
    )
    requestor_id = await create_user(
        "conditional-attestation-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "conditional-public-attestor@auracles.space",
        ["attestor"],
    )
    framework_id, _ = await create_framework(
        contributor_id,
        title="Conditional Attestation Framework",
    )
    attestation_id = await create_framework_attestation(
        framework_id=framework_id,
        requestor_id=requestor_id,
        attestor_id=attestor_id,
        status="closed",
        outcome="conditional",
    )

    filtered_response = await client.get(
        "/v1/explore/frameworks",
        params={"attestation_status": "conditionally_attested"},
    )
    detail_response = await client.get(f"/v1/explore/frameworks/{framework_id}")

    assert filtered_response.status_code == 200
    assert filtered_response.json()["total"] == 1
    item = filtered_response.json()["items"][0]
    assert item["id"] == str(framework_id)
    assert item["attestation_badge"]["id"] == str(attestation_id)
    assert item["attestation_badge"]["status"] == "conditionally_attested"
    assert item["attestation_badge"]["outcome"] == "conditional"
    assert detail_response.status_code == 200
    assert detail_response.json()["attestation_badge"]["status"] == (
        "conditionally_attested"
    )


async def test_public_contributor_profile_returns_safe_fields_and_frameworks(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Public Contributor profiles expose safe fields and published Frameworks."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "public-contributor@auracles.space",
        ["contributor"],
        display_name="Mara Okafor",
        avatar_url="https://cdn.auracles.test/avatars/mara.png",
        bio="Builds governance and operating model Frameworks.",
        location="Lagos, NG",
        website="https://mara.example",
    )
    await create_framework(contributor_id, title="Published Governance System")
    await create_framework(
        contributor_id,
        title="Draft Governance System",
        status="draft",
    )

    response = await client.get(f"/v1/explore/contributors/{contributor_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(contributor_id)
    assert body["display_name"] == "Mara Okafor"
    assert body["avatar_url"] == "https://cdn.auracles.test/avatars/mara.png"
    assert body["bio"] == "Builds governance and operating model Frameworks."
    assert body["location"] == "Lagos, NG"
    assert body["website"] == "https://mara.example"
    assert body["is_deactivated"] is False
    assert body["attestation_badge"] is None
    assert body["attestation_count"] == 0
    assert body["published_framework_count"] == 1
    assert [item["title"] for item in body["published_frameworks"]] == [
        "Published Governance System"
    ]
    assert "email" not in body
    assert "kyc_status" not in body
    assert "roles" not in body
    assert "payout" not in body


async def test_public_contributor_profile_nulls_unsafe_website_scheme(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """A stored javascript: website must not reach clients as a usable link."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "xss-contributor@auracles.space",
        ["contributor"],
        display_name="Eve Attacker",
        website="javascript:alert(document.cookie)",
    )
    await create_framework(contributor_id, title="Published Governance System")

    response = await client.get(f"/v1/explore/contributors/{contributor_id}")

    assert response.status_code == 200
    assert response.json()["website"] is None


async def test_public_contributor_profile_uses_best_attestation_badge(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Contributor profile badges prefer the best public outcome and count reports."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "attested-contributor@auracles.space",
        ["contributor"],
        display_name="Ife Adeyemi",
    )
    requestor_id = await create_user(
        "contributor-attestation-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "contributor-public-attestor@auracles.space",
        ["attestor"],
    )
    await create_framework(contributor_id, title="Attested Contributor Framework")
    approved_id = await create_contributor_attestation(
        contributor_id=contributor_id,
        requestor_id=requestor_id,
        attestor_id=attestor_id,
        status="closed",
        outcome="approved",
        issued_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await create_contributor_attestation(
        contributor_id=contributor_id,
        requestor_id=requestor_id,
        attestor_id=attestor_id,
        status="closed",
        outcome="rejected",
        issued_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    await create_contributor_attestation(
        contributor_id=contributor_id,
        requestor_id=requestor_id,
        attestor_id=attestor_id,
        status="closed",
        outcome="conditional",
        issued_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    response = await client.get(f"/v1/explore/contributors/{contributor_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["attestation_count"] == 3
    assert body["attestation_badge"] == {
        "id": str(approved_id),
        "status": "attested",
        "outcome": "approved",
        "report_key": body["attestation_badge"]["report_key"],
        "issued_at": body["attestation_badge"]["issued_at"],
        "attestation_count": 3,
    }


async def test_public_contributor_profile_visibility_guards_and_limit(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Contributor profiles avoid enumeration and cap published Framework cards."""
    del migrated_database, explore_test_context
    operator_id = await create_user("profile-operator@auracles.space", ["operator"])
    empty_contributor_id = await create_user(
        "empty-contributor@auracles.space",
        ["contributor"],
    )
    deactivated_contributor_id = await create_user(
        "deactivated-contributor@auracles.space",
        ["contributor"],
        display_name="Deactivated Contributor",
        deactivated_at=datetime.now(UTC),
    )
    await create_framework(
        deactivated_contributor_id,
        title="Deactivated Public Framework",
    )
    prolific_contributor_id = await create_user(
        "prolific-contributor@auracles.space",
        ["contributor"],
    )
    for index in range(14):
        await create_framework(
            prolific_contributor_id,
            title=f"Public Framework {index:02d}",
        )

    operator_response = await client.get(f"/v1/explore/contributors/{operator_id}")
    empty_response = await client.get(
        f"/v1/explore/contributors/{empty_contributor_id}"
    )
    deactivated_response = await client.get(
        f"/v1/explore/contributors/{deactivated_contributor_id}"
    )
    prolific_response = await client.get(
        f"/v1/explore/contributors/{prolific_contributor_id}"
    )

    assert operator_response.status_code == 404
    assert empty_response.status_code == 404
    assert deactivated_response.status_code == 200
    assert deactivated_response.json()["is_deactivated"] is True
    assert deactivated_response.json()["published_framework_count"] == 1
    assert prolific_response.status_code == 200
    assert prolific_response.json()["published_framework_count"] == 14
    assert len(prolific_response.json()["published_frameworks"]) == 12


async def test_suspended_contributor_is_hidden_from_explore_reads(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Suspended Contributors disappear from catalog, detail, and profile reads."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "suspended-explore-contributor@auracles.space",
        ["contributor"],
        display_name="Suspended Seller",
    )
    framework_id, _ = await create_framework(
        contributor_id,
        title="Suspended Explore Framework",
    )
    await suspend_user(contributor_id)

    catalog_response = await client.get("/v1/explore/frameworks")
    detail_response = await client.get(f"/v1/explore/frameworks/{framework_id}")
    profile_response = await client.get(f"/v1/explore/contributors/{contributor_id}")

    assert catalog_response.status_code == 200
    assert [
        item["title"] for item in catalog_response.json()["items"]
    ] == []
    assert detail_response.status_code == 404
    assert profile_response.status_code == 404


async def test_suspended_contributor_collections_are_hidden_from_explore(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Suspended Contributors' Collections disappear from public Explore."""
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        f"suspended-collection-contributor-{uuid4()}@auracles.space",
        ["contributor"],
    )
    first_framework_id, _ = await create_framework(
        contributor_id,
        title="Suspended Bundle Member A",
    )
    second_framework_id, _ = await create_framework(
        contributor_id,
        title="Suspended Bundle Member B",
    )
    collection_id = await create_collection(
        contributor_id=contributor_id,
        title="Suspended Collection",
        framework_ids=[first_framework_id, second_framework_id],
        bundle_price=Decimal("700.00"),
    )
    await suspend_user(contributor_id)

    list_response = await client.get("/v1/explore/collections")
    detail_response = await client.get(f"/v1/explore/collections/{collection_id}")

    assert list_response.status_code == 200
    assert list_response.json()["items"] == []
    assert detail_response.status_code == 404


async def test_authenticated_contributor_catalog_excludes_own_frameworks(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Authenticated Contributors do not see their own Frameworks in Explore."""
    owner_id = await create_user("owner-explore@auracles.space", ["contributor"])
    other_id = await create_user("other-explore@auracles.space", ["contributor"])
    await create_framework(owner_id, title="Owner Risk System")
    await create_framework(other_id, title="Other Risk System")

    response = await client.get(
        "/v1/explore/frameworks",
        headers=auth_headers(owner_id, ["contributor"]),
    )

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert "Owner Risk System" not in titles
    assert "Other Risk System" in titles


async def test_incomplete_authenticated_user_can_view_detail_and_preview(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Incomplete authenticated users can browse detail and public preview."""
    contributor_id = await create_user("preview-seller@auracles.space", ["contributor"])
    viewer_id = await create_user(
        "pending-viewer@auracles.space",
        ["operator"],
        kyc_status="pending",
        display_name="",
    )
    framework_id, preview_artifact_id = await create_framework(
        contributor_id,
        title="Previewable Risk System",
        with_preview=True,
    )

    response = await client.get(
        f"/v1/explore/frameworks/{framework_id}",
        headers=auth_headers(viewer_id, ["operator"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(framework_id)
    assert body["preview_artifact_id"] == str(preview_artifact_id)
    assert body["preview_url"].startswith("https://s3.test/")
    assert body["artifacts"][0]["id"] == str(preview_artifact_id)
    assert "file_key" not in body["artifacts"][0]


async def test_preview_url_rate_limit_returns_429_on_sixty_first_request(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Preview URL generation is rate-limited per client IP."""
    contributor_id = await create_user("rate-seller@auracles.space", ["contributor"])
    framework_id, _ = await create_framework(
        contributor_id,
        title="Rate Limited Preview",
        with_preview=True,
    )

    last_response = None
    for _ in range(61):
        last_response = await client.get(f"/v1/explore/frameworks/{framework_id}")

    assert last_response is not None
    assert last_response.status_code == 429


async def test_related_frameworks_use_tag_category_and_sector_overlap(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Related Frameworks prefer published items sharing marketplace metadata."""
    owner_id = await create_user("related-owner@auracles.space", ["contributor"])
    other_id = await create_user("related-other@auracles.space", ["contributor"])
    framework_id, _ = await create_framework(
        owner_id,
        title="Risk Control Hub",
        tags=["risk", "controls", "board"],
    )
    await create_framework(
        other_id,
        title="Board Controls Companion",
        tags=["risk", "controls", "audit"],
    )
    await create_framework(
        other_id,
        title="Sales Playbook",
        category="playbook",
        sector="technology",
        tags=["sales"],
    )

    response = await client.get(f"/v1/explore/frameworks/{framework_id}/related")

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()]
    assert titles[0] == "Board Controls Companion"
    assert "Risk Control Hub" not in titles
