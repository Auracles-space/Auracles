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

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, func, select, update

from app.core.currency import platform_currency
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_totp_secret,
    hash_password,
)
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

    def __init__(self) -> None:
        """Create empty in-memory Redis-like state."""
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.values[key] = value

    async def incr(self, key: str) -> int:
        """Increment and return a counter value."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """No-op TTL assignment for the test double."""
        del key, seconds

    async def delete(self, *keys: str) -> int:
        """Delete string and counter keys."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
        return removed

    async def ttl(self, key: str) -> int:
        """Return the no-expiry sentinel."""
        del key
        return -1


class FakeArtifactStorage:
    """S3 storage test double for artifact upload URL and object checks."""

    def __init__(self) -> None:
        """Create empty fake S3 state."""
        self.existing_keys: set[str] = set()
        self.presigned_requests: list[tuple[str, str, str, int, int]] = []
        self.copy_requests: list[tuple[str, str, str, str]] = []
        self.uploaded_bytes: list[tuple[str, str, bytes, str]] = []

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

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Record an upload and mark the destination object as present."""
        self.uploaded_bytes.append((bucket, key, body, mime_type))
        self.existing_keys.add(key)


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
            await session.execute(update(Framework).values(preview_artifact_id=None))
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


async def enable_admin_totp(user_id: UUID) -> str:
    """Enable TOTP on a user and return the raw secret for code generation.

    Admin moderation writes are step-up gated, so their test admins need a
    real authenticator secret rather than a bare role row.
    """
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            secret = pyotp.random_base32()
            user.totp_secret = encrypt_totp_secret(secret)
            user.totp_enabled = True
    return secret


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
    # Mirror a confirmed upload: the object now exists in storage, so the
    # publish/relist file-presence re-check passes for this artifact.
    from app.integrations import s3

    s3.storage.existing_keys.add(response.json()["file_key"])
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


async def test_framework_creation_accepts_investment_management_function(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Framework creation accepts the new canonical investment-management function."""
    contributor_id = await create_user_with_roles(
        "investment-function@auracles.space",
        ["contributor"],
    )
    payload = valid_framework_payload()
    payload["function"] = "investment_management"

    response = await client.post(
        "/v1/frameworks",
        json=payload,
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 201
    assert response.json()["function"] == "investment_management"


async def test_framework_creation_rejects_non_usd_pricing(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Contributors cannot price a Framework outside the platform currency.

    The suite pins `PLATFORM_CURRENCY=USD`, so NGN is the off-currency here;
    the rejection message is read from the setting rather than hardcoded so
    this keeps asserting the rule and not one deployment's currency.
    """
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
    assert f"Only {platform_currency()} amounts are supported." in response.text


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
                "license_types": ["single_user", "enterprise"],
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


async def test_confirm_artifact_upload_allowed_on_pipeline_failed_framework(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A replacement artifact on a pipeline_failed Framework can be confirmed.

    Pairs with the loosened upload-url gate: after uploading a replacement file
    to a failed Framework, confirm must dispatch the scan rather than 409.
    """
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
        "artifact-confirm-failed@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "replacement.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    artifact_id = upload.json()["artifact_id"]
    framework_test_context["storage"].existing_keys.add(upload.json()["file_key"])
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "pipeline_failed"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/confirm",
        json={"artifact_id": artifact_id},
        headers=headers,
    )

    assert response.status_code == 200
    assert dispatched == [artifact_id]


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


async def test_contributor_can_set_preview_on_pipeline_failed_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Preview stays selectable after a failed check so publish prep can finish.

    A failed publishing check moves a draft to pipeline_failed; the Contributor
    must still be able to designate a sample file before fixing the block and
    re-running, so preview selection is allowed in both editable states.
    """
    contributor_id = await create_user_with_roles(
        "artifact-preview-failed@auracles.space",
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
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Framework)
                .where(Framework.id == UUID(framework_id))
                .values(status="pipeline_failed")
            )

    preview = await client.patch(
        f"/v1/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=headers,
    )

    assert preview.status_code == 200
    assert preview.json()["preview_artifact_id"] == artifact_id


async def test_publish_requires_preview_when_an_eligible_artifact_exists(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Publish is refused when no preview is set but a file could be shown.

    Buyers can only inspect a Framework through its preview, so a passing
    Framework with a preview-eligible Artifact must designate one first.
    """
    contributor_id = await create_user_with_roles(
        "publish-needs-preview@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client, contributor_id, framework_id
    )
    await mark_artifact_pipeline_state(framework_id, artifact_id)
    headers = auth_headers(contributor_id, ["contributor"])
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit", headers=headers
    )
    assert submitted.json()["status"] == "pipeline_passed"

    response = await client.post(
        f"/v1/frameworks/{framework_id}/publish", headers=headers
    )

    assert response.status_code == 422
    assert "preview" in response.json()["detail"].lower()


