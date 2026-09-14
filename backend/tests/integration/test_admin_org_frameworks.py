"""Integration tests proving org-owned Frameworks reach the admin surfaces.

An org-owned Framework has ``contributor_id IS NULL`` and ``contributor_org_id``
set (``ck_frameworks_seller_xor``). The admin directory, suspended list, and
moderation queues must still surface it — with the owning organization named —
rather than dropping it through an inner join to ``users``.

Maps to: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slice A.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.modules.organizations.models import Organization, OrgMember
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


def _admin_headers(user_id: UUID) -> dict[str, str]:
    """Create bearer auth headers for an admin user."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def _cleanup() -> None:
    """Delete rows created by these tests in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(ArtifactPiiAudit))
        await session.execute(delete(ArtifactRarityAudit))
        await session.execute(delete(Artifact))
        await session.execute(delete(Framework))
        await session.execute(delete(OrgMember))
        await session.execute(delete(Organization))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database schema is current for these tests."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def admin_org_frameworks_context() -> AsyncIterator[None]:
    """Reset the tables these tests touch before and after each test."""
    await engine.dispose()
    await _cleanup()
    try:
        yield
    finally:
        await _cleanup()
        await engine.dispose()


async def _create_user(
    session: AsyncSession,
    *,
    prefix: str,
    roles: list[str],
) -> User:
    """Create one verified user with approved roles inside the caller's session."""
    now = datetime.now(UTC)
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorse9"),
        display_name=prefix,
        email_verified=True,
        kyc_status="verified",
    )
    session.add(user)
    await session.flush()
    for role in roles:
        session.add(UserRole(user_id=user.id, role=role, approved_at=now))
    await session.flush()
    return user


async def _create_org(session: AsyncSession, *, owner: User, name: str) -> Organization:
    """Create one organization owned by ``owner`` inside the caller's session."""
    org = Organization(
        slug=f"org-{uuid4().hex[:8]}",
        name=name,
        country="GB",
        created_by=owner.id,
    )
    session.add(org)
    await session.flush()
    session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
    await session.flush()
    return org


def _framework(
    *,
    title: str,
    status: str,
    contributor_id: UUID | None = None,
    contributor_org_id: UUID | None = None,
) -> Framework:
    """Build one Framework row owned by either a Contributor or an organization."""
    return Framework(
        contributor_id=contributor_id,
        contributor_org_id=contributor_org_id,
        title=title,
        description="Admin org-framework fixture.",
        status=status,
        category="operations",
        sector="technology",
        industry="software",
        business_function="operations",
        tags=["org"],
        tags_text="org",
        price=Decimal("120.00"),
        currency="USD",
        license_types=["single_user"],
        pipeline_failure_reasons={},
        published_at=datetime.now(UTC) if status == "published" else None,
    )


async def test_admin_directory_lists_org_owned_frameworks(
    client: AsyncClient,
    migrated_database: None,
    admin_org_frameworks_context: None,
) -> None:
    """The admin directory must list a published org-owned Framework.

    The row names the organization and leaves the contributor fields null,
    while a Contributor-owned row leaves the organization fields null.
    """
    del migrated_database, admin_org_frameworks_context
    async with async_session_factory() as session:
        async with session.begin():
            admin = await _create_user(session, prefix="admin", roles=["admin"])
            owner = await _create_user(session, prefix="owner", roles=["operator"])
            solo = await _create_user(session, prefix="solo", roles=["contributor"])
            org = await _create_org(session, owner=owner, name="Acme Advisory")
            org_framework = _framework(
                title="Org Playbook",
                status="published",
                contributor_org_id=org.id,
            )
            solo_framework = _framework(
                title="Solo Playbook",
                status="published",
                contributor_id=solo.id,
            )
            session.add_all([org_framework, solo_framework])
            await session.flush()
            admin_id, org_id, solo_id = admin.id, org.id, solo.id
            org_framework_id, solo_framework_id = org_framework.id, solo_framework.id

    response = await client.get(
        "/v1/admin/frameworks", headers=_admin_headers(admin_id)
    )

    assert response.status_code == 200
    by_id = {item["framework_id"]: item for item in response.json()["items"]}
    assert str(org_framework_id) in by_id
    org_item = by_id[str(org_framework_id)]
    assert org_item["title"] == "Org Playbook"
    assert org_item["contributor_id"] is None
    assert org_item["contributor_name"] is None
    assert org_item["organization_id"] == str(org_id)
    assert org_item["organization_name"] == "Acme Advisory"

    solo_item = by_id[str(solo_framework_id)]
    assert solo_item["contributor_id"] == str(solo_id)
    assert solo_item["contributor_name"] == "solo"
    assert solo_item["organization_id"] is None
    assert solo_item["organization_name"] is None


