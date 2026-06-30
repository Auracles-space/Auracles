"""Attestation artifact-access presign + audit coverage (§2.5)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, delete, func, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.integrations import s3
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationArtifactAccess,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
    AttestorApplication,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, Transaction
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# S3 Stub
# ---------------------------------------------------------------------------

class FakeDownloadStorage:
    """S3 storage test double for licensed Artifact downloads."""

    def __init__(self) -> None:
        self.presigned_get_requests: list[tuple[str, str, int]] = []
        self.counter = 0

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        self.counter += 1
        self.presigned_get_requests.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}?download={self.counter}"

@pytest.fixture
def stub_s3(monkeypatch: pytest.MonkeyPatch) -> FakeDownloadStorage:
    fake = FakeDownloadStorage()
    monkeypatch.setattr(s3, "storage", fake)
    return fake


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def _reset_state() -> None:
    """Remove attestation/user test rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(AttestationArtifactAccess))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(AttestorApplication))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            from sqlalchemy import update
            await session.execute(update(Framework).values(preview_artifact_id=None))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is at alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        sync_engine.dispose()

@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Clean attestation/user state before and after the test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()

@pytest.fixture
async def db_session(clean_state) -> AsyncIterator:
    del clean_state
    async with async_session_factory() as session:
        yield session

@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client

# ---------------------------------------------------------------------------
# Users & Auth
# ---------------------------------------------------------------------------

async def _create_user(role_name: str, prefix: str) -> User:
    async with async_session_factory() as session:
        user = User(
            email=f"{prefix}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name=prefix,
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role=role_name,
                approved_at=datetime.now(UTC),
            )
        )
        await session.commit()
        await session.refresh(user)
    return user


@pytest.fixture
async def operator(clean_state) -> User:
    return await _create_user("operator", "access-operator")

@pytest.fixture
async def attestor(clean_state) -> User:
    return await _create_user("attestor", "access-attestor")

@pytest.fixture
async def other_attestor(clean_state) -> User:
    return await _create_user("attestor", "access-other")

@pytest.fixture
def attestor_auth(attestor: User) -> dict[str, str]:
    token = create_access_token(attestor.id, ["attestor"])
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def other_attestor_auth(other_attestor: User) -> dict[str, str]:
    token = create_access_token(other_attestor.id, ["attestor"])
    return {"Authorization": f"Bearer {token}"}

# ---------------------------------------------------------------------------
# Data Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def framework_with_artifact(operator: User) -> tuple[Framework, Artifact]:
    async with async_session_factory() as session:
        framework = Framework(
            contributor_id=operator.id,
            title="Access Test Framework",
            description="Framework for access-scope integration tests.",
            status="published",
            category="compliance",
            tags=["test"],
            price=Decimal("199.00"),
            license_types=["single_user"],
            published_at=datetime.now(UTC),
        )
        session.add(framework)
        await session.flush()
        
        artifact = Artifact(
            framework_id=framework.id,
            name="main_doc.pdf",
            file_key="frameworks/access_test/main_doc.pdf",
            file_size=1024,
            mime_type="application/pdf",
            scan_status="clean",
        )
        session.add(artifact)
        await session.commit()
        await session.refresh(framework)
        await session.refresh(artifact)
    return framework, artifact

@pytest.fixture
async def framework_artifact(
    framework_with_artifact: tuple[Framework, Artifact]
) -> Artifact:
    return framework_with_artifact[1]

@pytest.fixture
async def accepted_attestation(
    framework_with_artifact: tuple[Framework, Artifact],
    operator: User,
    attestor: User
) -> Attestation:
    framework, _ = framework_with_artifact
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="framework",
            target_id=framework.id,
            requestor_id=operator.id,
            attestor_id=attestor.id,
            status="accepted",
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            content_ack_at=datetime.now(UTC),
            content_ack_version="v1",
        )
        session.add(attestation)
        await session.commit()
        await session.refresh(attestation)
    return attestation

