"""Integration tests for verified Credential exposure on public profiles.

Verifies that `GET /v1/explore/contributors/{contributor_id}` surfaces
verified Credentials via the `verified_credentials` field, exposing only
safe fields (title, issuer, credential_type, issued_date, expires_date,
expired) and never evidence keys, verification URLs, reference numbers,
review metadata, or non-verified Credentials.

Maps to: FR-FWK (contributor profile), credential verification slice Task 8.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
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
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
    Credential,
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
    fake_redis = FakeRedis()
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
            await session.execute(delete(Credential))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"redis": fake_redis}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def create_user(
    email: str,
    roles: list[str],
    *,
    display_name: str | None = None,
) -> UUID:
    """Create an email-verified user for Explore Credential tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=(
                    display_name if display_name is not None else email.split("@")[0]
                ),
                email_verified=True,
                kyc_status="verified",
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


async def create_framework(
    contributor_id: UUID,
    *,
    title: str,
    status: str = "published",
) -> UUID:
    """Create a Framework directly in the DB for profile-visibility tests."""
    async with async_session_factory() as session:
        framework = Framework(
            id=uuid4(),
            contributor_id=contributor_id,
            title=title,
            description=f"{title} implementation playbook.",
            version="1.0.0",
            status=status,
            category="framework",
            sector="financial_services",
            industry="fund_management",
            business_function="risk_management",
            tags=["risk", "governance"],
            tags_text="risk governance",
            jurisdiction="us",
            complexity=3,
            org_size="mid_market",
            lifecycle_stage="scale",
            price=Decimal("499.00"),
            currency="USD",
            license_types=["single_user", "team"],
            thumbnail_key=None,
            published_at=datetime.now(UTC) if status == "published" else None,
        )
        session.add(framework)
        await session.commit()
        return framework.id


async def create_credential(
    user_id: UUID,
    *,
    title: str,
    issuer: str = "PMI",
    credential_type: str | None = "PMP",
    issued_date: date = date(2024, 1, 1),
    expires_date: date | None = None,
    verification_status: str = "verified",
    reference_number: str | None = None,
    verification_url: str | None = None,
    evidence_file_keys: list[str] | None = None,
) -> UUID:
    """Create a Credential row directly in the DB for visibility tests."""
    async with async_session_factory() as session:
        async with session.begin():
            credential = Credential(
                user_id=user_id,
                title=title,
                issuer=issuer,
                credential_type=credential_type,
                issued_date=issued_date,
                expires_date=expires_date,
                verification_status=verification_status,
                reference_number=reference_number,
                verification_url=verification_url,
                evidence_file_keys=evidence_file_keys or [],
            )
            session.add(credential)
            await session.flush()
        return credential.id


async def test_public_contributor_profile_exposes_only_verified_credential_safe_fields(
    client: AsyncClient,
    migrated_database: None,
    explore_test_context: dict[str, Any],
) -> None:
    """Public profiles list verified Credentials with safe fields only.

    Pending Credentials and sensitive fields (reference_number,
    verification_url, evidence_file_keys) must never reach the client.
    """
    del migrated_database, explore_test_context
    contributor_id = await create_user(
        "credentialed-contributor@auracles.space",
        ["contributor"],
        display_name="Tomi Adebayo",
    )
    await create_framework(contributor_id, title="Published Governance System")

    await create_credential(
        contributor_id,
        title="PMP",
        issuer="PMI",
        credential_type="PMP",
        issued_date=date(2024, 1, 1),
        verification_status="verified",
        reference_number="SECRET-REF",
        verification_url="https://secret",
        evidence_file_keys=["s3-secret-key"],
    )
    await create_credential(
        contributor_id,
        title="Pending Cert",
        issuer="Some Body",
        credential_type="OTHER",
        issued_date=date(2024, 6, 1),
        verification_status="pending",
    )

    response = await client.get(f"/v1/explore/contributors/{contributor_id}")

    assert response.status_code == 200
    creds = response.json()["verified_credentials"]
    assert [c["title"] for c in creds] == ["PMP"]
    serialized = response.text
    assert "SECRET-REF" not in serialized
    assert "s3-secret-key" not in serialized
    assert "https://secret" not in serialized
    assert "Pending Cert" not in serialized
