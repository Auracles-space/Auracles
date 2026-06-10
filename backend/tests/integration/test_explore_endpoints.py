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


async def create_framework_attestation(
    *,
    framework_id: UUID,
    requestor_id: UUID,
    attestor_id: UUID,
    status: str = "report_submitted",
    outcome: str = "approved",
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
                issued_at=datetime.now(UTC),
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
    assert body["items"][0]["category"] == "framework"
    assert body["items"][0]["sector"] == "financial_services"
    assert body["items"][0]["industry"] == "fund_management"
    assert body["items"][0]["function"] == "risk_management"
    assert body["items"][0]["org_size"] == "mid_market"
    assert body["items"][0]["owned"] is False


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
