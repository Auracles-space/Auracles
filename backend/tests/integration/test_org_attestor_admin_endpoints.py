"""Integration tests for the platform-admin org attestor review endpoints.

Covers the review queue and gate-walk routes under
/v1/admin/org-attestor-applications plus the capability suspend/reinstate/
revoke routes under /v1/admin/orgs, including RBAC (401/403) and the full
submit → start-trial → ... → approve walk.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestorTrial,
    AttestorTrialAnswerKey,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PayoutAccount
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations import (
    attestor_application_service as attestor_svc,
)
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgAttestorProfile,
    OrgCapability,
    OrgLegalProfile,
    OrgMember,
    OrgMemberNda,
)
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.integration.test_auth_sessions import FakeRedis

pytestmark = pytest.mark.asyncio

_QUEUE = "/v1/admin/org-attestor-applications"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_state() -> AsyncIterator[FakeRedis]:
    """Reset org attestor rows between tests; install fake Redis."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK order between tests."""
        async with async_session_factory() as session:
            await session.execute(delete(AttestorTrialAnswerKey))
            await session.execute(delete(AttestorTrial))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgAttestorApplication))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Organization))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(AuditLog))
            await session.commit()

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    await cleanup()
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()


def auth(user_id: UUID, roles: list[str] | None = None) -> dict[str, str]:
    """Build an Authorization header for the given user (with token roles)."""
    return {"Authorization": f"Bearer {create_access_token(user_id, roles or [])}"}


async def _new_user(
    prefix: str, *, roles: list[str] | None = None, totp_enabled: bool = False
) -> UUID:
    """Create a verified user with optional platform roles; return its id.

    ``totp_enabled`` enrols the user in 2FA so step-up gated admin writes can
    be reached once ``open_step_up_window`` seeds a window.
    """
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                totp_enabled=totp_enabled,
                totp_secret=(
                    encrypt_totp_secret("JBSWY3DPEHPK3PXP") if totp_enabled else None
                ),
            )
            session.add(user)
            await session.flush()
            for role in roles or []:
                session.add(UserRole(user_id=user.id, role=role))
            return user.id


async def _org(owner_id: UUID) -> UUID:
    """Create org + owner member + pending attestor capability; return org id."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"adm-{uuid4().hex[:6]}",
                name="Admin Endpoint Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            session.add(
                OrgCapability(org_id=org.id, capability="attestor", status="pending")
            )
            return org.id


async def _create_calibration_fixture(contributor_id: UUID) -> UUID:
    """Create one calibration fixture with a complete quality answer key."""
    async with async_session_factory() as session:
        async with session.begin():
            dimensions = (
                await session.scalars(
                    select(AttestationRubricDimension)
                    .where(
                        AttestationRubricDimension.review_type == "quality",
                        AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                    )
                    .order_by(AttestationRubricDimension.display_order.asc())
                )
            ).all()
            assert dimensions

            framework = Framework(
                id=uuid4(),
                contributor_id=contributor_id,
                title="Calibration Fixture",
                description="Calibration framework fixture.",
                version="1.0.0",
                status="published",
                is_calibration=True,
                calibration_review_type="quality",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk"],
                tags_text="risk",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
            )
            session.add(framework)
            await session.flush()

            session.add(
                Artifact(
                    framework_id=framework.id,
                    name="Fixture.pdf",
                    file_key="calibration/fixture.pdf",
                    file_size=1024,
                    mime_type="application/pdf",
                    scan_status="clean",
                )
            )

            for dimension in dimensions:
                session.add(
                    AttestorTrialAnswerKey(
                        framework_id=framework.id,
                        dimension_id=dimension.id,
                        expected_score=4,
                        tolerance=0,
                    )
                )
            await session.flush()
            return framework.id


async def _verify_org_kyb(org_id: UUID) -> None:
    """Mark the organization business-verified.

    KYB moved off the attestor application onto the org's legal profile, and
    is decided on the organization queue, so the attestor gate walk starts
    from an already-verified org rather than stamping KYB itself.
    """
    from datetime import UTC, datetime

    async with async_session_factory() as session:
        async with session.begin():
            profile = await session.scalar(
                select(OrgLegalProfile).where(OrgLegalProfile.org_id == org_id)
            )
            if profile is None:
                profile = OrgLegalProfile(
                    org_id=org_id, legal_name="Acme Attestations Ltd"
                )
                session.add(profile)
            profile.registration_number = "RC123456"
            profile.incorporation_doc_keys = ["org-incorporation-docs/seed/cert.pdf"]
            profile.kyb_status = "verified"
            profile.kyb_verified_at = datetime.now(UTC)


async def _gated_application(
    org_id: UUID, owner_id: UUID, *, seed_kyb_and_trial: bool = True
) -> UUID:
    """Create a submitted application with all gates satisfied; return its id.

    With ``seed_kyb_and_trial=False`` the passed trial is left off, so a test
    can drive the start-trial → approve walk through the real endpoints. KYB is
    an organization-level fact now and is seeded by ``_verify_org_kyb``.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            member = await session.scalar(
                select(OrgMember).where(
                    OrgMember.org_id == org_id, OrgMember.user_id == owner_id
                )
            )
            assert member is not None
            account = PayoutAccount(
                org_id=org_id,
                provider="stripe",
                provider_account_id=f"acct_{uuid4().hex[:12]}",
                provider_account_lookup_hash=uuid4().hex + uuid4().hex,
                account_type="express",
            )
            session.add(account)
            await session.flush()
            application = OrgAttestorApplication(
                org_id=org_id,
                status="submitted",
                specializations=[],
                sectors=["PE"],
                functions=["Compliance"],
                jurisdictions=["US"],
                credentials_summary="Two decades of PE compliance experience.",
                sample_work={},
                professional_references="Jane Roe, MD.",
                coi_declarations=[],
                coi_signed_at=now,
                coi_expires_at=now,
                confidentiality_signed_at=now,
                payout_account_id=account.id,
                tax_document_type="w9",
                tax_document_key="org-tax/key.pdf",
                trial_member_id=member.id,
            )
            session.add(application)
            await session.flush()
            if seed_kyb_and_trial:
                session.add(
                    AttestorTrial(
                        org_application_id=application.id,
                        org_id=org_id,
                        member_id=member.id,
                        status="passed",
                    )
                )
            application_id = application.id

    if seed_kyb_and_trial:
        # Approval now requires the organization to be business-verified, so a
        # fully-gated fixture verifies the org as well as passing the trial.
        await _verify_org_kyb(org_id)
    return application_id


