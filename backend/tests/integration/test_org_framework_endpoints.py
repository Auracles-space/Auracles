"""Integration tests for organization-scoped Framework endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
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
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgTeam,
    OrgTeamCapability,
    OrgTeamMember,
)
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


async def _grant_contributor_to_member(org_id: str, member_id: UUID) -> None:
    """Place one member on a team with the contributor capability enabled."""
    async with async_session_factory() as session:
        async with session.begin():
            team = OrgTeam(org_id=UUID(org_id), name="Contributors")
            session.add(team)
            await session.flush()
            session.add(OrgTeamMember(team_id=team.id, member_id=member_id))
            session.add(OrgTeamCapability(team_id=team.id, capability="contributor"))


async def _seed_publishable_framework(
    framework_id: str,
    *,
    storage: FakeArtifactStorage,
) -> None:
    """Attach one clean current artifact and set the Framework to pipeline_passed.

    Also designates the artifact as the preview so the Framework satisfies the
    publish-time preview requirement, matching a realistically publishable draft.
    """
    file_key = f"frameworks/{framework_id}/artifacts/publishable.pdf"
    storage.existing_keys.add(file_key)
    async with async_session_factory() as session:
        async with session.begin():
            artifact = Artifact(
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
            session.add(artifact)
            await session.flush()
            framework = await session.get(Framework, UUID(framework_id))
            assert framework is not None
            framework.status = "pipeline_passed"
            framework.pipeline_failure_reasons = {}
            framework.preview_artifact_id = artifact.id


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
    """A contributor-team member can create a Framework under the org identity."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)

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


async def test_plain_member_cannot_create_org_framework(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """A member outside contributor teams is denied when authoring a Framework."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-ungranted-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-ungranted")
    await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "capability_grant_required"


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
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)

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
    """Contributor-team members can read their org Frameworks, not another org's."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    outsider_id = await create_user("org-framework-outsider")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    outsider_token = create_access_token(outsider_id, [])

    org = await create_org(client, owner_token, "org-framework-read")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)

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
    """A contributor-team member can upload artifacts and submit a Framework."""
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    from app.core.security import create_access_token
    from app.modules.frameworks import service as framework_service

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-submit")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)

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


async def test_org_list_artifacts_endpoint(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Contributor-authorized members can list current org Framework artifacts."""
    owner_id = await create_user("org-framework-artifact-list-owner")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-framework-artifact-list")
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

    response = await client.get(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts",
        headers=auth(owner_token),
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["framework_id"] == framework_id


async def test_org_list_artifacts_denied_for_plain_member(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Members without contributor grants cannot list org Framework artifacts."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-artifact-list-owner")
    member_id = await create_user("org-framework-artifact-list-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-artifact-denied")
    await _activate_contributor_capability(str(org["id"]))
    await add_member(str(org["id"]), member_id, "member")
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(owner_token),
    )
    assert created.status_code == 201

    response = await client.get(
        f"/v1/orgs/{org['id']}/frameworks/{created.json()['id']}/artifacts",
        headers=auth(member_token),
    )

    assert response.status_code == 403


async def test_org_member_can_delete_artifact(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """A contributor-team member can delete an artifact from an org Framework.

    Regression for the org authoring gap where delete_artifact routed through
    the personal-ownership endpoint and 404'd on an org-owned Framework.
    """
    owner_id = await create_user("org-framework-artifact-delete-owner")
    member_id = await create_user("org-framework-artifact-delete-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-artifact-delete")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)

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

    listed = await client.get(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts",
        headers=auth(member_token),
    )
    assert listed.status_code == 200
    artifact_id = listed.json()[0]["id"]

    deleted = await client.delete(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts/{artifact_id}",
        headers=auth(member_token),
    )

    assert deleted.status_code == 204

    remaining = await client.get(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts",
        headers=auth(member_token),
    )
    assert remaining.status_code == 200
    assert remaining.json() == []


async def test_org_delete_artifact_denied_for_plain_member(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Members without a contributor grant cannot delete org Framework artifacts."""
    owner_id = await create_user("org-framework-artifact-delete-denied-owner")
    member_id = await create_user("org-framework-artifact-delete-denied-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-artifact-delete-denied")
    await _activate_contributor_capability(str(org["id"]))
    await add_member(str(org["id"]), member_id, "member")
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
    listed = await client.get(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts",
        headers=auth(owner_token),
    )
    artifact_id = listed.json()[0]["id"]

    response = await client.delete(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts/{artifact_id}",
        headers=auth(member_token),
    )

    assert response.status_code == 403


async def test_org_member_can_set_preview_artifact(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """A contributor-team member can set the preview on an org draft Framework.

    Regression for the org authoring gap where set_preview_artifact routed
    through the personal-ownership endpoint and 404'd on an org-owned Framework.
    """
    owner_id = await create_user("org-framework-preview-owner")
    member_id = await create_user("org-framework-preview-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-preview")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)

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
    # Preview selection is draft-gated; the seed leaves the Framework in
    # pipeline_passed, so return it to draft with the processed artifact intact.
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Framework)
                .where(Framework.id == UUID(framework_id))
                .values(status="draft")
            )

    listed = await client.get(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts",
        headers=auth(member_token),
    )
    assert listed.status_code == 200
    artifact_id = listed.json()[0]["id"]

    response = await client.patch(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=auth(member_token),
    )

    assert response.status_code == 200
    assert response.json()["preview_artifact_id"] == artifact_id


