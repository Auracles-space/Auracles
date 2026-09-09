"""Integration tests for org shared-library allocation and download routes."""

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
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    LicenseGrant,
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
    OrgMember,
    OrgTeam,
    OrgTeamMember,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


class FakeDownloadStorage:
    """S3 storage test double for org-library Artifact downloads."""

    def __init__(self) -> None:
        """Create empty fake S3 state."""
        self.presigned_get_requests: list[tuple[str, str, int]] = []

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Return a deterministic fake presigned GET URL."""
        self.presigned_get_requests.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist for org-library endpoint tests."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def org_library_context() -> AsyncIterator[dict[str, object]]:
    """Reset org-library rows and install fake S3 storage for each test."""
    from app.integrations import s3

    fake_storage = FakeDownloadStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-library rows in foreign-key-safe order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(LicenseGrant))
            await session.execute(delete(License))
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(ArtifactRarityAudit))
            await session.execute(delete(ArtifactPiiAudit))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgTeamMember))
            await session.execute(delete(OrgTeam))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    original_storage = s3.storage
    s3.storage = fake_storage
    try:
        yield {"storage": fake_storage}
    finally:
        s3.storage = original_storage
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> UUID:
    """Create and return one verified user id for org-library integration tests."""
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
    """Return bearer auth headers for a user."""
    token = create_access_token(user_id, [])
    return {"Authorization": f"Bearer {token}"}


async def _create_org(
    client: AsyncClient,
    user_id: UUID,
    prefix: str,
) -> dict[str, str]:
    """Create one organization via the API for a specific owner."""
    response = await client.post(
        "/v1/orgs",
        json={"slug": f"{prefix}-{uuid4().hex[:6]}", "name": prefix, "country": "GB"},
        headers=_auth_headers(user_id),
    )
    assert response.status_code == 201
    return response.json()


async def _add_member(org_id: UUID, user_id: UUID, *, role: str = "member") -> UUID:
    """Insert one org membership row directly and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return member.id


async def _create_framework_snapshot(contributor_id: UUID) -> tuple[UUID, UUID]:
    """Create one Framework, Artifact, and version snapshot for org-library tests."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                contributor_org_id=None,
                title="Org Library Framework",
                description="A licensed framework.",
                status="published",
                category="framework",
                price=Decimal("249.00"),
                currency="USD",
                license_types=["team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            artifact = Artifact(
                framework_id=framework.id,
                name="licensed.pdf",
                file_key=f"frameworks/{framework.id}/artifacts/licensed.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="processed",
                current_for_framework=True,
            )
            session.add(artifact)
            await session.flush()
            snapshot = FrameworkVersion(
                framework_id=framework.id,
                version="1.0.0",
                change_type="major",
                change_log="Published for org library tests.",
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
            return framework.id, artifact.id


async def _grant_org_license(framework_id: UUID, org_id: UUID) -> UUID:
    """Insert one active org-owned License row and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                framework_id=framework_id,
                operator_id=None,
                licensee_org_id=org_id,
                license_type="team",
                status="active",
                version_at_grant="1.0.0",
                seats_used=1,
                seats_total=10,
            )
            session.add(license_row)
            await session.flush()
            return license_row.id


async def test_org_admin_can_add_and_list_license_grants(
    client: AsyncClient,
    migrated_database: None,
    org_library_context: dict[str, object],
) -> None:
    """Org admins can allocate a License and list grants without exposing granted_by."""
    del migrated_database, org_library_context
    contributor_id = await _create_user("org-library-seller")
    owner_id = await _create_user("org-library-owner")
    member_user_id = await _create_user("org-library-member")
    org = await _create_org(client, owner_id, "org-library")
    member_id = await _add_member(UUID(org["id"]), member_user_id)
    framework_id, _artifact_id = await _create_framework_snapshot(contributor_id)
    license_id = await _grant_org_license(framework_id, UUID(org["id"]))

    unauthenticated = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants",
        json={"member_id": str(member_id)},
    )
    created = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants",
        json={"member_id": str(member_id)},
        headers=_auth_headers(owner_id),
    )
    listed = await client.get(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants",
        headers=_auth_headers(owner_id),
    )

    assert unauthenticated.status_code == 401
    assert created.status_code == 201
    body = created.json()
    assert body["license_id"] == str(license_id)
    assert body["member_id"] == str(member_id)
    assert body["team_id"] is None
    assert "granted_by" not in body

    assert listed.status_code == 200
    grants = listed.json()["grants"]
    assert len(grants) == 1
    assert grants[0]["member_id"] == str(member_id)
    assert "granted_by" not in grants[0]


