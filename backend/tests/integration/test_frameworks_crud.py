"""Integration tests for contributor Framework draft CRUD.

These tests exercise the public `/v1/frameworks` API introduced in Phase 2
Slice 2. They intentionally verify observable behavior through FastAPI instead
of coupling to service internals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

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
from app.modules.financials.models import Payout, PayoutAccount, Transaction
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
    """Minimal Redis override for authenticated framework routes."""


class FakeArtifactStorage:
    """S3 storage test double for artifact upload URL and object checks."""

    def __init__(self) -> None:
        """Create empty fake S3 state."""
        self.existing_keys: set[str] = set()
        self.presigned_requests: list[tuple[str, str, str, int, int]] = []
        self.copy_requests: list[tuple[str, str, str, str]] = []

    def presigned_post(
        self,
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Return a deterministic fake artifact presigned POST policy."""
        self.presigned_requests.append((bucket, key, mime_type, max_size, expires_in))
        return {
            "url": f"https://s3.test/{bucket}",
            "fields": {
                "key": key,
                "Content-Type": mime_type,
                "policy": "fake-policy",
                "x-amz-signature": "fake-signature",
            },
        }

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return whether the fake object was marked uploaded."""
        return key in self.existing_keys

    def copy_object(
        self,
        source_bucket: str,
        source_key: str,
        destination_bucket: str,
        destination_key: str,
    ) -> None:
        """Record a copy and mark the destination object as present."""
        self.copy_requests.append(
            (source_bucket, source_key, destination_bucket, destination_key)
        )
        self.existing_keys.add(destination_key)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 2 marketplace tables exist for endpoint tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def framework_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset framework/auth state and install lightweight dependency overrides."""
    from app.integrations import s3
    fake_storage = FakeArtifactStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Remove marketplace rows before deleting users in test isolation."""
        async with async_session_factory() as session:
            await session.execute(
                update(Framework).values(preview_artifact_id=None)
            )
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(License))
            await session.execute(delete(Payout))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Transaction))
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


async def create_user_with_roles(
    email: str,
    roles: list[str],
    *,
    kyc_status: str = "verified",
    display_name: str | None = None,
) -> UUID:
    """Create an email-verified user with approved non-attestor roles."""
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


def valid_framework_payload() -> dict[str, Any]:
    """Return a valid draft Framework creation payload."""
    return {
        "title": "Board Risk Operating System",
        "description": "A board-ready governance framework for risk operations.",
        "category": "framework",
        "sector": "financial_services",
        "industry": "fund_management",
        "function": "risk_management",
        "tags": ["risk", "board", "governance"],
        "jurisdiction": "us",
        "complexity": 3,
        "org_size": "mid_market",
        "lifecycle_stage": "scale",
        "pricing": {
            "price": "499.00",
            "currency": "USD",
            "license_types": ["single_user", "team"],
            "commercial_rights": "Internal commercial use allowed.",
            "usage_restrictions": "No resale.",
        },
    }


async def create_draft_framework(
    client: AsyncClient,
    contributor_id: UUID,
) -> str:
    """Create a valid draft Framework through the public API and return its id."""
    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    assert response.status_code == 201
    return str(response.json()["id"])


async def create_artifact_for_framework(
    client: AsyncClient,
    contributor_id: UUID,
    framework_id: str,
    *,
    filename: str = "pipeline.pdf",
) -> str:
    """Create one Artifact row through the public upload-url endpoint."""
    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": filename,
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    assert response.status_code == 200
    return str(response.json()["artifact_id"])


async def mark_artifact_pipeline_state(
    framework_id: str,
    artifact_id: str,
    *,
    scan_status: str = "clean",
    processing_status: str = "processed",
    pii_detected: bool = False,
    pii_review_needed: bool = False,
    internal_rarity: Decimal | None = Decimal("1.0000"),
    external_rarity: Decimal | None = Decimal("1.0000"),
) -> None:
    """Persist pipeline fields that normally come from Celery workers."""
    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert artifact is not None
        artifact.scan_status = scan_status
        artifact.processing_status = processing_status
        artifact.pii_detected = pii_detected
        artifact.pii_review_needed = pii_review_needed
        artifact.internal_rarity = internal_rarity
        artifact.external_rarity = external_rarity
        artifact.rarity_score = internal_rarity
        await session.execute(
            delete(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == UUID(artifact_id)
            )
        )
        session.add(
            ArtifactRarityAudit(
                artifact_id=UUID(artifact_id),
                internal_jaccard=Decimal("0.0000"),
                external_phrases_queried=[],
                external_hit_counts=[],
                blended_score=internal_rarity,
            )
        )
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.pipeline_failure_reasons = {}
        await session.commit()


async def test_verified_contributor_can_create_draft_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Verified Contributors can create Framework drafts."""
    contributor_id = await create_user_with_roles(
        "creator@auracles.space",
        ["contributor"],
    )

    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Board Risk Operating System"
    assert body["status"] == "draft"
    assert body["version"] == "1.0.0"
    assert body["category"] == "framework"
    assert body["sector"] == "financial_services"
    assert body["industry"] == "fund_management"
    assert body["function"] == "risk_management"
    assert body["org_size"] == "mid_market"
    assert body["contributor_id"] == str(contributor_id)
    assert body["pricing"]["price"] == "499.00"
    assert body["pricing"]["license_types"] == ["single_user", "team"]