async def test_org_set_preview_artifact_denied_for_plain_member(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Members without a contributor grant cannot set an org Framework preview."""
    owner_id = await create_user("org-framework-preview-denied-owner")
    member_id = await create_user("org-framework-preview-denied-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-preview-denied")
    await _activate_contributor_capability(str(org["id"]))
    await add_member(str(org["id"]), member_id, "member")
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
            await session.execute(
                update(Framework)
                .where(Framework.id == UUID(framework_id))
                .values(status="draft")
            )
    listed = await client.get(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/artifacts",
        headers=auth(owner_token),
    )
    artifact_id = listed.json()[0]["id"]

    response = await client.patch(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=auth(member_token),
    )

    assert response.status_code == 403


async def _seed_flagged_artifact(framework_id: str) -> str:
    """Flag the seeded artifact for PII review and fail the Framework's gate.

    Returns the flagged Artifact's id.
    """
    async with async_session_factory() as session:
        async with session.begin():
            artifact = await session.scalar(
                select(Artifact).where(Artifact.framework_id == UUID(framework_id))
            )
            assert artifact is not None
            artifact.processing_status = "flagged_pii"
            artifact.pii_detected = True
            artifact.pii_review_needed = True
            framework = await session.get(Framework, UUID(framework_id))
            assert framework is not None
            framework.status = "pipeline_failed"
            framework.pipeline_failure_reasons = {"pii": [str(artifact.id)]}
            return str(artifact.id)


async def test_org_member_can_resolve_pii_review(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contributor-team member can re-run PII review on an org Framework.

    Regression for the org authoring gap where resolve_pii_review routed
    through the personal-ownership endpoint and 404'd on an org-owned Framework.
    """
    dispatched: list[str] = []

    class FakeScanTask:
        """Celery task double recording scan dispatches."""

        def delay(self, artifact_id: str) -> None:
            """Record a scan dispatch instead of touching Celery."""
            dispatched.append(artifact_id)

    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        FakeScanTask(),
        raising=False,
    )
    owner_id = await create_user("org-pii-resolve-owner")
    member_id = await create_user("org-pii-resolve-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-pii-resolve")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id, storage=org_framework_test_context["storage"]
    )
    artifact_id = await _seed_flagged_artifact(framework_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}"
        f"/artifacts/{artifact_id}/resolve-pii-review",
        headers=auth(member_token),
    )

    assert response.status_code == 200
    assert response.json()["pii_review_needed"] is False
    assert dispatched == [artifact_id]


async def test_org_resolve_pii_review_denied_for_plain_member(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Members without a contributor grant cannot resolve org PII review."""
    owner_id = await create_user("org-pii-resolve-denied-owner")
    member_id = await create_user("org-pii-resolve-denied-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-pii-resolve-denied")
    await _activate_contributor_capability(str(org["id"]))
    await add_member(str(org["id"]), member_id, "member")
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(owner_token),
    )
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id, storage=org_framework_test_context["storage"]
    )
    artifact_id = await _seed_flagged_artifact(framework_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}"
        f"/artifacts/{artifact_id}/resolve-pii-review",
        headers=auth(member_token),
    )

    assert response.status_code == 403


async def test_org_member_can_accept_redaction(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contributor-team member can accept a redacted copy on an org Framework."""
    dispatched: list[str] = []

    class FakeProcessTask:
        """Celery task double recording processing dispatches."""

        def delay(self, artifact_id: str) -> None:
            """Record a process dispatch instead of touching Celery."""
            dispatched.append(artifact_id)

    monkeypatch.setattr(
        "app.modules.frameworks.service.process_artifact",
        FakeProcessTask(),
        raising=False,
    )
    owner_id = await create_user("org-redaction-owner")
    member_id = await create_user("org-redaction-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-redaction")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id, storage=org_framework_test_context["storage"]
    )
    artifact_id = await _seed_flagged_artifact(framework_id)
    clean_file_key = f"frameworks/{framework_id}/artifacts/{artifact_id}/redacted/a.pdf"
    async with async_session_factory() as session:
        async with session.begin():
            artifact = await session.get(Artifact, UUID(artifact_id))
            assert artifact is not None
            artifact.clean_file_key = clean_file_key
            artifact.metadata_vector = {
                "redaction": {"status": "generated", "clean_file_key": clean_file_key}
            }

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}"
        f"/artifacts/{artifact_id}/accept-redaction",
        headers=auth(member_token),
    )

    assert response.status_code == 200
    assert response.json()["pii_review_needed"] is False
    assert dispatched == [artifact_id]