async def test_publish_succeeds_once_a_preview_is_selected(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Selecting a preview while drafting unblocks publish for an eligible file."""
    contributor_id = await create_user_with_roles(
        "publish-with-preview@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client, contributor_id, framework_id
    )
    await mark_artifact_pipeline_state(framework_id, artifact_id)
    headers = auth_headers(contributor_id, ["contributor"])
    preview = await client.patch(
        f"/v1/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=headers,
    )
    assert preview.status_code == 200
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit", headers=headers
    )
    assert submitted.json()["status"] == "pipeline_passed"

    response = await client.post(
        f"/v1/frameworks/{framework_id}/publish", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"


async def test_preview_selectable_at_pipeline_passed_unblocks_publish(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A passing Framework with no preview is never trapped.

    Reaching pipeline_passed without a preview must not dead-end: the
    Contributor can still designate one at pipeline_passed and then publish.
    """
    contributor_id = await create_user_with_roles(
        "publish-preview-at-passed@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client, contributor_id, framework_id
    )
    await mark_artifact_pipeline_state(framework_id, artifact_id)
    headers = auth_headers(contributor_id, ["contributor"])
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit", headers=headers
    )
    assert submitted.json()["status"] == "pipeline_passed"

    preview = await client.patch(
        f"/v1/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=headers,
    )
    assert preview.status_code == 200

    published = await client.post(
        f"/v1/frameworks/{framework_id}/publish", headers=headers
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"


async def test_publish_allowed_without_preview_when_no_artifact_is_eligible(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """An all-sensitive Framework stays publishable without a preview.

    When every current Artifact carries unredacted detected PII, none is
    eligible to be shown publicly, so the preview requirement must not trap the
    Framework — publish proceeds without one.
    """
    contributor_id = await create_user_with_roles(
        "publish-no-eligible@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client, contributor_id, framework_id
    )
    # Detected-but-unredacted PII with no review outstanding: the pipeline gate
    # passes (nothing to review), yet the file is ineligible as a preview.
    await mark_artifact_pipeline_state(
        framework_id,
        artifact_id,
        pii_detected=True,
        pii_review_needed=False,
    )
    headers = auth_headers(contributor_id, ["contributor"])
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit", headers=headers
    )
    assert submitted.json()["status"] == "pipeline_passed"

    response = await client.post(
        f"/v1/frameworks/{framework_id}/publish", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"


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


async def test_artifact_delete_allowed_on_pipeline_failed_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A pipeline_failed Framework can have artifacts removed so it can recover.

    A PII/rarity soft-fail moves the Framework to pipeline_failed; the
    Contributor must be able to remove the offending artifact to fix and
    re-run the pipeline, not just while still in draft.
    """
    contributor_id = await create_user_with_roles(
        "artifact-failed-delete@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "flagged.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "pipeline_failed"
        await session.commit()

    response = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{upload.json()['artifact_id']}",
        headers=headers,
    )

    assert response.status_code == 204


async def test_artifact_delete_and_upload_allowed_on_pipeline_passed_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A pipeline_passed Framework accepts artifact changes and resets to draft.

    Allowing artifact deletion and uploading on pipeline_passed frameworks enables
    contributors to make last-minute updates, and reverts the status to draft to
    ensure the updated deliverables pass the pipeline checks before publishing.
    """
    contributor_id = await create_user_with_roles(
        "artifact-passed-delete@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload_1 = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "first.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    # Uploading a second one so we don't hit the "last artifact deleted" special case
    await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "second.pdf",
            "mime_type": "application/pdf",
            "file_size": 1024,
        },
        headers=headers,
    )

    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "pipeline_passed"
        await session.commit()

    # Deleting an artifact should succeed and revert status to draft
    response_delete = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{upload_1.json()['artifact_id']}",
        headers=headers,
    )
    assert response_delete.status_code == 204

    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        assert framework.status == "draft"
        # Reset to pipeline_passed to test upload URL logic
        framework.status = "pipeline_passed"
        await session.commit()

    # Uploading an artifact should succeed and revert status to draft
    response_upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "third.pdf",
            "mime_type": "application/pdf",
            "file_size": 512,
        },
        headers=headers,
    )
    assert response_upload.status_code == 200

    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        assert framework.status == "draft"


