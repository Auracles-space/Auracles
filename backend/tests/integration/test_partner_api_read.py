"""Integration tests for Phase 5a Partner API marketplace reads."""

from __future__ import annotations

import hashlib
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

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
)
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    ApiKey,
    ApiRequestLog,
    DeveloperAccount,
    DeveloperApplication,
)
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
from app.modules.notifications.models import Notification
from app.shared.models.audit_log import AuditLog


class FakePartnerRedis:
    """Redis test double covering Partner API auth and preview rate limits."""

    def __init__(self) -> None:
        """Create empty counter and sliding-window state."""
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        """Set a string value, respecting NX."""
        if ex is not None:
            self.ttls[key] = ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def incr(self, key: str) -> int:
        """Increment and return an integer counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        """Record key expiry requests."""
        self.ttls[key] = seconds
        return True

    async def delete(self, *keys: str) -> int:
        """Delete fake Redis keys."""
        removed = 0
        for key in keys:
            removed += int(
                key in self.values or key in self.counters or key in self.sorted_sets
            )
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.sorted_sets.pop(key, None)
            self.ttls.pop(key, None)
        return removed

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        key: str,
        now_ms: int,
        window_ms: int,
        limit: int,
    ) -> list[int]:
        """Emulate the Partner API sliding-window Redis script."""
        bucket = self.sorted_sets.setdefault(key, {})
        cutoff = now_ms - window_ms
        for member, score in list(bucket.items()):
            if score < cutoff:
                bucket.pop(member, None)
        if len(bucket) >= limit:
            return [0, len(bucket)]
        bucket[f"{now_ms}:{len(bucket)}"] = float(now_ms)
        return [1, len(bucket)]


class FakePartnerStorage:
    """S3 storage test double for Partner preview URLs."""

    def __init__(self) -> None:
        """Create empty fake S3 request state."""
        self.presigned_get_requests: list[tuple[str, str, int]] = []

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a deterministic fake preview URL."""
        self.presigned_get_requests.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}?signature=fake"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure marketplace and Developer tables exist for Partner API tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def partner_read_context() -> AsyncIterator[dict[str, Any]]:
    """Reset marketplace/developer rows and install dependency overrides."""
    from app.integrations import s3

    fake_redis = FakePartnerRedis()
    fake_storage = FakePartnerStorage()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in dependency order so tests stay isolated."""
        async with async_session_factory() as session:
            await session.execute(update(Framework).values(preview_artifact_id=None))
            await session.execute(delete(ApiRequestLog))
            await session.execute(delete(Notification))
            await session.execute(delete(ApiKey))
            await session.execute(delete(DeveloperAccount))
            await session.execute(delete(DeveloperApplication))
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


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create an email-verified user for Partner API read tests."""
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
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


async def create_partner_key(raw_key: str, scopes: list[str]) -> UUID:
    """Create an active Partner API key with the requested scopes."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{raw_key}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=raw_key,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="developer",
                    approved_at=datetime.now(UTC),
                )
            )
            application = DeveloperApplication(
                user_id=user.id,
                company_name="Partner Read Co.",
                website="https://partner-read.example.com",
                use_case="Read public marketplace catalog through Partner API.",
                status="approved",
                reviewed_at=datetime.now(UTC),
            )
            session.add(application)
            await session.flush()
            account = DeveloperAccount(
                user_id=user.id,
                application_id=application.id,
                company_name=application.company_name,
            )
            session.add(account)
            await session.flush()
            api_key = ApiKey(
                developer_account_id=account.id,
                name="Partner read key",
                key_prefix=raw_key[:12],
                key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
                scopes=scopes,
            )
            session.add(api_key)
            await session.flush()
            return api_key.id


def api_key_headers(raw_key: str) -> dict[str, str]:
    """Return Partner API auth headers for a raw key."""
    return {"X-API-Key": raw_key}


async def create_framework(
    contributor_id: UUID,
    *,
    title: str,
    status: str = "published",
    with_preview: bool = False,
) -> tuple[UUID, UUID | None]:
    """Create a Framework and optional preview/current Artifact."""
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
            published_at=datetime.now(UTC) if status == "published" else None,
        )
        session.add(framework)
        preview_artifact_id: UUID | None = None
        if with_preview:
            preview = Artifact(
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
            licensed = Artifact(
                id=uuid4(),
                framework_id=framework.id,
                name="full.zip",
                file_key=f"frameworks/{framework.id}/artifacts/full.zip",
                file_size=4096,
                mime_type="application/zip",
                scan_status="clean",
                processing_status="processed",
                current_for_framework=True,
            )
            session.add_all([preview, licensed])
            await session.flush()
            framework.preview_artifact_id = preview.id
            preview_artifact_id = preview.id
        await session.commit()
        return framework.id, preview_artifact_id


async def create_framework_attestation(
    *,
    framework_id: UUID,
    requestor_id: UUID,
    attestor_id: UUID,
) -> UUID:
    """Create a public Framework-target Attestation report."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=framework_id,
                requestor_id=requestor_id,
                attestor_id=attestor_id,
                status="closed",
                outcome="approved",
                requested_specializations=["governance"],
                requested_jurisdictions=["US"],
                summary="Independent review completed.",
                scope="Review of implementation method and artifacts.",
                evidence_references={"private": "do-not-return"},
                report_key=f"attestation-reports/{uuid4()}/report.pdf",
                fee_amount=Decimal("250.00"),
                currency="USD",
                issued_at=datetime.now(UTC),
            )
            session.add(attestation)
            await session.flush()
            return attestation.id