async def test_org_relist_endpoint_admin(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org owner can relist a delisted organization Framework."""
    owner_id = await create_user("org-framework-relist-owner")
    from app.core.security import create_access_token
    from app.modules.frameworks import service as framework_service

    async def _noop_index(*args: object, **kwargs: object) -> None:
        """Avoid external indexing while asserting the relist response."""
        return None

    monkeypatch.setattr(framework_service, "index_framework_artifacts", _noop_index)
    owner_token = create_access_token(owner_id, [])
    org = await create_org(client, owner_token, "org-framework-relist")
    await _activate_contributor_capability(str(org["id"]))
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(owner_token),
    )
    assert created.status_code == 201
    framework_id = UUID(created.json()["id"])
    async with async_session_factory() as session:
        async with session.begin():
            framework = await session.get(Framework, framework_id)
            assert framework is not None
            framework.status = "unpublished"

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/relist",
        headers=auth(owner_token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"


async def test_org_relist_denied_for_non_admin(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """A non-admin member cannot relist an organization Framework."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-relist-owner")
    member_id = await create_user("org-framework-relist-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-relist-denied")
    await _activate_contributor_capability(str(org["id"]))
    await add_member(str(org["id"]), member_id, "member")
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(owner_token),
    )
    assert created.status_code == 201

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{created.json()['id']}/relist",
        headers=auth(member_token),
    )

    assert response.status_code == 403


@pytest.mark.parametrize("blocked_state", ["pii", "virus", "missing_file"])
async def test_org_relist_rejects_artifact_trust_gate_failures(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
    blocked_state: str,
) -> None:
    """Org relist returns 409 for PII, virus, and missing-file blockers."""
    owner_id = await create_user(f"org-framework-relist-{blocked_state}")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    org = await create_org(
        client,
        owner_token,
        f"org-relist-{blocked_state.replace('_', '-')}",
    )
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
    file_key = f"frameworks/{framework_id}/artifacts/publishable.pdf"

    async with async_session_factory() as session:
        async with session.begin():
            framework = await session.get(Framework, UUID(framework_id))
            artifact = await session.scalar(
                select(Artifact).where(Artifact.framework_id == UUID(framework_id))
            )
            assert framework is not None and artifact is not None
            framework.status = "unpublished"
            if blocked_state == "pii":
                artifact.processing_status = "flagged_pii"
                artifact.pii_review_needed = True
            elif blocked_state == "virus":
                artifact.scan_status = "infected"

    if blocked_state == "missing_file":
        org_framework_test_context["storage"].existing_keys.discard(file_key)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/relist",
        headers=auth(owner_token),
    )

    assert response.status_code == 409
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
    assert framework is not None
    assert framework.status == "unpublished"


