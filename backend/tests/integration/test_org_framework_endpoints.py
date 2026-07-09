"""Integration tests for organization-scoped Framework endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

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
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.shared.models.audit_log import AuditLog
from tests.integration.test_frameworks_crud import FakeArtifactStorage, FakeRedis
from tests.integration.test_organizations_endpoints import (
    add_member,
    auth,
    create_org,
    create_user,
    migrated_database,
)

pytestmark = pytest.mark.asyncio
__all__ = ["migrated_database"]


@pytest.fixture
async def org_framework_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset org/framework state and install fake Redis plus fake S3 storage."""
    from app.integrations import s3

    fake_storage = FakeArtifactStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete framework and organization rows in foreign-key-safe order."""
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
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
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


async def _activate_contributor_capability(org_id: str) -> None:
    """Persist an active contributor capability for one organization."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=UUID(org_id),
                    capability="contributor",
                    status="active",
                )
            )


async def _seed_publishable_framework(
    framework_id: str,
    *,
    storage: FakeArtifactStorage,
) -> None:
    """Attach one clean current artifact and set the Framework to pipeline_passed."""
    file_key = f"frameworks/{framework_id}/artifacts/publishable.pdf"
    storage.existing_keys.add(file_key)
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Artifact(
                    framework_id=UUID(framework_id),
                    name="publishable.pdf",
                    file_key=file_key,
                    file_size=2048,
                    mime_type="application/pdf",
                    scan_status="clean",
                    processing_status="processed",
                    pii_detected=False,
                    pii_review_needed=False,
                    current_for_framework=True,
                )
            )
            framework = await session.get(Framework, UUID(framework_id))
            assert framework is not None
            framework.status = "pipeline_passed"
            framework.pipeline_failure_reasons = {}


def _valid_framework_payload() -> dict[str, Any]:
    """Return a valid framework creation request body."""
    return {
        "title": "Org Framework",
        "description": "A contributor framework authored under an organization.",
        "category": "framework",
        "sector": "financial_services",
        "industry": "fund_management",
        "function": "risk_management",
        "tags": ["org", "framework"],
        "jurisdiction": "GB",
        "complexity": 3,
        "org_size": "mid_market",
        "lifecycle_stage": "scale",
        "pricing": {
            "price": "499.00",
            "currency": "USD",
            "license_types": ["single_user"],
            "commercial_rights": "Internal commercial use allowed.",
            "usage_restrictions": "No resale.",
        },
    }


async def test_org_member_can_create_framework_under_org_identity(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """A plain org member can create a Framework under the org seller identity."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["contributor_id"] is None
    assert body["contributor_org_id"] == org["id"]

    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(body["id"]))

    assert framework is not None
    assert framework.contributor_id is None
    assert framework.contributor_org_id == UUID(str(org["id"]))
    assert framework.authoring_member_id == member_row_id


async def test_org_publish_requires_admin_role(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member cannot publish an org Framework, while an admin can."""
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    from app.core.security import create_access_token
    from app.modules.frameworks import service as framework_service

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-publish")
    await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )
    assert created.status_code == 201
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id,
        storage=org_framework_test_context["storage"],
    )

    async def _noop_pipeline(*args: object, **kwargs: object) -> None:
        return None

    async def _noop_index(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        framework_service,
        "evaluate_framework_pipeline",
        _noop_pipeline,
    )
    monkeypatch.setattr(framework_service, "index_framework_artifacts", _noop_index)

    forbidden = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/publish",
        headers=auth(member_token),
    )
    allowed = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/publish",
        headers=auth(owner_token),
    )

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "published"


async def test_org_member_can_list_and_read_own_frameworks_only(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Members can list and read their org Frameworks, but not another org's."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    outsider_id = await create_user("org-framework-outsider")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    outsider_token = create_access_token(outsider_id, [])

    org = await create_org(client, owner_token, "org-framework-read")
    await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    other_org = await create_org(client, outsider_token, "org-framework-other")
    await _activate_contributor_capability(str(other_org["id"]))

    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )
    assert created.status_code == 201
    framework_id = created.json()["id"]

    listed = await client.get(
        f"/v1/orgs/{org['id']}/frameworks",
        headers=auth(member_token),
    )
    detailed = await client.get(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}",
        headers=auth(member_token),
    )
    cross_org = await client.get(
        f"/v1/orgs/{other_org['id']}/frameworks/{framework_id}",
        headers=auth(outsider_token),
    )

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == framework_id
    assert detailed.status_code == 200
    assert detailed.json()["id"] == framework_id
    assert cross_org.status_code == 404


