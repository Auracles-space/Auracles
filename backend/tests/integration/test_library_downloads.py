"""Integration tests for license grants, Operator library, and downloads."""

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
from sqlalchemy import create_engine, delete, func, select, update

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
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
    """Minimal Redis override for authenticated library routes."""


class FakeDownloadStorage:
    """S3 storage test double for licensed Artifact downloads."""

    def __init__(self) -> None:
        """Create empty fake S3 state."""
        self.presigned_get_requests: list[tuple[str, str, int]] = []
        self.counter = 0

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a unique deterministic fake presigned GET URL."""
        self.counter += 1
        self.presigned_get_requests.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}?download={self.counter}"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure marketplace tables exist for library endpoint tests."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def library_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset marketplace rows and install fake Redis/S3 dependencies."""
    from app.integrations import s3

    fake_storage = FakeDownloadStorage()
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
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    original_s3_storage = s3.storage
    s3.storage = fake_storage
    try:
        yield {"storage": fake_storage}
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
) -> UUID:
    """Create an email-verified user for library tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
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


async def create_published_framework_version(
    contributor_id: UUID,
    *,
    status: str = "published",
    version: str = "1.0.0",
    title: str = "Licensed Risk System",
) -> tuple[UUID, UUID]:
    """Create one published Framework, version snapshot, and Artifact."""
    async with async_session_factory() as session:
        framework = Framework(
            id=uuid4(),
            contributor_id=contributor_id,
            title=title,
            description=f"{title} implementation guide.",
            version=version,
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
            license_types=["single_user", "team", "enterprise"],
            published_at=datetime.now(UTC),
        )
        artifact = Artifact(
            id=uuid4(),
            framework_id=framework.id,
            name="licensed.pdf",
            file_key=f"frameworks/{framework.id}/artifacts/licensed.pdf",
            file_size=2048,
            mime_type="application/pdf",
            scan_status="clean",
            processing_status="processed",
            current_for_framework=True,
        )
        session.add_all([framework, artifact])
        await session.flush()
        snapshot = FrameworkVersion(
            framework_id=framework.id,
            version=version,
            change_type="major",
            change_log="Published for library tests.",
        )
        session.add(snapshot)
        await session.flush()
        session.add(
            FrameworkVersionArtifact(
                framework_version_id=snapshot.id,
                artifact_id=artifact.id,
                is_preview=False,
            )
        )
        await session.commit()
        return framework.id, artifact.id


async def create_new_current_artifact_without_license_snapshot(
    framework_id: UUID,
) -> UUID:
    """Create a v2 Artifact that is not covered by an existing v1 license."""
    async with async_session_factory() as session:
        framework = await session.get(Framework, framework_id)
        assert framework is not None
        framework.version = "2.0.0"
        old_artifacts = (
            (
                await session.execute(
                    select(Artifact).where(Artifact.framework_id == framework_id)
                )
            )
            .scalars()
            .all()
        )
        for artifact in old_artifacts:
            artifact.current_for_framework = False
        new_artifact = Artifact(
            id=uuid4(),
            framework_id=framework_id,
            name="licensed-v2.pdf",
            file_key=f"frameworks/{framework_id}/artifacts/licensed-v2.pdf",
            file_size=4096,
            mime_type="application/pdf",
            scan_status="clean",
            processing_status="processed",
            current_for_framework=True,
        )
        session.add(new_artifact)
        await session.commit()
        return new_artifact.id


async def grant_license_directly(
    framework_id: UUID,
    operator_id: UUID,
    *,
    version: str = "1.0.0",
    license_type: str = "single_user",
) -> UUID:
    """Create an active license directly in the DB for download tests."""
    async with async_session_factory() as session:
        license_row = License(
            framework_id=framework_id,
            operator_id=operator_id,
            license_type=license_type,
            status="active",
            version_at_grant=version,
            seats_used=1,
            seats_total=10 if license_type == "team" else None,
        )
        session.add(license_row)
        await session.commit()
        return license_row.id


async def grant_collection_license_directly(
    framework_id: UUID,
    operator_id: UUID,
    contributor_id: UUID,
) -> UUID:
    """Create a collection-sourced license directly for library tests."""
    async with async_session_factory() as session:
        async with session.begin():
            collection = FrameworkCollection(
                contributor_id=contributor_id,
                title="Governance Collection",
                description="A collection source for library display.",
                bundle_price=Decimal("399.00"),
                currency="USD",
                status="published",
            )
            session.add(collection)
            await session.flush()
            session.add(
                CollectionFramework(
                    collection_id=collection.id,
                    framework_id=framework_id,
                )
            )
            license_row = License(
                framework_id=framework_id,
                operator_id=operator_id,
                source="collection",
                collection_id=collection.id,
                license_type="team",
                status="active",
                version_at_grant="1.0.0",
                seats_used=1,
                seats_total=10,
            )
            session.add(license_row)
            await session.flush()
            return collection.id


async def test_admin_can_grant_team_license_and_operator_library_lists_it(
    client: AsyncClient,
    migrated_database: None,
    library_test_context: dict[str, Any],
) -> None:
    """Admin license grant creates a library entry for the Operator."""
    contributor_id = await create_user("licensor@auracles.space", ["contributor"])
    operator_id = await create_user("operator-library@auracles.space", ["operator"])
    admin_id = await create_user("admin-license@auracles.space", ["admin"])
    framework_id, _ = await create_published_framework_version(contributor_id)

    grant = await client.post(
        "/v1/admin/licenses",
        json={
            "framework_id": str(framework_id),
            "operator_id": str(operator_id),
            "type": "team",
        },
        headers=auth_headers(admin_id, ["admin"]),
    )
    library = await client.get(
        "/v1/library",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert grant.status_code == 201
    assert grant.json()["version_at_grant"] == "1.0.0"
    assert grant.json()["seats_total"] == 10
    assert library.status_code == 200
    assert library.json()["total"] == 1
    assert library.json()["items"][0]["framework_id"] == str(framework_id)
    assert library.json()["items"][0]["source"] == "individual"
    assert library.json()["items"][0]["collection_id"] is None


async def test_operator_library_marks_collection_sourced_licenses(
    client: AsyncClient,
    migrated_database: None,
    library_test_context: dict[str, Any],
) -> None:
    """Collection-minted licenses expose source metadata for the Library UI."""
    contributor_id = await create_user(
        "collection-library-seller@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user(
        "collection-library-operator@auracles.space",
        ["operator"],
    )
    framework_id, _ = await create_published_framework_version(contributor_id)
    collection_id = await grant_collection_license_directly(
        framework_id,
        operator_id,
        contributor_id,
    )

    library = await client.get(
        "/v1/library",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert library.status_code == 200
    item = library.json()["items"][0]
    assert item["framework_id"] == str(framework_id)
    assert item["source"] == "collection"
    assert item["collection_id"] == str(collection_id)


async def test_admin_duplicate_license_grant_returns_409(
    client: AsyncClient,
    migrated_database: None,
    library_test_context: dict[str, Any],
) -> None:
    """A user can hold only one license per Framework."""
    contributor_id = await create_user(
        "duplicate-seller@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user("duplicate-operator@auracles.space", ["operator"])
    admin_id = await create_user("duplicate-admin@auracles.space", ["admin"])
    framework_id, _ = await create_published_framework_version(contributor_id)
    payload = {
        "framework_id": str(framework_id),
        "operator_id": str(operator_id),
        "type": "single_user",
    }

    first = await client.post(
        "/v1/admin/licenses",
        json=payload,
        headers=auth_headers(admin_id, ["admin"]),
    )
    duplicate = await client.post(
        "/v1/admin/licenses",
        json=payload,
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409


async def test_operator_download_requires_license_and_verified_kyc(
    client: AsyncClient,
    migrated_database: None,
    library_test_context: dict[str, Any],
) -> None:
    """Download gate enforces active license plus verified Operator KYC."""
    contributor_id = await create_user(
        "download-seller@auracles.space",
        ["contributor"],
    )
    no_license_id = await create_user("no-license@auracles.space", ["operator"])
    pending_id = await create_user(
        "pending-download@auracles.space",
        ["operator"],
        kyc_status="pending",
    )
    verified_id = await create_user("verified-download@auracles.space", ["operator"])
    framework_id, artifact_id = await create_published_framework_version(contributor_id)
    await grant_license_directly(framework_id, pending_id)
    await grant_license_directly(framework_id, verified_id)

    no_license = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/download",
        headers=auth_headers(no_license_id, ["operator"]),
    )
    pending = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/download",
        headers=auth_headers(pending_id, ["operator"]),
    )
    verified = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/download",
        headers=auth_headers(verified_id, ["operator"]),
    )

    assert no_license.status_code == 403
    assert pending.status_code == 403
    assert pending.json()["detail"] == {
        "error_code": "kyc_required",
        "onboarding_url": "/settings/onboarding",
    }
    assert verified.status_code == 200
    assert verified.json()["download_url"].startswith("https://s3.test/")

    async with async_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(ArtifactDownload))
    assert count == 1


async def test_license_version_blocks_download_of_newer_artifact(
    client: AsyncClient,
    migrated_database: None,
    library_test_context: dict[str, Any],
) -> None:
    """A v1 license cannot download a v2 Artifact outside its snapshot."""
    contributor_id = await create_user("version-seller@auracles.space", ["contributor"])
    operator_id = await create_user("version-operator@auracles.space", ["operator"])
    framework_id, _old_artifact_id = await create_published_framework_version(
        contributor_id
    )
    await grant_license_directly(framework_id, operator_id, version="1.0.0")
    new_artifact_id = await create_new_current_artifact_without_license_snapshot(
        framework_id
    )

    response = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{new_artifact_id}/download",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert response.status_code == 403


async def test_suspended_framework_download_still_works_for_existing_licensee(
    client: AsyncClient,
    migrated_database: None,
    library_test_context: dict[str, Any],
) -> None:
    """Suspension hides catalog access but does not revoke existing licenses."""
    contributor_id = await create_user(
        "suspended-seller@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user("suspended-operator@auracles.space", ["operator"])
    framework_id, artifact_id = await create_published_framework_version(
        contributor_id,
        status="suspended",
    )
    await grant_license_directly(framework_id, operator_id)

    response = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/download",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert response.status_code == 200
    assert response.json()["download_url"].startswith("https://s3.test/")