async def test_org_library_lists_all_items_for_admin_and_only_granted_items_for_member(
    client: AsyncClient,
    migrated_database: None,
    org_library_context: dict[str, object],
) -> None:
    """Admins see the full org library; members see only Licenses granted to them."""
    del migrated_database, org_library_context
    contributor_id = await _create_user("org-library-seller")
    owner_id = await _create_user("org-library-owner")
    member_user_id = await _create_user("org-library-member")
    org = await _create_org(client, owner_id, "org-library")
    member_id = await _add_member(UUID(org["id"]), member_user_id)

    framework_one_id, _artifact_one_id = await _create_framework_snapshot(
        contributor_id
    )
    framework_two_id, _artifact_two_id = await _create_framework_snapshot(
        contributor_id
    )
    license_one_id = await _grant_org_license(framework_one_id, UUID(org["id"]))
    await _grant_org_license(framework_two_id, UUID(org["id"]))

    granted = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_one_id}/grants",
        json={"member_id": str(member_id)},
        headers=_auth_headers(owner_id),
    )
    assert granted.status_code == 201

    owner_library = await client.get(
        f"/v1/orgs/{org['id']}/library",
        headers=_auth_headers(owner_id),
    )
    member_library = await client.get(
        f"/v1/orgs/{org['id']}/library",
        headers=_auth_headers(member_user_id),
    )

    assert owner_library.status_code == 200
    assert member_library.status_code == 200
    assert len(owner_library.json()["items"]) == 2
    assert len(member_library.json()["items"]) == 1
    assert member_library.json()["items"][0]["license_id"] == str(license_one_id)
    assert "granted_by" not in str(member_library.json())


async def test_org_artifact_download_requires_grant_and_writes_member_audit_row(
    client: AsyncClient,
    migrated_database: None,
    org_library_context: dict[str, object],
) -> None:
    """Org download denies ungranted members, then writes per-user audit."""
    contributor_id = await _create_user("org-library-seller")
    owner_id = await _create_user("org-library-owner")
    member_user_id = await _create_user("org-library-member")
    org = await _create_org(client, owner_id, "org-library")
    member_id = await _add_member(UUID(org["id"]), member_user_id)
    framework_id, artifact_id = await _create_framework_snapshot(contributor_id)
    license_id = await _grant_org_license(framework_id, UUID(org["id"]))

    denied = await client.post(
        f"/v1/orgs/{org['id']}/library/{license_id}/artifacts/{artifact_id}/download",
        headers=_auth_headers(member_user_id),
    )
    assert denied.status_code == 403
    storage = org_library_context["storage"]
    assert isinstance(storage, FakeDownloadStorage)
    assert storage.presigned_get_requests == []

    granted = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants",
        json={"member_id": str(member_id)},
        headers=_auth_headers(owner_id),
    )
    assert granted.status_code == 201

    downloaded = await client.post(
        f"/v1/orgs/{org['id']}/library/{license_id}/artifacts/{artifact_id}/download",
        headers=_auth_headers(member_user_id),
    )

    assert downloaded.status_code == 200
    assert downloaded.json()["license_id"] == str(license_id)
    assert downloaded.json()["artifact_id"] == str(artifact_id)
    assert len(storage.presigned_get_requests) == 1

    async with async_session_factory() as session:
        row = await session.scalar(
            select(ArtifactDownload).where(ArtifactDownload.license_id == license_id)
        )
    assert row is not None
    assert row.user_id == member_user_id


async def test_org_grant_management_blocks_members_and_hides_other_org_licenses(
    client: AsyncClient,
    migrated_database: None,
    org_library_context: dict[str, object],
) -> None:
    """Grant routes are admin-only and hide other orgs' license namespaces."""
    del migrated_database, org_library_context
    contributor_id = await _create_user("org-library-seller")
    owner_id = await _create_user("org-library-owner")
    member_user_id = await _create_user("org-library-member")
    other_owner_id = await _create_user("org-library-other-owner")
    org = await _create_org(client, owner_id, "org-library")
    other_org = await _create_org(client, other_owner_id, "other-library")
    member_id = await _add_member(UUID(org["id"]), member_user_id)
    framework_id, _artifact_id = await _create_framework_snapshot(contributor_id)
    license_id = await _grant_org_license(framework_id, UUID(org["id"]))

    created = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants",
        json={"member_id": str(member_id)},
        headers=_auth_headers(owner_id),
    )
    assert created.status_code == 201
    grant_id = created.json()["id"]

    post_forbidden = await client.post(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants",
        json={"member_id": str(member_id)},
        headers=_auth_headers(member_user_id),
    )
    get_forbidden = await client.get(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants",
        headers=_auth_headers(member_user_id),
    )
    delete_forbidden = await client.delete(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants/{grant_id}",
        headers=_auth_headers(member_user_id),
    )
    cross_org = await client.get(
        f"/v1/orgs/{other_org['id']}/licenses/{license_id}/grants",
        headers=_auth_headers(other_owner_id),
    )
    deleted = await client.delete(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants/{grant_id}",
        headers=_auth_headers(owner_id),
    )
    listed = await client.get(
        f"/v1/orgs/{org['id']}/licenses/{license_id}/grants",
        headers=_auth_headers(owner_id),
    )

    assert post_forbidden.status_code == 403
    assert get_forbidden.status_code == 403
    assert delete_forbidden.status_code == 403
    assert cross_org.status_code == 404
    assert deleted.status_code == 204
    assert listed.status_code == 200
    assert listed.json()["grants"] == []