async def test_org_member_can_upload_confirm_and_submit_framework(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org member can upload artifacts and submit an org-owned Framework."""
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    from app.core.security import create_access_token
    from app.modules.frameworks import service as framework_service

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-submit")
    await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )
    assert created.status_code == 201
    framework_id = created.json()["id"]

    upload = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "artifact.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=auth(member_token),
    )
    assert upload.status_code == 200
    org_framework_test_context["storage"].existing_keys.add(upload.json()["file_key"])

    confirm = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts/confirm",
        json={"artifact_id": upload.json()["artifact_id"]},
        headers=auth(member_token),
    )
    assert confirm.status_code == 200

    async def _noop_pipeline(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        framework_service,
        "evaluate_framework_pipeline",
        _noop_pipeline,
    )

    submit = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/submit",
        headers=auth(member_token),
    )

    assert submit.status_code == 200
    assert submit.json()["status"] == "submitted"


async def test_org_member_can_edit_metadata_but_only_admin_can_change_pricing(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Metadata edits are member-level, while pricing changes are admin-only."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-edit")
    await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )
    assert created.status_code == 201
    framework_id = created.json()["id"]

    metadata_update = await client.patch(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}",
        json={"title": "Updated Org Framework"},
        headers=auth(member_token),
    )
    pricing_forbidden = await client.patch(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/pricing",
        json={
            "pricing": {
                "price": "799.00",
                "currency": "USD",
                "license_types": ["team"],
                "commercial_rights": "Internal commercial use allowed.",
                "usage_restrictions": "No resale.",
            }
        },
        headers=auth(member_token),
    )
    pricing_allowed = await client.patch(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/pricing",
        json={
            "pricing": {
                "price": "799.00",
                "currency": "USD",
                "license_types": ["team"],
                "commercial_rights": "Internal commercial use allowed.",
                "usage_restrictions": "No resale.",
            }
        },
        headers=auth(owner_token),
    )

    assert metadata_update.status_code == 200
    assert metadata_update.json()["title"] == "Updated Org Framework"
    assert pricing_forbidden.status_code == 403
    assert pricing_allowed.status_code == 200
    assert pricing_allowed.json()["pricing"]["price"] == "799.00"


async def test_org_admin_can_unpublish_and_start_new_version(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """An org admin can unpublish a Framework and start a new draft version."""
    owner_id = await create_user("org-framework-owner")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-framework-version")
    await _activate_contributor_capability(str(org["id"]))

    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(owner_token),
    )
    assert created.status_code == 201
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id,
        storage=org_framework_test_context["storage"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = await session.get(Framework, UUID(framework_id))
            assert framework is not None
            framework.status = "published"

    async with async_session_factory() as session:
        artifact_id = await session.scalar(
            select(Artifact.id).where(
                Artifact.framework_id == UUID(framework_id),
                Artifact.current_for_framework.is_(True),
            )
        )
    assert artifact_id is not None

    unpublished = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/unpublish",
        headers=auth(owner_token),
    )
    versioned = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/version",
        json={
            "change_type": "improvement",
            "change_log": "Refresh for a new release.",
            "artifact_inheritance": {str(artifact_id): True},
        },
        headers=auth(owner_token),
    )

    assert unpublished.status_code == 200
    assert unpublished.json()["status"] == "unpublished"
    assert versioned.status_code == 200
    assert versioned.json()["status"] == "draft"
    assert versioned.json()["version"] == "1.1.0"


async def test_org_framework_create_enforces_auth_membership_and_capability(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Org framework create requires auth, membership, and active capability."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-owner")
    outsider_id = await create_user("org-framework-outsider")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    outsider_token = create_access_token(outsider_id, [])
    org = await create_org(client, owner_token, "org-framework-guards")

    unauthenticated = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
    )
    non_member = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(outsider_token),
    )
    inactive_capability = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(owner_token),
    )

    assert unauthenticated.status_code == 401
    assert non_member.status_code == 403
    assert inactive_capability.status_code == 403