async def test_org_member_can_edit_metadata_but_only_admin_can_change_pricing(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Team-granted metadata edits remain distinct from admin-only pricing."""
    del org_framework_test_context
    owner_id = await create_user("org-framework-owner")
    member_id = await create_user("org-framework-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-framework-edit")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)

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
                "license_types": ["single_user", "team"],
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
                "license_types": ["single_user", "team"],
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


async def _seed_rarity_soft_fail(framework_id: str) -> str:
    """Fail the seeded Framework on an external-rarity soft check.

    Sets a low external rarity and the ``external_check`` failure reason so the
    Framework sits at ``pipeline_failed`` awaiting Contributor acknowledgement.
    Returns the Artifact's id.
    """
    async with async_session_factory() as session:
        async with session.begin():
            artifact = await session.scalar(
                select(Artifact).where(Artifact.framework_id == UUID(framework_id))
            )
            assert artifact is not None
            artifact.processing_status = "processed"
            artifact.internal_rarity = Decimal("1.0000")
            artifact.external_rarity = Decimal("0.2000")
            artifact.rarity_score = Decimal("0.2000")
            framework = await session.get(Framework, UUID(framework_id))
            assert framework is not None
            framework.status = "pipeline_failed"
            framework.pipeline_failure_reasons = {"external_check": "unavailable"}
            return str(artifact.id)


async def _seed_similarity_notice(framework_id: str) -> str:
    """Attach a non-blocking similarity notice to the seeded Artifact.

    Returns the Artifact's id.
    """
    async with async_session_factory() as session:
        async with session.begin():
            artifact = await session.scalar(
                select(Artifact).where(Artifact.framework_id == UUID(framework_id))
            )
            assert artifact is not None
            artifact.metadata_vector = {
                "similarity_notice": {
                    "average_review_score": "4.50",
                    "jaccard": "0.8000",
                    "nearest_match_artifact_id": str(UUID(int=1)),
                    "nearest_match_framework_id": str(UUID(int=2)),
                    "nearest_match_title": "Published Risk Framework",
                    "review_count": 2,
                }
            }
            return str(artifact.id)


async def test_org_member_can_acknowledge_soft_fail(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """A contributor-team member can acknowledge an org rarity soft fail.

    Regression for the org authoring gap where acknowledge_soft_fail routed
    through the personal-ownership endpoint and 404'd on an org-owned Framework.
    """
    owner_id = await create_user("org-softfail-owner")
    member_id = await create_user("org-softfail-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-softfail")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id, storage=org_framework_test_context["storage"]
    )
    await _seed_rarity_soft_fail(framework_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/acknowledge-soft-fail",
        headers=auth(member_token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pipeline_passed"


async def test_org_acknowledge_soft_fail_denied_for_plain_member(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Members without a contributor grant cannot acknowledge an org soft fail."""
    owner_id = await create_user("org-softfail-denied-owner")
    member_id = await create_user("org-softfail-denied-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-softfail-denied")
    await _activate_contributor_capability(str(org["id"]))
    await add_member(str(org["id"]), member_id, "member")
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(owner_token),
    )
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id, storage=org_framework_test_context["storage"]
    )
    await _seed_rarity_soft_fail(framework_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}/acknowledge-soft-fail",
        headers=auth(member_token),
    )

    assert response.status_code == 403


async def test_org_member_can_acknowledge_similarity_notice(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """A contributor-team member can acknowledge an org similarity notice.

    Regression for the org authoring gap where acknowledge_similarity_notice
    routed through the personal-ownership endpoint and 404'd on org Frameworks.
    """
    owner_id = await create_user("org-similarity-owner")
    member_id = await create_user("org-similarity-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-similarity")
    member_row_id = await add_member(str(org["id"]), member_id, "member")
    await _activate_contributor_capability(str(org["id"]))
    await _grant_contributor_to_member(str(org["id"]), member_row_id)
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(member_token),
    )
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id, storage=org_framework_test_context["storage"]
    )
    await _seed_similarity_notice(framework_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}"
        f"/similarity-notice/acknowledge",
        json={"differentiation_note": "Distinct implementation focus and sector."},
        headers=auth(member_token),
    )

    assert response.status_code == 200


async def test_org_acknowledge_similarity_notice_denied_for_plain_member(
    client: AsyncClient,
    org_framework_test_context: dict[str, Any],
) -> None:
    """Members without a contributor grant cannot ack an org similarity notice."""
    owner_id = await create_user("org-similarity-denied-owner")
    member_id = await create_user("org-similarity-denied-member")
    from app.core.security import create_access_token

    owner_token = create_access_token(owner_id, [])
    member_token = create_access_token(member_id, [])
    org = await create_org(client, owner_token, "org-similarity-denied")
    await _activate_contributor_capability(str(org["id"]))
    await add_member(str(org["id"]), member_id, "member")
    created = await client.post(
        f"/v1/orgs/{org['id']}/frameworks",
        json=_valid_framework_payload(),
        headers=auth(owner_token),
    )
    framework_id = created.json()["id"]
    await _seed_publishable_framework(
        framework_id, storage=org_framework_test_context["storage"]
    )
    await _seed_similarity_notice(framework_id)

    response = await client.post(
        f"/v1/orgs/{org['id']}/frameworks/{framework_id}"
        f"/similarity-notice/acknowledge",
        json={"differentiation_note": "Distinct implementation focus and sector."},
        headers=auth(member_token),
    )

    assert response.status_code == 403