async def test_queue_requires_admin(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """The queue rejects anonymous (401) and non-admin (403) callers."""
    plain_id = await _new_user("plain")
    assert (await client.get(_QUEUE)).status_code == 401
    assert (await client.get(_QUEUE, headers=auth(plain_id))).status_code == 403


async def test_queue_lists_and_filters(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """An admin lists the queue and filters it by status."""
    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    await _gated_application(org_id, owner_id)

    res = await client.get(_QUEUE, headers=auth(admin_id, ["admin"]))
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    # The gated fixture seeds a passed trial; the row must surface it so the
    # admin queue can gate Approve without opening the full application.
    assert body["applications"][0]["trial_status"] == "passed"
    # The org's attestor capability status rides along so the admin queue can
    # gate the suspend/reinstate/revoke controls; _org seeds it pending.
    assert body["applications"][0]["capability_status"] == "pending"

    filtered = await client.get(
        f"{_QUEUE}?status=needs_info", headers=auth(admin_id, ["admin"])
    )
    assert filtered.json()["total"] == 0


async def test_full_gate_walk_to_approval(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify-kyb → start-trial → approve activates the capability."""
    from app.integrations import s3

    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: True)

    notifications: list[dict[str, object]] = []

    class _FakeTask:
        def delay(self, **kwargs: object) -> None:
            notifications.append(kwargs)

    monkeypatch.setattr(attestor_svc, "dispatch_project_notification", _FakeTask())

    admin_id = await _new_user("admin", roles=["admin"], totp_enabled=True)
    await open_step_up_window(clean_state, admin_id)
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    fixture_id = await _create_calibration_fixture(owner_id)
    application_id = await _gated_application(
        org_id, owner_id, seed_kyb_and_trial=False
    )

    await _verify_org_kyb(org_id)

    trial = await client.post(
        f"{_QUEUE}/{application_id}/start-trial",
        headers=auth(admin_id, ["admin"]),
        json={"framework_id": str(fixture_id)},
    )
    assert trial.status_code == 200

    trial_view = await client.get(
        f"/v1/orgs/{org_id}/attestor-trial",
        headers=auth(owner_id),
    )
    assert trial_view.status_code == 200
    dimensions = trial_view.json()["dimensions"]

    submitted = await client.post(
        f"/v1/orgs/{org_id}/attestor-trial/submit",
        headers=auth(owner_id),
        json={
            "scores": [
                {"dimension_id": dimension["dimension_id"], "score": 4}
                for dimension in dimensions
            ]
        },
    )
    assert submitted.status_code == 200

    decided = await client.post(
        f"{_QUEUE}/{application_id}/trial/decide",
        headers=auth(admin_id, ["admin"]),
        json={"result": "pass", "feedback": "Solid calibration."},
    )
    assert decided.status_code == 200
    assert decided.json()["gate_checklist"]["trial_passed"] is True

    approved = await client.post(
        f"{_QUEUE}/{application_id}/approve", headers=auth(admin_id, ["admin"])
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # The owner must be told the outcome so they can start attesting.
    approved_notes = [
        n for n in notifications if n["notification_type"] == "org_attestor_approved"
    ]
    assert len(approved_notes) == 1
    assert approved_notes[0]["user_id"] == str(owner_id)

    async with async_session_factory() as session:
        capability = await session.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == "attestor",
            )
        )
        assert capability is not None and capability.status == "active"
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner_id, UserRole.role == "attestor"
            )
        )
        assert role is not None


async def test_admin_can_grade_and_decide_trial(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admin loads the grade view and decides a submitted trial.

    The decision is a trust grant, so it needs an open step-up window; the
    grade view and trial start do not.
    """
    from app.integrations import s3

    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: True)

    admin_id = await _new_user("admin", roles=["admin"], totp_enabled=True)
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    fixture_id = await _create_calibration_fixture(owner_id)
    application_id = await _gated_application(
        org_id, owner_id, seed_kyb_and_trial=False
    )

    await _verify_org_kyb(org_id)
    started = await client.post(
        f"{_QUEUE}/{application_id}/start-trial",
        headers=auth(admin_id, ["admin"]),
        json={"framework_id": str(fixture_id)},
    )
    assert started.status_code == 200

    trial_view = await client.get(
        f"/v1/orgs/{org_id}/attestor-trial",
        headers=auth(owner_id),
    )
    assert trial_view.status_code == 200
    dimensions = trial_view.json()["dimensions"]

    submitted = await client.post(
        f"/v1/orgs/{org_id}/attestor-trial/submit",
        headers=auth(owner_id),
        json={
            "scores": [
                {"dimension_id": dimension["dimension_id"], "score": 4}
                for dimension in dimensions
            ]
        },
    )
    assert submitted.status_code == 200

    grade = await client.get(
        f"{_QUEUE}/{application_id}/trial",
        headers=auth(admin_id, ["admin"]),
    )
    assert grade.status_code == 200
    assert grade.json()["status"] == "submitted"

    no_window = await client.post(
        f"{_QUEUE}/{application_id}/trial/decide",
        headers=auth(admin_id, ["admin"]),
        json={"result": "pass", "feedback": "Solid calibration."},
    )
    assert no_window.status_code == 403
    assert no_window.json()["detail"]["error_code"] == "step_up_required"

    await open_step_up_window(clean_state, admin_id)
    decided = await client.post(
        f"{_QUEUE}/{application_id}/trial/decide",
        headers=auth(admin_id, ["admin"]),
        json={"result": "pass", "feedback": "Solid calibration."},
    )
    assert decided.status_code == 200
    assert decided.json()["gate_checklist"]["trial_passed"] is True


async def test_approve_requires_step_up(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Approval activates a trust capability: 403 without a window, 200 with one."""
    admin_id = await _new_user("admin", roles=["admin"], totp_enabled=True)
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)

    no_window = await client.post(
        f"{_QUEUE}/{application_id}/approve", headers=auth(admin_id, ["admin"])
    )
    assert no_window.status_code == 403
    assert no_window.json()["detail"]["error_code"] == "step_up_required"

    await open_step_up_window(clean_state, admin_id)
    approved = await client.post(
        f"{_QUEUE}/{application_id}/approve", headers=auth(admin_id, ["admin"])
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


async def test_documents_returns_presigned_links(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admin gets one presigned link per incorporation and tax document."""
    from app.integrations import s3

    monkeypatch.setattr(
        s3.storage,
        "presigned_get",
        lambda bucket, key, expires_in, *, download_name=None: f"https://signed/{key}",
    )
    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: True)

    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)
    # The incorporation document hangs off the org's legal profile now, so the
    # attestor reviewer only sees one once the org has been through KYB.
    await _verify_org_kyb(org_id)

    res = await client.get(
        f"{_QUEUE}/{application_id}/documents", headers=auth(admin_id, ["admin"])
    )
    assert res.status_code == 200
    documents = res.json()["documents"]
    assert len(documents) == 2
    assert all(doc["available"] for doc in documents)
    assert all(doc["url"].startswith("https://signed/") for doc in documents)
    assert {doc["filename"] for doc in documents} == {"cert.pdf", "key.pdf"}


async def test_documents_flag_missing_objects(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reserved keys with no uploaded object come back flagged unavailable."""
    from app.integrations import s3

    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: False)

    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)

    res = await client.get(
        f"{_QUEUE}/{application_id}/documents", headers=auth(admin_id, ["admin"])
    )
    assert res.status_code == 200
    documents = res.json()["documents"]
    assert documents
    assert all(doc["available"] is False for doc in documents)
    assert all(doc["url"] == "" for doc in documents)


async def test_documents_requires_admin(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """The documents route rejects anonymous (401) and non-admin (403) callers."""
    plain_id = await _new_user("plain")
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)
    url = f"{_QUEUE}/{application_id}/documents"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=auth(plain_id))).status_code == 403


async def test_needs_info_and_reject(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Needs-info transitions the application; reject terminates it."""
    admin_id = await _new_user("admin", roles=["admin"], totp_enabled=True)
    await open_step_up_window(clean_state, admin_id)
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)

    held = await client.post(
        f"{_QUEUE}/{application_id}/needs-info",
        json={"feedback": "Clarify jurisdictions."},
        headers=auth(admin_id, ["admin"]),
    )
    assert held.status_code == 200
    assert held.json()["status"] == "needs_info"

    # The admin queue must surface the feedback the admin sent, so the
    # reviewer can see what they asked the org to clarify.
    queue = await client.get(
        f"{_QUEUE}?status=needs_info", headers=auth(admin_id, ["admin"])
    )
    assert queue.status_code == 200
    row = next(
        item
        for item in queue.json()["applications"]
        if item["id"] == str(application_id)
    )
    assert row["admin_feedback"] == "Clarify jurisdictions."

    rejected = await client.post(
        f"{_QUEUE}/{application_id}/reject",
        json={"feedback": "Not a fit at this time."},
        headers=auth(admin_id, ["admin"]),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


async def test_capability_suspend_reinstate_revoke(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Suspend/reinstate/revoke drive the derived role and profile state."""
    admin_id = await _new_user("admin", roles=["admin"], totp_enabled=True)
    await open_step_up_window(clean_state, admin_id)
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    application_id = await _gated_application(org_id, owner_id)
    await client.post(
        f"{_QUEUE}/{application_id}/approve", headers=auth(admin_id, ["admin"])
    )

    base = f"/v1/admin/orgs/{org_id}/attestor-capability"
    assert (
        await client.post(f"{base}/suspend", headers=auth(admin_id, ["admin"]))
    ).status_code == 204

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == owner_id, UserRole.role == "attestor"
            )
        )
        assert role is None

    assert (
        await client.post(f"{base}/reinstate", headers=auth(admin_id, ["admin"]))
    ).status_code == 204
    assert (
        await client.post(f"{base}/revoke", headers=auth(admin_id, ["admin"]))
    ).status_code == 204

    async with async_session_factory() as session:
        profile = await session.scalar(
            select(OrgAttestorProfile).where(OrgAttestorProfile.org_id == org_id)
        )
        assert profile is not None and profile.active is False


async def test_capability_routes_require_admin(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Capability routes reject anonymous (401) and non-admin (403) callers."""
    plain_id = await _new_user("plain")
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    base = f"/v1/admin/orgs/{org_id}/attestor-capability/suspend"
    assert (await client.post(base)).status_code == 401
    assert (await client.post(base, headers=auth(plain_id))).status_code == 403


_FIXTURES = "/v1/admin/org-attestor-applications/calibration-fixtures"


async def _bare_fixture(contributor_id: UUID) -> UUID:
    """Create a calibration fixture with a complete key but no artifacts."""
    async with async_session_factory() as session:
        async with session.begin():
            dimensions = (
                await session.scalars(
                    select(AttestationRubricDimension).where(
                        AttestationRubricDimension.review_type == "quality",
                        AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                    )
                )
            ).all()
            framework = Framework(
                id=uuid4(),
                contributor_id=contributor_id,
                title="Bare Fixture",
                description="No artifacts yet.",
                version="1.0.0",
                status="published",
                is_calibration=True,
                calibration_review_type="quality",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk"],
                tags_text="risk",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
            )
            session.add(framework)
            await session.flush()
            for dimension in dimensions:
                session.add(
                    AttestorTrialAnswerKey(
                        framework_id=framework.id,
                        dimension_id=dimension.id,
                        expected_score=4,
                        tolerance=0,
                    )
                )
            return framework.id


async def test_admin_fixture_artifact_upload_confirm_list_delete(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin uploads, confirms, lists, and deletes a fixture artifact."""
    from app.integrations import s3
    from app.modules.organizations import attestor_trial_service

    monkeypatch.setattr(
        s3.storage,
        "presigned_post",
        lambda **kwargs: {"url": "https://s3.example/u", "fields": {"key": "v"}},
    )
    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: True)
    deleted: list[str] = []
    monkeypatch.setattr(
        s3.storage, "delete_object", lambda bucket, key: deleted.append(key)
    )
    scanned: list[str] = []

    class _FakeScan:
        def delay(self, artifact_id: str) -> None:
            scanned.append(artifact_id)

    monkeypatch.setattr(attestor_trial_service, "scan_artifact", _FakeScan())

    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    fixture_id = await _bare_fixture(owner_id)

    url_res = await client.post(
        f"{_FIXTURES}/{fixture_id}/artifacts/upload-url",
        headers=auth(admin_id, ["admin"]),
        json={
            "filename": "sample.pdf",
            "mime_type": "application/pdf",
            "file_size": 2048,
        },
    )
    assert url_res.status_code == 200
    artifact_id = url_res.json()["artifact_id"]

    confirm_res = await client.post(
        f"{_FIXTURES}/{fixture_id}/artifacts/confirm",
        headers=auth(admin_id, ["admin"]),
        json={"artifact_id": artifact_id},
    )
    assert confirm_res.status_code == 200
    assert scanned == [artifact_id]

    list_res = await client.get(
        f"{_FIXTURES}/{fixture_id}/artifacts", headers=auth(admin_id, ["admin"])
    )
    assert list_res.status_code == 200
    assert [a["id"] for a in list_res.json()["artifacts"]] == [artifact_id]

    del_res = await client.delete(
        f"{_FIXTURES}/{fixture_id}/artifacts/{artifact_id}",
        headers=auth(admin_id, ["admin"]),
    )
    assert del_res.status_code == 204
    assert deleted and deleted[0].endswith(".pdf")

    empty = await client.get(
        f"{_FIXTURES}/{fixture_id}/artifacts", headers=auth(admin_id, ["admin"])
    )
    assert empty.json()["artifacts"] == []


async def test_admin_fixture_artifact_confirm_without_object_409(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirming before the object lands in S3 is 409."""
    from app.integrations import s3

    monkeypatch.setattr(
        s3.storage,
        "presigned_post",
        lambda **kwargs: {"url": "https://s3.example/u", "fields": {"key": "v"}},
    )
    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: False)

    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    fixture_id = await _bare_fixture(owner_id)

    url_res = await client.post(
        f"{_FIXTURES}/{fixture_id}/artifacts/upload-url",
        headers=auth(admin_id, ["admin"]),
        json={"filename": "s.pdf", "mime_type": "application/pdf", "file_size": 10},
    )
    artifact_id = url_res.json()["artifact_id"]
    confirm_res = await client.post(
        f"{_FIXTURES}/{fixture_id}/artifacts/confirm",
        headers=auth(admin_id, ["admin"]),
        json={"artifact_id": artifact_id},
    )
    assert confirm_res.status_code == 409


async def test_admin_fixture_artifact_routes_require_admin(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
) -> None:
    """Fixture-artifact routes reject anonymous (401) and non-admin (403)."""
    plain_id = await _new_user("plain")
    owner_id = await _new_user("owner")
    fixture_id = await _bare_fixture(owner_id)
    path = f"{_FIXTURES}/{fixture_id}/artifacts"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=auth(plain_id))).status_code == 403


async def test_start_trial_rejects_fixture_without_clean_artifact(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
) -> None:
    """A fixture whose artifacts are unscanned cannot start a trial (422)."""
    admin_id = await _new_user("admin", roles=["admin"])
    owner_id = await _new_user("owner")
    org_id = await _org(owner_id)
    fixture_id = await _bare_fixture(owner_id)
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Artifact(
                    framework_id=fixture_id,
                    name="pending.pdf",
                    file_key="calibration/pending.pdf",
                    file_size=1024,
                    mime_type="application/pdf",
                    scan_status="pending",
                )
            )
    application_id = await _gated_application(
        org_id, owner_id, seed_kyb_and_trial=False
    )
    await _verify_org_kyb(org_id)
    res = await client.post(
        f"{_QUEUE}/{application_id}/start-trial",
        headers=auth(admin_id, ["admin"]),
        json={"framework_id": str(fixture_id)},
    )
    assert res.status_code == 422