async def test_admin_suspended_list_includes_org_owned_frameworks(
    client: AsyncClient,
    migrated_database: None,
    admin_org_frameworks_context: None,
) -> None:
    """A suspended org-owned Framework appears in the suspended list with its org."""
    del migrated_database, admin_org_frameworks_context
    async with async_session_factory() as session:
        async with session.begin():
            admin = await _create_user(session, prefix="admin", roles=["admin"])
            owner = await _create_user(session, prefix="owner", roles=["operator"])
            org = await _create_org(session, owner=owner, name="Acme Advisory")
            framework = _framework(
                title="Suspended Org Playbook",
                status="suspended",
                contributor_org_id=org.id,
            )
            framework.rejection_reason = "Takedown request."
            session.add(framework)
            await session.flush()
            admin_id, org_id, framework_id = admin.id, org.id, framework.id

    response = await client.get(
        "/v1/admin/frameworks/suspended", headers=_admin_headers(admin_id)
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["framework_id"] for item in items] == [str(framework_id)]
    assert items[0]["contributor_id"] is None
    assert items[0]["contributor_name"] is None
    assert items[0]["organization_id"] == str(org_id)
    assert items[0]["organization_name"] == "Acme Advisory"
    assert items[0]["reason"] == "Takedown request."


async def test_admin_moderation_queues_include_org_owned_frameworks(
    client: AsyncClient,
    migrated_database: None,
    admin_org_frameworks_context: None,
) -> None:
    """Rarity, near-duplicate, and PII queues each surface an org-owned Framework."""
    del migrated_database, admin_org_frameworks_context
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            admin = await _create_user(session, prefix="admin", roles=["admin"])
            owner = await _create_user(session, prefix="owner", roles=["operator"])
            org = await _create_org(session, owner=owner, name="Acme Advisory")
            rarity_framework = _framework(
                title="Org Rarity Playbook",
                status="pipeline_failed",
                contributor_org_id=org.id,
            )
            pii_framework = _framework(
                title="Org PII Playbook",
                status="pipeline_failed",
                contributor_org_id=org.id,
            )
            session.add_all([rarity_framework, pii_framework])
            await session.flush()

            rarity_artifact = Artifact(
                framework_id=rarity_framework.id,
                name="org-rarity.pdf",
                file_key="frameworks/org-rarity/original.pdf",
                file_size=1024,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="flagged_rarity",
                current_for_framework=True,
                created_at=now - timedelta(hours=2),
            )
            pii_artifact = Artifact(
                framework_id=pii_framework.id,
                name="org-pii.pdf",
                file_key="frameworks/org-pii/original.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="flagged_pii",
                pii_detected=True,
                pii_review_needed=True,
                current_for_framework=True,
                created_at=now - timedelta(hours=1),
            )
            session.add_all([rarity_artifact, pii_artifact])
            await session.flush()
            # Blocking the rarity artifact promotes it into the near-duplicate
            # queue as well, so one fixture exercises both rarity queues.
            rarity_framework.pipeline_failure_reasons = {
                "internal_rarity": [str(rarity_artifact.id)]
            }
            session.add_all(
                [
                    ArtifactRarityAudit(
                        artifact_id=rarity_artifact.id,
                        internal_jaccard=Decimal("0.9500"),
                        blended_score=Decimal("0.1200"),
                        external_phrases_queried=[],
                        external_hit_counts=[],
                        created_at=now - timedelta(hours=2),
                    ),
                    ArtifactPiiAudit(
                        artifact_id=pii_artifact.id,
                        pii_types_found=["email"],
                        auto_redacted=False,
                        flagged_for_review=True,
                        processed_at=now - timedelta(hours=1),
                    ),
                ]
            )
            admin_id, org_id = admin.id, org.id
            rarity_framework_id, pii_framework_id = (
                rarity_framework.id,
                pii_framework.id,
            )

    response = await client.get(
        "/v1/admin/moderation/queue", headers=_admin_headers(admin_id)
    )

    assert response.status_code == 200
    body = response.json()
    by_type = {item["queue_type"]: item for item in body["items"]}
    assert set(by_type) == {"rarity_review", "near_duplicate_block", "pii_review"}
    assert by_type["rarity_review"]["framework_id"] == str(rarity_framework_id)
    assert by_type["near_duplicate_block"]["framework_id"] == str(rarity_framework_id)
    assert by_type["pii_review"]["framework_id"] == str(pii_framework_id)
    for item in body["items"]:
        assert item["contributor_id"] is None
        assert item["contributor_name"] is None
        assert item["organization_id"] == str(org_id)
        assert item["organization_name"] == "Acme Advisory"