async def test_framework_creation_rejects_non_usd_pricing(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors cannot create non-USD Frameworks during Stripe-only MVP."""
    del migrated_database, framework_test_context
    contributor_id = await create_user_with_roles(
        "ngn-creator@auracles.space",
        ["contributor"],
    )
    payload = valid_framework_payload()
    payload["pricing"]["currency"] = "NGN"

    response = await client.post(
        "/v1/frameworks",
        json=payload,
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 422
    assert "Only USD Framework pricing is supported." in response.text


@pytest.mark.parametrize("kyc_status", ["unverified", "pending"])
async def test_kyc_incomplete_contributor_cannot_create_framework(
    kyc_status: str,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Unverified and pending KYC Contributors are blocked from draft create."""
    contributor_id = await create_user_with_roles(
        f"{kyc_status}@auracles.space",
        ["contributor"],
        kyc_status=kyc_status,
    )

    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "kyc_required",
        "onboarding_url": "/settings/onboarding",
    }


async def test_non_contributor_cannot_create_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Authenticated users without Contributor role cannot create Frameworks."""
    operator_id = await create_user_with_roles(
        "operator-create@auracles.space",
        ["operator"],
    )

    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "role_required",
        "onboarding_url": "/settings/onboarding",
    }


@pytest.mark.parametrize(
    ("pricing_patch", "expected_field"),
    [
        ({"price": "0.00"}, "price"),
        ({"license_types": []}, "license_types"),
    ],
)
async def test_framework_create_validates_pricing_payload(
    pricing_patch: dict[str, Any],
    expected_field: str,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Invalid price and empty license type selections are rejected with 422."""
    contributor_id = await create_user_with_roles(
        "invalid-pricing@auracles.space",
        ["contributor"],
    )
    payload = valid_framework_payload()
    payload["pricing"] = {**payload["pricing"], **pricing_patch}

    response = await client.post(
        "/v1/frameworks",
        json=payload,
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 422
    assert expected_field in str(response.json()["detail"])


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("category", "made_up_category"),
        ("sector", "made_up_sector"),
        ("industry", "made_up_industry"),
        ("function", "made_up_function"),
    ],
)
async def test_framework_create_rejects_unknown_taxonomy_values(
    field_name: str,
    invalid_value: str,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Framework creation rejects taxonomy values outside the catalog vocabulary."""
    contributor_id = await create_user_with_roles(
        "invalid-taxonomy@auracles.space",
        ["contributor"],
    )
    payload = valid_framework_payload()
    payload[field_name] = invalid_value

    response = await client.post(
        "/v1/frameworks",
        json=payload,
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 422
    assert field_name in str(response.json()["detail"])


async def test_contributor_can_view_list_update_and_delete_draft_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors can manage their own draft Framework metadata."""
    contributor_id = await create_user_with_roles(
        "draft-owner@auracles.space",
        ["contributor"],
    )
    headers = auth_headers(contributor_id, ["contributor"])
    created = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=headers,
    )
    framework_id = created.json()["id"]

    fetched = await client.get(f"/v1/frameworks/{framework_id}", headers=headers)
    updated = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={
            "title": "Board Risk Operating System v2",
            "tags": ["risk", "controls"],
            "pricing": {
                "price": "699.00",
                "currency": "usd",
                "license_types": ["enterprise"],
            },
        },
        headers=headers,
    )
    listed = await client.get("/v1/frameworks", headers=headers)
    deleted = await client.delete(f"/v1/frameworks/{framework_id}", headers=headers)
    after_delete = await client.get(f"/v1/frameworks/{framework_id}", headers=headers)

    assert fetched.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["title"] == "Board Risk Operating System v2"
    assert updated.json()["tags"] == ["risk", "controls"]
    assert updated.json()["pricing"]["price"] == "699.00"
    assert updated.json()["pricing"]["currency"] == "USD"
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == framework_id
    assert deleted.status_code == 204
    assert after_delete.status_code == 404


