"""Framework-page badge list tests for Module 6c public badge detail reads."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
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
from app.core.security import hash_password
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationBadge,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
)
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
)
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


class FakeRedis:
    """Redis test double for preview rate-limit dependencies."""

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        store = self.__dict__.setdefault("values", {})
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.__dict__.setdefault("values", {})[key] = value

    async def incr(self, key: str) -> int:
        """Return a deterministic counter value for tests without previews."""
        del key
        return 1

    async def expire(self, key: str, seconds: int) -> bool:
        """Accept expiry requests for tests without previews."""
        del key, seconds
        return True


class FakeExploreStorage:
    """S3 storage double for preview URL generation."""

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a deterministic fake presigned URL."""
        return f"https://s3.test/{bucket}/{key}?expires={expires_in}"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Explore source tables exist for framework badge detail tests."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def explore_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset marketplace state and install lightweight dependency overrides."""
    from app.integrations import s3

    fake_redis = FakeRedis()
    fake_storage = FakeExploreStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK-safe order so tests stay isolated."""
        async with async_session_factory() as session:
            await session.execute(update(Framework).values(preview_artifact_id=None))
            await session.execute(delete(AuditLog))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(AttestationBadge))
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(ArtifactRarityAudit))
            await session.execute(delete(ArtifactPiiAudit))
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


async def _create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user for framework badge detail tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
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


async def _create_framework(
    contributor_id: UUID,
    *,
    title: str,
    version: str,
) -> Framework:
    """Create one published framework for Explore detail reads."""
    async with async_session_factory() as session:
        framework = Framework(
            id=uuid4(),
            contributor_id=contributor_id,
            title=title,
            description="Published framework for badge detail tests.",
            version=version,
            status="published",
            category="framework",
            sector="financial_services",
            industry="fund_management",
            business_function="risk_management",
            tags=["badge"],
            jurisdiction="us",
            complexity=3,
            org_size="mid_market",
            lifecycle_stage="scale",
            price=Decimal("499.00"),
            currency="USD",
            license_types=["single_user"],
            published_at=datetime.now(UTC),
        )
        session.add(framework)
        await session.commit()
        await session.refresh(framework)
        return framework


async def _create_badge(
    *,
    framework: Framework,
    attestor_id: UUID,
    outcome: str,
    framework_version: str | None,
    issued_at: datetime,
) -> None:
    """Create one attestation plus immutable badge snapshot row."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=framework.id,
                requestor_id=framework.contributor_id,
                status="closed",
                outcome=outcome,
                review_type="quality",
                requested_specializations=["governance"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("500.00"),
                currency="USD",
                report_published_eligible=True,
                closed_at=issued_at,
            )
            session.add(attestation)
            await session.flush()
            session.add(
                AttestationBadge(
                    attestation_id=attestation.id,
                    framework_id=framework.id,
                    review_type="quality",
                    outcome=outcome,
                    attestor_id=attestor_id,
                    attestor_display_name="Public Attestor",
                    credentials_snapshot=[
                        {
                            "title": "Certified Transformation Lead",
                            "issuer": "Global Institute",
                            "credential_type": "professional",
                            "issued_date": "2024-01-01",
                            # Relative, because `expired: False` below has to
                            # stay true for the snapshot to mean what the
                            # assertions read it as.
                            "expires_date": (
                                date.today() + timedelta(days=365 * 3)
                            ).isoformat(),
                            "expired": False,
                        }
                    ],
                    framework_version=framework_version,
                    issued_at=issued_at,
                )
            )


@pytest.fixture
async def published_framework_with_badges(
    explore_test_context: dict[str, Any],
) -> Framework:
    """Create a framework with one approved and one rejected badge snapshot."""
    del explore_test_context
    contributor_id = await _create_user(
        "framework-badge-seller@auracles.space",
        ["contributor"],
    )
    attestor_id = await _create_user(
        "framework-badge-attestor@auracles.space",
        ["attestor"],
    )
    framework = await _create_framework(
        contributor_id,
        title="Badge Detail Framework",
        version="1.0",
    )
    await _create_badge(
        framework=framework,
        attestor_id=attestor_id,
        outcome="approved",
        framework_version="1.0",
        issued_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    await _create_badge(
        framework=framework,
        attestor_id=attestor_id,
        outcome="rejected",
        framework_version="1.0",
        issued_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    return framework


@pytest.fixture
async def framework_with_stale_badge(
    explore_test_context: dict[str, Any],
) -> Framework:
    """Create a framework whose approved badge points at an older version."""
    del explore_test_context
    contributor_id = await _create_user(
        "stale-badge-seller@auracles.space",
        ["contributor"],
    )
    attestor_id = await _create_user(
        "stale-badge-attestor@auracles.space",
        ["attestor"],
    )
    framework = await _create_framework(
        contributor_id,
        title="Stale Badge Framework",
        version="1.1",
    )
    await _create_badge(
        framework=framework,
        attestor_id=attestor_id,
        outcome="approved",
        framework_version="1.0",
        issued_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    return framework


async def test_detail_lists_positive_badges_only(
    client: AsyncClient,
    migrated_database: None,
    published_framework_with_badges: Framework,
) -> None:
    """Framework detail returns approved badges and excludes rejected ones."""
    del migrated_database
    response = await client.get(
        f"/v1/explore/frameworks/{published_framework_with_badges.id}"
    )

    assert response.status_code == 200
    outcomes = {b["outcome"] for b in response.json()["attestation_badges"]}
    assert outcomes == {"approved"}


async def test_newer_version_exists_flag(
    client: AsyncClient,
    migrated_database: None,
    framework_with_stale_badge: Framework,
) -> None:
    """A stale captured version sets newer_version_exists on the badge detail."""
    del migrated_database
    response = await client.get(
        f"/v1/explore/frameworks/{framework_with_stale_badge.id}"
    )

    assert response.status_code == 200
    badge = response.json()["attestation_badges"][0]
    assert badge["framework_version"] == "1.0"
    assert badge["newer_version_exists"] is True