@pytest.fixture
async def offered_attestation(
    framework_with_artifact: tuple[Framework, Artifact],
    operator: User,
    attestor: User
) -> Attestation:
    framework, _ = framework_with_artifact
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="framework",
            target_id=framework.id,
            requestor_id=operator.id,
            attestor_id=None,
            status="offered",
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
        )
        session.add(attestation)
        await session.flush()
        
        offer = AttestationOffer(
            attestation_id=attestation.id,
            attestor_id=attestor.id,
            cohort_index=0,
            status="offered",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(offer)
        await session.commit()
        await session.refresh(attestation)
    return attestation


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_assigned_attestor_full_access_logs(
    client, attestor_auth, accepted_attestation, framework_artifact, db_session, stub_s3
):
    """The assigned attestor gets a presigned URL and the access is logged."""
    resp = await client.post(
        f"/v1/attestations/{accepted_attestation.id}"
        f"/artifacts/{framework_artifact.id}/access",
        headers=attestor_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["download_url"]
    count = await db_session.scalar(
        select(func.count())
        .select_from(AttestationArtifactAccess)
        .where(AttestationArtifactAccess.attestation_id == accepted_attestation.id)
    )
    assert count == 1


async def test_preview_scope_rejects_non_preview_artifact(
    client, attestor_auth, offered_attestation, framework_artifact, stub_s3
):
    """A cohort member (preview scope) cannot presign a non-preview artifact."""
    resp = await client.post(
        f"/v1/attestations/{offered_attestation.id}"
        f"/artifacts/{framework_artifact.id}/access",
        headers=attestor_auth,
    )
    assert resp.status_code == 403


async def test_outsider_gets_forbidden(
    client, other_attestor_auth, accepted_attestation, framework_artifact
):
    """A user with no entitlement is forbidden."""
    resp = await client.post(
        f"/v1/attestations/{accepted_attestation.id}"
        f"/artifacts/{framework_artifact.id}/access",
        headers=other_attestor_auth,
    )
    assert resp.status_code in (403, 404)


@pytest.fixture
async def preview_artifact(
    framework_with_artifact: tuple[Framework, Artifact]
) -> Artifact:
    framework, _ = framework_with_artifact
    async with async_session_factory() as session:
        artifact = Artifact(
            framework_id=framework.id,
            name="preview_doc.pdf",
            file_key="frameworks/access_test/preview_doc.pdf",
            file_size=500,
            mime_type="application/pdf",
            scan_status="clean",
        )
        session.add(artifact)
        await session.commit()
        
        fw = await session.get(Framework, framework.id)
        fw.preview_artifact_id = artifact.id
        await session.commit()
        await session.refresh(artifact)
    return artifact


async def test_package_full_lists_all_artifacts(
    client: AsyncClient,
    attestor_auth: dict[str, str],
    accepted_attestation: Attestation,
    framework_artifact: Artifact,
) -> None:
    """The assigned attestor's package reports full scope and lists all artifacts."""
    resp = await client.get(
        f"/v1/attestations/{accepted_attestation.id}/package",
        headers=attestor_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entitlement"] == "full"
    assert any(a["id"] == str(framework_artifact.id) for a in body["artifacts"])


async def test_package_preview_lists_only_preview(
    client: AsyncClient,
    attestor_auth: dict[str, str],
    offered_attestation: Attestation,
    framework_artifact: Artifact,
    preview_artifact: Artifact,
) -> None:
    """A cohort member's package reports preview scope and only preview artifacts."""
    resp = await client.get(
        f"/v1/attestations/{offered_attestation.id}/package",
        headers=attestor_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["entitlement"] == "preview"
    ids = {a["id"] for a in body["artifacts"]}
    assert str(preview_artifact.id) in ids
    assert str(framework_artifact.id) not in ids


async def test_package_outsider_not_found(
    client: AsyncClient,
    other_attestor_auth: dict[str, str],
    accepted_attestation: Attestation,
) -> None:
    """A non-participant cannot see the package."""
    resp = await client.get(
        f"/v1/attestations/{accepted_attestation.id}/package",
        headers=other_attestor_auth,
    )
    assert resp.status_code == 404