async def test_deleting_last_artifact_resets_failed_framework_to_draft(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Removing the final artifact returns a failed Framework to draft.

    With no artifacts there is nothing to gate, so a stale pipeline_failed
    status and its failure reasons must clear rather than stranding the
    Contributor on a "Checks failed" badge for checks that cannot run.
    """
    contributor_id = await create_user_with_roles(
        "artifact-last-delete@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "only.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "pipeline_failed"
        framework.pipeline_failure_reasons = {"external_check": "unavailable"}
        await session.commit()

    deleted = await client.delete(
        f"/v1/frameworks/{framework_id}/artifacts/{upload.json()['artifact_id']}",
        headers=headers,
    )

    assert deleted.status_code == 204
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        assert framework.status == "draft"
        assert framework.pipeline_failure_reasons == {}


async def test_artifact_upload_url_allowed_on_pipeline_failed_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A pipeline_failed Framework accepts a replacement artifact upload.

    Pairs with resolve_pii_review (which already allows pipeline_failed): the
    Contributor replaces the flagged file, then re-runs the pipeline.
    """
    contributor_id = await create_user_with_roles(
        "artifact-failed-upload@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "pipeline_failed"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "filename": "replacement.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
        headers=headers,
    )

    assert response.status_code == 200


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


async def test_contributor_can_relist_unpublished_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Relisting returns a delisted Framework to the catalog at the same version."""
    contributor_id = await create_user_with_roles(
        "framework-relist@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "unpublished"
        await session.commit()
        original_version = framework.version

    response = await client.post(
        f"/v1/frameworks/{framework_id}/relist",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["version"] == original_version


async def test_relist_refuses_when_current_artifact_flagged_pii(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Relist re-checks trust gates: a flagged-PII artifact blocks republish.

    A delisted Framework may have drifted (re-processing, an accepted redaction
    that re-flagged) since it was last live. Relist must never flip it back to
    published while a current Artifact carries a PII flag.
    """
    contributor_id = await create_user_with_roles(
        "framework-relist-pii@auracles.space",
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
        pii_review_needed=True,
    )
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "unpublished"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/relist",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 409
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        assert framework.status != "published"


async def test_relist_rejects_non_unpublished_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Only unpublished Frameworks can be relisted; a draft returns 409."""
    contributor_id = await create_user_with_roles(
        "framework-relist-conflict@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)

    # A never-published draft has no catalog listing to restore.
    response = await client.post(
        f"/v1/frameworks/{framework_id}/relist",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 409


async def test_relist_is_idempotent_on_published_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Relisting an already-live Framework is a no-op 200, mirroring unpublish."""
    contributor_id = await create_user_with_roles(
        "framework-relist-idempotent@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/relist",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"


async def test_relist_denied_for_non_owner(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A stranger cannot relist another contributor's delisted Framework (404)."""
    owner_id = await create_user_with_roles(
        "framework-relist-owner@auracles.space",
        ["contributor"],
    )
    stranger_id = await create_user_with_roles(
        "framework-relist-stranger@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, owner_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "unpublished"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/relist",
        headers=auth_headers(stranger_id, ["contributor"]),
    )

    assert response.status_code == 404


async def test_contributor_can_edit_metadata_on_published_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Title/price/tags edit in place on a live Framework without a version bump."""
    contributor_id = await create_user_with_roles(
        "framework-live-edit@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()
        original_version = framework.version

    response = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={
            "title": "Live Edited Title",
            "tags": ["updated"],
            "pricing": {
                "price": "880.00",
                "currency": "usd",
                "license_types": ["single_user", "team"],
            },
        },
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Live Edited Title"
    assert body["pricing"]["price"] == "880.00"
    assert body["status"] == "published"
    assert body["version"] == original_version


async def test_contributor_can_edit_metadata_on_unpublished_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A delisted Framework's metadata is editable in place too."""
    contributor_id = await create_user_with_roles(
        "framework-delisted-edit@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "unpublished"
        await session.commit()

    response = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={"title": "Delisted Edited Title"},
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Delisted Edited Title"


async def test_metadata_edit_blocked_while_framework_in_pipeline(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Metadata is locked while a Framework moves through the publishing pipeline."""
    contributor_id = await create_user_with_roles(
        "framework-pipeline-edit@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "submitted"
        await session.commit()

    response = await client.patch(
        f"/v1/frameworks/{framework_id}",
        json={"title": "Should Not Save"},
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 409


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


async def test_publish_refuses_when_current_artifact_drifted_to_flagged_pii(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Publish re-runs the gate and refuses a framework whose artifact regained PII.

    Guards against a stale ``pipeline_passed`` status: if a current Artifact
    drifts back to ``flagged_pii`` after the gate passed (re-processing, an
    added file), publish must re-verify and block, never leak PII into the
    public catalog.
    """
    contributor_id = await create_user_with_roles(
        "publish-pii-drift@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    await mark_artifact_pipeline_state(framework_id, artifact_id)
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    assert submitted.json()["status"] == "pipeline_passed"

    # Drift: the current Artifact regains a PII flag while the framework status
    # is still the now-stale pipeline_passed.
    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert artifact is not None
        artifact.processing_status = "flagged_pii"
        artifact.pii_review_needed = True
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/publish",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 409
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        assert framework.status != "published"


async def test_publish_refuses_when_current_artifact_file_missing_from_storage(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Publish blocks when a current Artifact's S3 object was removed.

    The pipeline gate only inspects DB columns, so a file deleted from S3 out
    of band (lifecycle rule, manual delete, quarantine) after processing would
    otherwise publish a dangling ``file_key`` — Operators would buy a Framework
    whose presigned download 404s. Publish must re-verify the bytes exist.
    """
    contributor_id = await create_user_with_roles(
        "publish-missing-file@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    artifact_id = await create_artifact_for_framework(
        client,
        contributor_id,
        framework_id,
    )
    await mark_artifact_pipeline_state(framework_id, artifact_id)
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    assert submitted.json()["status"] == "pipeline_passed"

    # The S3 object disappears after the pipeline passed but before publish.
    storage = framework_test_context["storage"]
    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        assert artifact is not None
        storage.existing_keys.discard(artifact.file_key)

    response = await client.post(
        f"/v1/frameworks/{framework_id}/publish",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 409
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        assert framework.status != "published"


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
    # Publish now requires a preview when a file is eligible; select one while
    # the Framework is still a draft.
    await client.patch(
        f"/v1/frameworks/{framework_id}/preview-artifact",
        json={"artifact_id": artifact_id},
        headers=headers,
    )
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


async def test_revise_returns_passed_framework_to_draft(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Revising a checks-passed Framework returns it to an editable draft.

    A pipeline_passed Framework locks all edits; revising resets it to draft so
    the Contributor can correct metadata, pricing, or files before re-running.
    """
    contributor_id = await create_user_with_roles(
        "revise@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "pipeline_passed"
        await session.commit()

    response = await client.post(
        f"/v1/frameworks/{framework_id}/revise",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "draft"


async def test_revise_rejects_a_draft_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Only a checks-passed Framework can be returned to draft."""
    contributor_id = await create_user_with_roles(
        "revise-draft@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])

    response = await client.post(
        f"/v1/frameworks/{framework_id}/revise",
        headers=headers,
    )

    assert response.status_code == 409


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
            select(AuditLog).where(AuditLog.action == "similarity_notice_acknowledged")
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
        assert framework.pipeline_failure_reasons == {"internal_rarity": [artifact_id]}


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
    admin_totp = await enable_admin_totp(admin_id)
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
        json={
            "reason": "Contributor supplied reuse license evidence.",
            "totp_code": pyotp.TOTP(admin_totp).now(),
        },
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
    admin_totp = await enable_admin_totp(admin_id)
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.post(
        f"/v1/admin/frameworks/{framework_id}/suspend",
        json={
            "reason": "Post-publish moderation hit.",
            "totp_code": pyotp.TOTP(admin_totp).now(),
        },
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "suspended"
    assert removed_frameworks == [framework_id]


async def test_admin_suspended_frameworks_list_surfaces_takedowns(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """The suspended-frameworks listing returns each takedown for review."""

    async def fake_remove(framework_id: UUID) -> None:
        return None

    monkeypatch.setattr(
        "app.modules.admin.service.remove_framework_artifacts_from_index",
        fake_remove,
        raising=False,
    )
    contributor_id = await create_user_with_roles(
        "suspended-list-owner@auracles.space",
        ["contributor"],
        display_name="Listed Owner",
    )
    admin_id = await create_user_with_roles(
        "suspended-list-admin@auracles.space", ["admin"]
    )
    admin_totp = await enable_admin_totp(admin_id)
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()
    await client.post(
        f"/v1/admin/frameworks/{framework_id}/suspend",
        json={
            "reason": "Listed for review.",
            "totp_code": pyotp.TOTP(admin_totp).now(),
        },
        headers=auth_headers(admin_id, ["admin"]),
    )

    response = await client.get(
        "/v1/admin/frameworks/suspended",
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["framework_id"] == framework_id
    assert items[0]["contributor_name"] == "Listed Owner"
    assert items[0]["reason"] == "Listed for review."
    assert items[0]["suspended_at"] is not None


async def test_admin_framework_directory_lists_published_with_owner(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """The admin Framework directory surfaces any published Framework for delisting.

    Unlike the moderation queue (signal-flagged only) and the suspended list
    (already taken down), this directory lets an admin find an arbitrary
    published Framework — and its owning Contributor — to delist on request.
    """
    contributor_id = await create_user_with_roles(
        "fw-directory-owner@auracles.space",
        ["contributor"],
        display_name="Directory Owner",
    )
    admin_id = await create_user_with_roles(
        "fw-directory-admin@auracles.space", ["admin"]
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        framework_title = framework.title
        await session.commit()

    response = await client.get(
        "/v1/admin/frameworks",
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    items = response.json()["items"]
    matching = [item for item in items if item["framework_id"] == framework_id]
    assert len(matching) == 1
    assert matching[0]["title"] == framework_title
    assert matching[0]["contributor_id"] == str(contributor_id)
    assert matching[0]["contributor_name"] == "Directory Owner"
    assert matching[0]["status"] == "published"


async def test_admin_framework_directory_filters_by_query(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A title search narrows the directory so admins can find one Framework."""
    contributor_id = await create_user_with_roles(
        "fw-directory-search-owner@auracles.space",
        ["contributor"],
    )
    admin_id = await create_user_with_roles(
        "fw-directory-search-admin@auracles.space", ["admin"]
    )
    wanted_id = await create_draft_framework(client, contributor_id)
    other_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        for fid in (wanted_id, other_id):
            framework = await session.get(Framework, UUID(fid))
            assert framework is not None
            framework.status = "published"
        wanted = await session.get(Framework, UUID(wanted_id))
        assert wanted is not None
        wanted.title = "Quantum Risk Ledger"
        await session.commit()

    response = await client.get(
        "/v1/admin/frameworks",
        params={"query": "quantum risk"},
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    returned_ids = {item["framework_id"] for item in response.json()["items"]}
    assert wanted_id in returned_ids
    assert other_id not in returned_ids


async def test_admin_framework_directory_rejects_non_admin(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A non-admin caller is denied the admin Framework directory (403)."""
    contributor_id = await create_user_with_roles(
        "fw-directory-intruder@auracles.space",
        ["contributor"],
    )

    response = await client.get(
        "/v1/admin/frameworks",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 403


async def test_admin_framework_directory_excludes_non_published(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Draft and suspended Frameworks never appear in the delist directory."""
    contributor_id = await create_user_with_roles(
        "fw-directory-states-owner@auracles.space",
        ["contributor"],
    )
    admin_id = await create_user_with_roles(
        "fw-directory-states-admin@auracles.space", ["admin"]
    )
    draft_id = await create_draft_framework(client, contributor_id)
    suspended_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        suspended = await session.get(Framework, UUID(suspended_id))
        assert suspended is not None
        suspended.status = "suspended"
        await session.commit()

    response = await client.get(
        "/v1/admin/frameworks",
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    returned_ids = {item["framework_id"] for item in response.json()["items"]}
    assert draft_id not in returned_ids
    assert suspended_id not in returned_ids


async def test_admin_can_reinstate_suspended_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Admins can reverse a takedown, returning the Framework to the catalog."""
    contributor_id = await create_user_with_roles(
        "reinstate-owner@auracles.space",
        ["contributor"],
    )
    admin_id = await create_user_with_roles("reinstate-admin@auracles.space", ["admin"])
    admin_totp = await enable_admin_totp(admin_id)
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "suspended"
        framework.rejection_reason = "Earlier moderation hit."
        await session.commit()

    response = await client.post(
        f"/v1/admin/frameworks/{framework_id}/reinstate",
        json={"totp_code": pyotp.TOTP(admin_totp).now()},
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        # Reinstatement clears the takedown reason and republishes.
        assert framework.status == "published"
        assert framework.rejection_reason is None


async def test_admin_moderation_writes_require_step_up_code(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Suspend, reinstate, and rarity override each demand a valid admin code.

    These sit alongside user suspension and the escrow overrides, which were
    already gated. A stolen admin session must not be able to pull a
    contributor's published work from the catalog on its own.
    """
    contributor_id = await create_user_with_roles(
        "stepup-owner@auracles.space",
        ["contributor"],
    )
    admin_id = await create_user_with_roles("stepup-admin@auracles.space", ["admin"])
    await enable_admin_totp(admin_id)
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    headers = auth_headers(admin_id, ["admin"])
    suspend_without_code = await client.post(
        f"/v1/admin/frameworks/{framework_id}/suspend",
        json={"reason": "No step-up supplied."},
        headers=headers,
    )
    suspend_wrong_code = await client.post(
        f"/v1/admin/frameworks/{framework_id}/suspend",
        json={"reason": "Wrong step-up supplied.", "totp_code": "000000"},
        headers=headers,
    )
    reinstate_without_code = await client.post(
        f"/v1/admin/frameworks/{framework_id}/reinstate",
        json={},
        headers=headers,
    )
    override_without_code = await client.post(
        f"/v1/admin/frameworks/{framework_id}/rarity-block/override",
        json={"reason": "No step-up supplied for override."},
        headers=headers,
    )

    assert suspend_without_code.status_code == 422
    assert suspend_wrong_code.status_code == 422
    assert reinstate_without_code.status_code == 422
    assert override_without_code.status_code == 422
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        # The rejected takedown must not have moved the Framework.
        assert framework.status == "published"


async def test_admin_reinstate_rejects_non_suspended_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Reinstate only applies to suspended Frameworks; published returns 409."""
    contributor_id = await create_user_with_roles(
        "reinstate-noop-owner@auracles.space",
        ["contributor"],
    )
    admin_id = await create_user_with_roles(
        "reinstate-noop-admin@auracles.space", ["admin"]
    )
    admin_totp = await enable_admin_totp(admin_id)
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "published"
        await session.commit()

    response = await client.post(
        f"/v1/admin/frameworks/{framework_id}/reinstate",
        json={"totp_code": pyotp.TOTP(admin_totp).now()},
        headers=auth_headers(admin_id, ["admin"]),
    )

    assert response.status_code == 409


async def test_contributor_cannot_republish_suspended_framework(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A suspended Framework is a dead end for its owner — publish is refused.

    Locks the moderation guarantee: only an admin reinstate can return a
    suspended Framework to the catalog.
    """
    contributor_id = await create_user_with_roles(
        "suspended-republish@auracles.space",
        ["contributor"],
    )
    framework_id = await create_draft_framework(client, contributor_id)
    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        framework.status = "suspended"
        await session.commit()

    publish = await client.post(
        f"/v1/frameworks/{framework_id}/publish",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    assert publish.status_code == 409

    # The version-bump escape hatch is closed too.
    version = await client.post(
        f"/v1/frameworks/{framework_id}/versions",
        json={"change_type": "patch", "artifact_inheritance": {}},
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    assert version.status_code in {409, 422}

    async with async_session_factory() as session:
        framework = await session.get(Framework, UUID(framework_id))
        assert framework is not None
        assert framework.status == "suspended"


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


# Metadata edits are allowed on published/unpublished (see the live-edit tests)
# but blocked mid-pipeline; deletion stays draft-only for every non-draft status.
@pytest.mark.parametrize(
    ("framework_status", "update_status"),
    [("submitted", 409), ("published", 200)],
)
async def test_non_draft_framework_update_policy_and_delete_lock(
    framework_status: str,
    update_status: int,
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Mid-pipeline edits are blocked; deletion is always draft-only."""
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
        json={"title": "Edited"},
        headers=headers,
    )
    deleted = await client.delete(f"/v1/frameworks/{framework_id}", headers=headers)

    assert updated.status_code == update_status
    assert deleted.status_code == 409


async def _seed_drive_connection(
    user_id: UUID,
    *,
    access_token: str = "import-at",
) -> UUID:
    """Insert an active Drive connection for the copy-in tests."""
    from datetime import timedelta

    from app.core.security import encrypt_connector_token
    from app.modules.integrations.models import OAuthConnection

    async with async_session_factory() as session:
        async with session.begin():
            connection = OAuthConnection(
                user_id=user_id,
                provider="google_drive",
                access_token_encrypted=encrypt_connector_token(access_token),
                token_expires_at=datetime.now(UTC) + timedelta(hours=1),
                scopes="https://www.googleapis.com/auth/drive.readonly",
            )
            session.add(connection)
            await session.flush()
            return connection.id


def _mock_drive_file(
    respx_mock: Any,
    *,
    file_id: str,
    name: str,
    mime_type: str,
    size: str | None,
    content: bytes,
    export: bool = False,
    modified_time: str = "2026-07-08T00:00:00Z",
) -> None:
    """Mock the Drive metadata + download (or export) endpoints."""
    import httpx

    metadata: dict[str, Any] = {"id": file_id, "name": name, "mimeType": mime_type}
    if size is not None:
        metadata["size"] = size
    metadata["modifiedTime"] = modified_time
    base = f"https://www.googleapis.com/drive/v3/files/{file_id}"
    respx_mock.get(
        base, params__contains={"fields": "id,name,mimeType,size,modifiedTime"}
    ).mock(return_value=httpx.Response(200, json=metadata))
    if export:
        respx_mock.get(f"{base}/export").mock(
            return_value=httpx.Response(200, content=content)
        )
    else:
        respx_mock.get(base, params__contains={"alt": "media"}).mock(
            return_value=httpx.Response(200, content=content)
        )


async def test_import_from_connector_creates_processing_artifact(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing a binary Drive file copies bytes in and dispatches the scan."""
    import respx

    scanned: list[str] = []
    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(scanned.append)}),
    )
    contributor_id = await create_user_with_roles(
        "connector-import@auracles.space", ["contributor"]
    )
    framework_id = await create_draft_framework(client, contributor_id)
    connection_id = await _seed_drive_connection(contributor_id)

    with respx.mock as respx_mock:
        _mock_drive_file(
            respx_mock,
            file_id="file123",
            name="playbook.pdf",
            mime_type="application/pdf",
            size="13",
            content=b"dummy content",
        )
        response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/from-connector",
            headers=auth_headers(contributor_id, ["contributor"]),
            json={"connection_id": str(connection_id), "file_id": "file123"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "playbook.pdf"
    assert data["processing_status"] == "processing"
    assert data["file_size"] == len(b"dummy content")
    assert data["source_kind"] == "google_drive"
    assert scanned == [data["id"]]

    storage = framework_test_context["storage"]
    assert storage.uploaded_bytes
    _, key, body, mime_type = storage.uploaded_bytes[-1]
    assert body == b"dummy content"
    assert mime_type == "application/pdf"
    assert key.startswith(f"frameworks/{framework_id}/artifacts/")

    async with async_session_factory() as session:
        audit = (
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action == "artifact_uploaded")
                    .order_by(AuditLog.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
    assert audit is not None
    assert audit.metadata_["source"] == "google_drive"
    assert audit.metadata_["connection_id"] == str(connection_id)
    assert audit.metadata_["external_file_id"] == "file123"


async def test_import_from_connector_exports_google_native_docs(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Google Doc is exported to DOCX and named with the mapped extension."""
    import respx

    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    contributor_id = await create_user_with_roles(
        "connector-native@auracles.space", ["contributor"]
    )
    framework_id = await create_draft_framework(client, contributor_id)
    connection_id = await _seed_drive_connection(contributor_id)

    with respx.mock as respx_mock:
        _mock_drive_file(
            respx_mock,
            file_id="doc42",
            name="Strategy Notes",
            mime_type="application/vnd.google-apps.document",
            size=None,
            content=b"DOCX-BYTES",
            export=True,
        )
        response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/from-connector",
            headers=auth_headers(contributor_id, ["contributor"]),
            json={"connection_id": str(connection_id), "file_id": "doc42"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Strategy Notes.docx"
    assert data["file_size"] == len(b"DOCX-BYTES")

    storage = framework_test_context["storage"]
    _, key, body, mime_type = storage.uploaded_bytes[-1]
    assert body == b"DOCX-BYTES"
    assert mime_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert key.endswith(".docx")


async def test_import_from_connector_stamps_source_binding(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connector import records the Drive binding and drift baseline on the row."""
    import httpx
    import respx

    monkeypatch.setattr(
        "app.modules.frameworks.service.scan_artifact",
        type("FakeTask", (), {"delay": staticmethod(lambda _: None)}),
    )
    contributor_id = await create_user_with_roles(
        "connector-binding@auracles.space", ["contributor"]
    )
    framework_id = await create_draft_framework(client, contributor_id)
    connection_id = await _seed_drive_connection(contributor_id)

    with respx.mock as respx_mock:
        respx_mock.get("https://www.googleapis.com/drive/v3/files/f1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "f1",
                    "name": "brief.pdf",
                    "mimeType": "application/pdf",
                    "size": "13",
                    "modifiedTime": "2026-07-08T00:00:00Z",
                },
            )
        )
        respx_mock.get(
            "https://www.googleapis.com/drive/v3/files/f1",
            params__contains={"alt": "media"},
        ).mock(return_value=httpx.Response(200, content=b"dummy content"))
        response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/from-connector",
            headers=auth_headers(contributor_id, ["contributor"]),
            json={"connection_id": str(connection_id), "file_id": "f1"},
        )

    assert response.status_code == 200
    artifact_id = UUID(response.json()["id"])

    async with async_session_factory() as session:
        artifact = await session.get(Artifact, artifact_id)

    assert artifact is not None
    assert artifact.source_kind == "google_drive"
    assert artifact.source_external_id == "f1"
    assert str(artifact.source_connection_id) == str(connection_id)
    assert artifact.source_synced_revision == "2026-07-08T00:00:00Z"
    assert artifact.source_last_synced_at is not None


async def test_import_from_connector_rejects_unsupported_mime(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A Drive file whose effective MIME is not allowed returns 415."""
    import httpx
    import respx

    contributor_id = await create_user_with_roles(
        "connector-mime@auracles.space", ["contributor"]
    )
    framework_id = await create_draft_framework(client, contributor_id)
    connection_id = await _seed_drive_connection(contributor_id)

    with respx.mock as respx_mock:
        respx_mock.get("https://www.googleapis.com/drive/v3/files/vid1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "vid1",
                    "name": "clip.mp4",
                    "mimeType": "video/mp4",
                    "size": "10",
                },
            )
        )
        response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/from-connector",
            headers=auth_headers(contributor_id, ["contributor"]),
            json={"connection_id": str(connection_id), "file_id": "vid1"},
        )

    assert response.status_code == 415
    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count(Artifact.id)).where(
                Artifact.framework_id == UUID(framework_id)
            )
        )
    assert count == 0


async def test_import_from_connector_rejects_oversized_metadata(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """A file whose known size exceeds the budget 413s before downloading."""
    import httpx
    import respx

    contributor_id = await create_user_with_roles(
        "connector-size@auracles.space", ["contributor"]
    )
    framework_id = await create_draft_framework(client, contributor_id)
    connection_id = await _seed_drive_connection(contributor_id)

    with respx.mock as respx_mock:
        respx_mock.get("https://www.googleapis.com/drive/v3/files/big1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "big1",
                    "name": "huge.pdf",
                    "mimeType": "application/pdf",
                    "size": str(600 * 1024 * 1024),
                },
            )
        )
        response = await client.post(
            f"/v1/frameworks/{framework_id}/artifacts/from-connector",
            headers=auth_headers(contributor_id, ["contributor"]),
            json={"connection_id": str(connection_id), "file_id": "big1"},
        )

    assert response.status_code == 413


async def test_import_from_connector_foreign_connection_is_404(
    client: AsyncClient,
    migrated_database: None,
    framework_test_context: dict[str, Any],
) -> None:
    """Another user's connection id must not be usable for imports."""
    contributor_id = await create_user_with_roles(
        "connector-owner@auracles.space", ["contributor"]
    )
    other_id = await create_user_with_roles(
        "connector-other@auracles.space", ["contributor"]
    )
    framework_id = await create_draft_framework(client, contributor_id)
    foreign_connection_id = await _seed_drive_connection(other_id)

    response = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/from-connector",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={"connection_id": str(foreign_connection_id), "file_id": "f1"},
    )
    assert response.status_code == 404