async def test_contributor_can_request_artifact_upload_url_for_draft_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Verified Contributors can create a pending Artifact upload target."""
    contributor_id = await create_user_with_roles(
        "artifact-owner@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "risk-playbook.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    listed = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"]
    assert body["upload_url"].startswith("https://s3.test/")
    assert body["file_key"].startswith(f"frameworks/{framework_id}/")
    assert body["fields"]["key"] == body["file_key"]
    assert body["fields"]["Content-Type"] == "application/pdf"
    assert body["fields"]["policy"] == "fake-policy"
    assert body["max_size"] == 500 * 1024 * 1024
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["artifact_id"]
    assert listed.json()[0]["scan_status"] == "pending"


async def test_artifact_upload_url_rejects_wrong_mime_and_oversize_total(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Artifact upload targets enforce MIME allow-list and 500MB total size."""
    contributor_id = await create_user_with_roles(
        "artifact-limits@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])

    bad_mime = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "notes.txt",
            "mime_type": "text/plain",
            "file_size": 128,
        },
        headers=headers,
    )
    too_large = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "huge.zip",
            "mime_type": "application/zip",
            "file_size": (500 * 1024 * 1024) + 1,
        },
        headers=headers,
    )

    assert bad_mime.status_code == 415
    assert too_large.status_code == 413


async def test_artifact_upload_url_accepts_preview_image_artifacts(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Standalone image Artifacts are accepted for deterministic thumbnails."""
    contributor_id = await create_user_with_roles(
        "artifact-image@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "cover.png",
            "mime_type": "image/png",
            "file_size": 2048,
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["fields"]["Content-Type"] == "image/png"


async def test_artifact_upload_url_is_denied_for_non_owner(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors cannot create Artifact upload targets for others' drafts."""
    owner_id = await create_user_with_roles(
        "artifact-real-owner@auracles.space",
        ["contributor"],
    )
    other_id = await create_user_with_roles(
        "artifact-other@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, owner_id)

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "risk-playbook.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=auth_headers(other_id, ["contributor"]),
    )

    assert response.status_code == 404


async def test_confirm_artifact_upload_is_idempotent_and_dispatches_scan_once(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Confirming an uploaded Artifact starts virus scanning exactly once."""
    dispatched: list[str] = []

    class FakeScanTask:
        """Celery task double that records dispatched Artifact ids."""

        def delay(self, artifact_id: str) -> None:
            """Record a scan dispatch instead of touching Redis/Celery."""
            dispatched.append(artifact_id)

    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        FakeScanTask(),
        raising=False,
    )
    contributor_id = await create_user_with_roles(
        "artifact-confirm@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "risk-playbook.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    artifact_id = upload.json()["artifact_id"]
    framework_test_context["storage"].existing_keys.add(upload.json()["file_key"])

    first = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/confirm",
        json={"artifact_id": artifact_id},
        headers=headers,
    )
    second = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/confirm",
        json={"artifact_id": artifact_id},
        headers=headers,
    )
    listed = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert dispatched == [artifact_id]
    assert listed.json()[0]["processing_status"] == "processing"


async def test_artifact_response_exposes_safe_redaction_status(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Artifact responses expose redaction state without leaking S3 clean keys."""
    contributor_id = await create_user_with_roles(
        "artifact-redaction-status@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    headers = auth_headers(contributor_id, ["contributor"])
    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert artifact is not None
        artifact.pii_review_needed = True
        artifact.processing_status = "flagged_pii"
        artifact.clean_file_key = (
            f"frameworks/{framework_id}/artifacts/{artifact_id}/redacted/a.pdf"
        )
        artifact.metadata_vector = {
            "redaction": {
                "status": "generated",
                "clean_file_key": artifact.clean_file_key,
                "accepted": False,
            }
        }
        await session.commit()

    listed = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=headers,
    )

    assert listed.status_code == 200
    body = listed.json()[0]
    assert body["redaction_available"] is True
    assert body["redaction_status"] == "generated"
    assert body["redaction_accepted"] is False
    assert "clean_file_key" not in body


async def test_confirm_artifact_upload_requires_uploaded_s3_object(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Confirm rejects records whose private S3 object is not present yet."""
    contributor_id = await create_user_with_roles(
        "artifact-not-uploaded@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "risk-playbook.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/confirm",
        json={"artifact_id": upload.json()["artifact_id"]},
        headers=headers,
    )

    assert response.status_code == 409


async def test_contributor_can_set_preview_artifact_and_delete_draft_artifact(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors can select and remove Artifacts while Framework is draft."""
    contributor_id = await create_user_with_roles(
        "artifact-preview@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "preview.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    artifact_id = upload.json()["artifact_id"]

    preview = await client.patch(
        f"/v1/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=headers,
    )
    deleted = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}",
        headers=headers,
    )
    fetched = await client.get(f"/v1/frameworks/{framework_id}", headers=headers)
    listed = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=headers,
    )

    assert preview.status_code == 200
    assert preview.json()["preview_artifact_id"] == artifact_id
    assert deleted.status_code == 204
    assert fetched.json()["preview_artifact_id"] is None
    assert listed.json() == []


async def test_published_framework_artifact_delete_is_rejected(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Artifacts cannot be deleted directly once the Framework is published."""
    contributor_id = await create_user_with_roles(
        "artifact-published@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "locked.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{upload.json()['artifact_id']}",
        headers=headers,
    )

    assert response.status_code == 409


async def test_artifact_delete_is_rejected_while_processing(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Deleting an Artifact mid-pipeline is rejected to avoid a worker race."""
    contributor_id = await create_user_with_roles(
        "artifact-processing@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "scanning.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    artifact_id = upload.json()["artifact_id"]
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        scan_status="pending",
        processing_status="processing",
    )

    response = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}",
        headers=headers,
    )

    assert response.status_code == 409