async def test_partner_catalog_returns_only_published_frameworks(
    client: AsyncClient,
    migrated_database: None,
    partner_read_context: dict[str, Any],
) -> None:
    """Partner catalog reuses public Explore visibility and hides drafts."""
    del migrated_database, partner_read_context
    raw_key = "ak_partner_catalog"
    await create_partner_key(raw_key, ["catalog:read"])
    contributor_id = await create_user("partner-seller@auracles.space", ["contributor"])
    published_id, _ = await create_framework(
        contributor_id,
        title="Partner Visible Framework",
    )
    await create_framework(contributor_id, title="Hidden Draft", status="draft")

    response = await client.get(
        "/v1/partner/catalog",
        headers=api_key_headers(raw_key),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(published_id)
    assert body["items"][0]["title"] == "Partner Visible Framework"


async def test_partner_detail_and_preview_do_not_expose_full_artifacts(
    client: AsyncClient,
    migrated_database: None,
    partner_read_context: dict[str, Any],
) -> None:
    """Partner detail is public metadata; preview exposes only preview Artifact."""
    del migrated_database
    raw_key = "ak_partner_preview"
    await create_partner_key(raw_key, ["catalog:read", "preview:read"])
    contributor_id = await create_user(
        "partner-preview-seller@auracles.space",
        ["contributor"],
    )
    framework_id, preview_artifact_id = await create_framework(
        contributor_id,
        title="Preview Safe Framework",
        with_preview=True,
    )

    detail = await client.get(
        f"/v1/partner/catalog/{framework_id}",
        headers=api_key_headers(raw_key),
    )
    preview = await client.get(
        f"/v1/partner/catalog/{framework_id}/preview",
        headers=api_key_headers(raw_key),
    )

    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["id"] == str(framework_id)
    assert "artifacts" not in detail_body
    assert "preview_url" not in detail_body
    assert detail_body["preview_artifact_id"] == str(preview_artifact_id)
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["id"] == str(preview_artifact_id)
    assert preview_body["name"] == "preview.pdf"
    assert preview_body["preview_url"].startswith("https://s3.test/")
    assert "full.zip" not in preview.text
    storage = partner_read_context["storage"]
    assert len(storage.presigned_get_requests) == 1
    assert storage.presigned_get_requests[0][1].endswith("/preview.pdf")


async def test_partner_attestations_return_public_report_metadata_only(
    client: AsyncClient,
    migrated_database: None,
    partner_read_context: dict[str, Any],
) -> None:
    """Partner attestation reads expose report metadata without private evidence."""
    del migrated_database, partner_read_context
    raw_key = "ak_partner_attestations"
    await create_partner_key(raw_key, ["attestations:read"])
    contributor_id = await create_user(
        "partner-attested-seller@auracles.space",
        ["contributor"],
    )
    requestor_id = await create_user(
        "partner-attestation-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "partner-attestor@auracles.space",
        ["attestor"],
    )
    framework_id, _preview_id = await create_framework(
        contributor_id,
        title="Partner Attested Framework",
    )
    attestation_id = await create_framework_attestation(
        framework_id=framework_id,
        requestor_id=requestor_id,
        attestor_id=attestor_id,
    )

    response = await client.get(
        f"/v1/partner/catalog/{framework_id}/attestations",
        headers=api_key_headers(raw_key),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["attestations"][0]["id"] == str(attestation_id)
    assert body["attestations"][0]["status"] == "closed"
    assert body["attestations"][0]["outcome"] == "approved"
    assert body["attestations"][0]["report_key"].startswith("attestation-reports/")
    assert "evidence_references" not in response.text
    assert "escrow_id" not in response.text
    assert "fee_amount" not in response.text
    assert "private" not in response.text


async def test_partner_preview_requires_preview_scope(
    client: AsyncClient,
    migrated_database: None,
    partner_read_context: dict[str, Any],
) -> None:
    """Partner preview endpoint requires the narrow preview read scope."""
    del migrated_database, partner_read_context
    raw_key = "ak_partner_no_preview"
    await create_partner_key(raw_key, ["catalog:read"])
    contributor_id = await create_user(
        "partner-no-preview-seller@auracles.space",
        ["contributor"],
    )
    framework_id, _preview_artifact_id = await create_framework(
        contributor_id,
        title="Preview Scope Framework",
        with_preview=True,
    )

    response = await client.get(
        f"/v1/partner/catalog/{framework_id}/preview",
        headers=api_key_headers(raw_key),
    )

    assert response.status_code == 403