async def test_contributor_can_unpublish_owned_published_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors can hide a published Framework from new catalog purchases."""
    contributor_id = await create_user_with_roles(
        "artifact-unpublish@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/unpublish",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "unpublished"


async def test_kyc_pending_contributor_can_unpublish_owned_published_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Delisting is not KYC-gated because it reduces marketplace exposure."""
    contributor_id = await create_user_with_roles(
        "pending-unpublish@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        contributor = await session.get(User, contributor_id)
        framework = await session.get(Framework, UUID(framework_id))
        assert contributor is not None
        assert framework is not None
        contributor.kyc_status = "pending"
        framework.status = "published"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/unpublish",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "unpublished"


async def test_new_version_without_inherited_artifact_clones_current_artifact(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A non-inherited Artifact is copied into the new draft version."""
    contributor_id = await create_user_with_roles(
        "version-clone@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "versioned.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    artifact_id = upload.json()["artifact_id"]
    await client.patch(
        f"/v1/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=headers,
    )
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert framework is not None
        assert artifact is not None
        framework.status = "published"
        artifact.scan_status = "clean"
        artifact.processing_status = "processed"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/versions",
        json={
            "change_type": "improvement",
            "change_log": "Refresh the implementation playbook.",
            "artifact_inheritance": {artifact_id: False},
        },
        headers=headers,
    )
    listed = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["version"] == "1.1.0"
    assert response.json()["status"] == "draft"
    current_artifacts = listed.json()
    assert len(current_artifacts) == 1
    assert current_artifacts[0]["id"] != artifact_id
    assert current_artifacts[0]["processing_status"] == "pending"
    assert framework_test_context["storage"].copy_requests

    async with async_session_factory() as session:
        old_artifact = await session.get(Artifact, UUID(artifact_id))
        snapshot = await session.scalar(
            select(FrameworkVersion).where(
                FrameworkVersion.framework_id == UUID(framework_id),
                FrameworkVersion.version == "1.0.0",
            )
        )
        assert old_artifact is not None
        assert old_artifact.current_for_framework is False
        assert snapshot is not None
        snapshot_artifact = await session.get(
            FrameworkVersionArtifact,
            (snapshot.id, UUID(artifact_id)),
        )
        assert snapshot_artifact is not None
        assert snapshot_artifact.is_preview is True


async def test_new_version_rejects_empty_inheritance_as_nothing_to_bump(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Version creation needs an explicit Artifact inheritance decision."""
    contributor_id = await create_user_with_roles(
        "version-empty@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/versions",
        json={
            "change_type": "fix",
            "change_log": "No artifact decision.",
            "artifact_inheritance": {},
        },
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Nothing to bump."


async def test_major_bump_from_zero_version_starts_at_one_zero_zero(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """The first major version from 0.0.0 starts cleanly at 1.0.0."""
    contributor_id = await create_user_with_roles(
        "version-zero@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "zero.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    artifact_id = upload.json()["artifact_id"]
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        framework.version = "0.0.0"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/versions",
        json={
            "change_type": "major",
            "change_log": "Initial published version.",
            "artifact_inheritance": {artifact_id: True},
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["version"] == "1.0.0"


async def test_deleting_inherited_version_artifact_keeps_historical_snapshot(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Inherited Artifacts are hidden from drafts, not deleted historically."""
    contributor_id = await create_user_with_roles(
        "version-inherit-delete@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "inherited.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    artifact_id = upload.json()["artifact_id"]
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    version = await client.post(
        f"/v1/frameworks/{framework_id}/versions",
        json={
            "change_type": "fix",
            "change_log": "Start a draft with inherited files.",
            "artifact_inheritance": {artifact_id: True},
        },
        headers=headers,
    )
    deleted = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}",
        headers=headers,
    )
    listed = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=headers,
    )

    assert version.status_code == 200
    assert deleted.status_code == 204
    assert listed.json() == []

    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        snapshot = await session.scalar(
            select(FrameworkVersion).where(
                FrameworkVersion.framework_id == UUID(framework_id),
                FrameworkVersion.version == "1.0.0",
            )
        )
        assert artifact is not None
        assert artifact.current_for_framework is False
        assert snapshot is not None
        assert await session.get(
            FrameworkVersionArtifact,
            (snapshot.id, UUID(artifact_id)),
        )


async def test_submit_framework_with_processed_artifacts_passes_pipeline_gate(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Submitting a clean processed Framework enables Contributor publish."""
    contributor_id = await create_user_with_roles(
        "submit-pass@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    await mark_artifact_pipeline_state(framework_id, artifact_id)

    response = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pipeline_passed"


async def test_submit_framework_without_artifacts_is_rejected(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A Framework must have at least one Artifact before submission."""
    contributor_id = await create_user_with_roles(
        "submit-empty@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)

    response = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "At least one Artifact is required."


@pytest.mark.parametrize("action", ["submit", "publish"])
async def test_kyc_pending_contributor_cannot_submit_or_publish_framework(
    action: str,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """KYC pending is not verified for marketplace publish-gate actions."""
    contributor_id = await create_user_with_roles(
        f"kyc-pending-{action}@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        user = await session.get(User, contributor_id)
        framework = await session.get(Framework, UUID(framework_id))
        assert user is not None
        assert framework is not None
        user.kyc_status = "pending"
        if action == "publish":
            framework.status = "pipeline_passed"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/{action}",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "kyc_required",
        "onboarding_url": "/settings/onboarding",
    }


async def test_publish_requires_pipeline_pass_and_snapshots_current_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Publish is only allowed after the pipeline gate has passed."""
    indexed_frameworks: list[str] = []
    notified_versions: list[tuple[str, str]] = []

    class FakeNotifyTask:
        """Celery task double that records new-version notifications."""

        def delay(self, framework_id: str, new_version: str) -> None:
            """Record notification dispatches instead of touching Celery."""
            notified_versions.append((framework_id, new_version))

    async def fake_index_framework_artifacts(framework_id: UUID) -> None:
        """Record MinHash LSH indexing instead of touching Redis."""
        indexed_frameworks.append(str(framework_id))

    monkeypatch.setattr(
        "app.modules.frameworks.service.index_framework_artifacts",
        fake_index_framework_artifacts,
        raising=False,
    )
    monkeypatch.setattr(
        "app.modules.frameworks.service.notify_licensees_of_new_version",
        FakeNotifyTask(),
        raising=False,
    )
    contributor_id = await create_user_with_roles(
        "publish-pass@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    headers = auth_headers(contributor_id, ["contributor"])
    premature = await client.post(
        f"/v1/frameworks/{framework_id}/publish",
        headers=headers,
    )
    await mark_artifact_pipeline_state(framework_id, artifact_id)
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=headers,
    )

    published = await client.post(
        f"/v1/frameworks/{framework_id}/publish",
        headers=headers,
    )

    assert premature.status_code == 409
    assert submitted.status_code == 200
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None
    assert indexed_frameworks == [framework_id]
    assert notified_versions == []

    async with async_session_factory() as session:
        snapshot = await session.scalar(
            select(FrameworkVersion).where(
                FrameworkVersion.framework_id == UUID(framework_id),
                FrameworkVersion.version == "1.0.0",
            )
        )
        assert snapshot is not None
        assert await session.get(
            FrameworkVersionArtifact,
            (snapshot.id, UUID(artifact_id)),
        )


async def test_external_rarity_soft_fail_requires_acknowledgement_before_publish(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Low external rarity blocks publish until Contributor acknowledgement."""
    contributor_id = await create_user_with_roles(
        "soft-fail@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    headers = auth_headers(contributor_id, ["contributor"])
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        external_rarity=Decimal("0.2000"),
    )

    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=headers,
    )
    publish_before_ack = await client.post(
        f"/v1/frameworks/{framework_id}/publish",
        headers=headers,
    )
    acknowledged = await client.post(
        f"/v1/frameworks/{framework_id}/acknowledge-soft-fail",
        headers=headers,
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pipeline_failed"
    assert publish_before_ack.status_code == 409
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "pipeline_passed"


async def test_similarity_notice_band_passes_pipeline_and_exposes_context(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A same-topic similarity notice does not block Contributor publish."""
    contributor_id = await create_user_with_roles(
        "similarity-notice@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        internal_rarity=Decimal("0.2000"),
    )
    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert artifact is not None
        audit = await session.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == artifact.id
            )
        )
        assert audit is not None
        audit.internal_jaccard = Decimal("0.8000")
        await session.commit()

    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    listed = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pipeline_passed"
    assert listed.status_code == 200
    notice = listed.json()[0]["similarity_notice"]
    assert notice["jaccard"] == "0.8000"
    assert notice["nearest_match_title"] is None


async def test_similarity_notice_acknowledgement_persists_differentiation_note(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributor notice acknowledgement is audited without gating publish."""
    contributor_id = await create_user_with_roles(
        "notice-ack@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        internal_rarity=Decimal("0.2000"),
    )
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == UUID(artifact_id)
            )
        )
        assert audit is not None
        audit.internal_jaccard = Decimal("0.8000")
        await session.commit()
    headers = auth_headers(contributor_id, ["contributor"])
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=headers,
    )
    acknowledged = await client.post(
        f"/v1/frameworks/{framework_id}/similarity-notice/acknowledge",
        json={
            "differentiation_note": (
                "This version adds implementation controls and jurisdiction "
                "mapping absent from the similar Framework."
            )
        },
        headers=headers,
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pipeline_passed"
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "pipeline_passed"
    async with async_session_factory() as session:
        audit_log = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "similarity_notice_acknowledged"
            )
        )
        assert audit_log is not None
        assert audit_log.metadata_["differentiation_note"].startswith(
            "This version adds implementation controls"
        )
        assert audit_log.metadata_["notices"][0]["artifact_id"] == artifact_id


async def test_similarity_notice_includes_nearest_match_review_context(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Similarity notices include nearest published Framework review context."""
    contributor_id = await create_user_with_roles(
        "notice-context@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "notice-reviewer@auracles.space",
        ["operator"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    async with async_session_factory() as session:
        async with session.begin():
            nearest_framework = Framework(
                contributor_id=contributor_id,
                title="Published Risk Controls Framework",
                description="Published controls for operational risk teams.",
                version="1.0.0",
                status="published",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk", "controls"],
                tags_text="risk controls",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(nearest_framework)
            await session.flush()
            nearest_artifact = Artifact(
                framework_id=nearest_framework.id,
                name="published.pdf",
                file_key=f"frameworks/{nearest_framework.id}/published.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="processed",
                current_for_framework=True,
            )
            session.add(nearest_artifact)
            await session.flush()
            license_row = License(
                framework_id=nearest_framework.id,
                operator_id=operator_id,
                license_type="single_user",
                status="active",
                version_at_grant="1.0.0",
            )
            session.add(license_row)
            await session.flush()
            session.add(
                Review(
                    framework_id=nearest_framework.id,
                    operator_id=operator_id,
                    license_id=license_row.id,
                    score=5,
                    body="Strong operational controls.",
                )
            )
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        internal_rarity=Decimal("0.2000"),
    )
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == UUID(artifact_id)
            )
        )
        assert audit is not None
        audit.internal_jaccard = Decimal("0.8000")
        audit.nearest_match_id = nearest_artifact.id
        await session.commit()

    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    listed = await client.get(
        f"/v1/frameworks/{framework_id}/artifacts",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pipeline_passed"
    notice = listed.json()[0]["similarity_notice"]
    assert notice["nearest_match_title"] == "Published Risk Controls Framework"
    assert notice["average_review_score"] == "5.00"
    assert notice["review_count"] == 1


async def test_near_duplicate_band_hard_blocks_pipeline(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A near-duplicate Jaccard match remains a hard pipeline failure."""
    contributor_id = await create_user_with_roles(
        "near-duplicate@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        internal_rarity=Decimal("0.0500"),
    )
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == UUID(artifact_id)
            )
        )
        assert audit is not None
        audit.internal_jaccard = Decimal("0.9500")
        await session.commit()

    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pipeline_failed"
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        assert framework.pipeline_failure_reasons == {
            "internal_rarity": [artifact_id]
        }


async def test_admin_override_unblocks_near_duplicate_hard_band(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Admin rarity override writes durable state and unblocks re-evaluation."""
    contributor_id = await create_user_with_roles(
        "override-seller@auracles.space",
        ["contributor"],
    )
    admin_id = await create_user_with_roles(
        "rarity-admin@auracles.space",
        ["admin"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        internal_rarity=Decimal("0.0500"),
    )
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == UUID(artifact_id)
            )
        )
        assert audit is not None
        audit.internal_jaccard = Decimal("0.9500")
        await session.commit()

    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    override = await client.post(
        f"/v1/admin/frameworks/{framework_id}/rarity-block/override",
        json={"reason": "Contributor supplied reuse license evidence."},
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pipeline_failed"
    assert override.status_code == 200
    assert override.json()["status"] == "pipeline_passed"
    async with async_session_factory() as session:
        rarity_audit = await session.scalar(
            select(ArtifactRarityAudit).where(
                ArtifactRarityAudit.artifact_id == UUID(artifact_id)
            )
        )
        audit_log = await session.scalar(
            select(AuditLog).where(AuditLog.action == "rarity_block_overridden")
        )
        assert rarity_audit is not None
        assert rarity_audit.near_duplicate_overridden_by == admin_id
        assert rarity_audit.near_duplicate_override_reason == (
            "Contributor supplied reuse license evidence."
        )
        assert audit_log is not None


async def test_resolve_pii_review_resets_artifact_and_reruns_scan(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributor can ask the pipeline to re-check a replaced PII Artifact."""
    dispatched: list[str] = []

    class FakeScanTask:
        """Celery task double that records scan dispatches."""

        def delay(self, artifact_id: str) -> None:
            """Record a scan dispatch instead of touching Celery."""
            dispatched.append(artifact_id)

    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        FakeScanTask(),
        raising=False,
    )
    contributor_id = await create_user_with_roles(
        "pii-resolve@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        processing_status="flagged_pii",
        pii_detected=True,
        pii_review_needed=True,
    )
    await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/resolve-pii-review",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["processing_status"] == "processing"
    assert response.json()["pii_detected"] is False
    assert response.json()["pii_review_needed"] is False
    assert dispatched == [artifact_id]


async def test_accept_redaction_promotes_clean_artifact_and_reruns_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributor can accept a generated redacted copy as canonical."""
    dispatched: list[str] = []

    class FakeProcessTask:
        """Celery task double that records processing dispatches."""

        def delay(self, artifact_id: str) -> None:
            """Record a process dispatch instead of touching Celery."""
            dispatched.append(artifact_id)

    monkeypatch.setattr(
        "app.modules.frameworks.service.process_artifact",
        FakeProcessTask(),
        raising=False,
    )
    contributor_id = await create_user_with_roles(
        "redaction-accept@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    clean_file_key = f"frameworks/{framework_id}/artifacts/{artifact_id}/redacted/a.pdf"
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        processing_status="flagged_pii",
        pii_detected=True,
        pii_review_needed=True,
    )
    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert artifact is not None
        original_file_key = artifact.file_key
        artifact.clean_file_key = clean_file_key
        artifact.metadata_vector = {
            "redaction": {
                "status": "generated",
                "clean_file_key": clean_file_key,
            }
        }
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "pipeline_failed"
        framework.pipeline_failure_reasons = {"pii": [artifact_id]}
        session.add(
            ArtifactPiiAudit(
                artifact_id=UUID(artifact_id),
                pii_types_found=["EMAIL_ADDRESS"],
                auto_redacted=True,
                flagged_for_review=True,
            )
        )
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/accept-redaction",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    second_response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/{artifact_id}/accept-redaction",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["processing_status"] == "processing"
    assert response.json()["pii_detected"] is False
    assert response.json()["pii_review_needed"] is False
    assert second_response.status_code == 200
    assert dispatched == [artifact_id]

    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert artifact is not None
        assert artifact.file_key == clean_file_key
        assert artifact.clean_file_key == clean_file_key
        assert artifact.metadata_vector["redaction"]["accepted"] is True
        assert artifact.metadata_vector["redaction"]["original_file_key"] == (
            original_file_key
        )
        audit = await session.scalar(
            select(ArtifactPiiAudit).where(
                ArtifactPiiAudit.artifact_id == UUID(artifact_id)
            )
        )
        assert audit is not None
        assert audit.reviewed_by == contributor_id
        assert audit.flagged_for_review is False


async def test_admin_can_suspend_published_framework(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Admins can remove a published Framework from marketplace discovery."""
    removed_frameworks: list[str] = []

    async def fake_remove_framework_artifacts(framework_id: UUID) -> None:
        """Record MinHash LSH eviction instead of touching Redis."""
        removed_frameworks.append(str(framework_id))

    monkeypatch.setattr(
        "app.modules.admin.service.remove_framework_artifacts_from_index",
        fake_remove_framework_artifacts,
        raising=False,
    )
    contributor_id = await create_user_with_roles(
        "suspend-owner@auracles.space",
        ["contributor"],
    )
    admin_id = await create_user_with_roles("suspend-admin@auracles.space", ["admin"])
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.post(
        f"/v1/admin/frameworks/{framework_id}/suspend",
        json={"reason": "Post-publish moderation hit."},
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "suspended"
    assert removed_frameworks == [framework_id]


async def test_unauthenticated_create_returns_401_and_creates_no_draft(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Visitors who click Create Framework are sent to auth with no draft write."""
    response = await client.post("/v1/frameworks", json=valid_framework_payload())

    async with async_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Framework))

    assert response.status_code == 401
    assert count == 0


async def test_blank_profile_contributor_is_routed_to_onboarding(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors with incomplete profile data cannot create Frameworks."""
    contributor_id = await create_user_with_roles(
        "blank-profile@auracles.space",
        ["contributor"],
        display_name="",
    )

    response = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "error_code": "profile_required",
        "onboarding_url": "/settings/onboarding",
    }


async def test_contributor_cannot_read_or_mutate_another_contributors_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributor endpoints are scoped to the owning Contributor."""
    owner_id = await create_user_with_roles("owner@auracles.space", ["contributor"])
    other_id = await create_user_with_roles("other@auracles.space", ["contributor"])
    created = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=auth_headers(owner_id, ["contributor"]),
    )
    framework_id = created.json()["id"]
    other_headers = auth_headers(other_id, ["contributor"])

    fetched = await client.get(f"/v1/frameworks/{framework_id}", headers=other_headers)
    updated = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={"title": "Stolen draft"},
        headers=other_headers,
    )
    deleted = await client.delete(
        f"/v1/frameworks/{framework_id}",
        headers=other_headers,
    )

    assert fetched.status_code == 404
    assert updated.status_code == 404
    assert deleted.status_code == 404


@pytest.mark.parametrize("framework_status", ["submitted", "published"])
async def test_non_draft_framework_cannot_be_updated_or_deleted(
    framework_status: str,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Submitted and published Frameworks are locked from draft mutations."""
    contributor_id = await create_user_with_roles(
        f"{framework_status}-owner@auracles.space",
        ["contributor"],
    )
    headers = auth_headers(contributor_id, ["contributor"])
    created = await client.post(
        "/v1/frameworks",
        json=valid_framework_payload(),
        headers=headers,
    )
    framework_id = created.json()["id"]
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = framework_status
        await session.commit()

    updated = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={"title": "Locked"},
        headers=headers,
    )
    deleted = await client.delete(f"/v1/frameworks/{framework_id}", headers=headers)

    assert updated.status_code == 409
    assert deleted.status_code == 409
