"""End-to-end lifecycle test for organizations as Attestors.

Drives one attestor organization through the whole real-endpoint journey:
application → 8-gate activation → capability active + derived member role →
offer accepted-and-staffed → the reviewing member acknowledges content, runs
the review, and submits the report → the requestor accepts and escrow settles
to the organization → org earnings and a TOTP-gated org payout → the public
directory lists the organization under its own identity.

Payment rails (Stripe/Paystack) and calibration-trial grading are out-of-band,
so their primitives are seeded directly; every org state transition under test
runs through the shipped HTTP endpoints. Enforces the full re-point of
docs/superpowers/specs/2026-07-04-org-attestor-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select, update

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_payout_provider_account_id,
    encrypt_totp_secret,
    hash_password,
    hash_payout_provider_account_id,
)
from app.main import app
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationOffer,
    AttestationRubricDimension,
    AttestationRubricScore,
    AttestorTrial,
    AttestorTrialAnswerKey,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.modules.financials.models import (
    Escrow,
    FinancialEvent,
    Payout,
    PayoutAccount,
    Transaction,
)
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from app.shared.models.audit_log import AuditLog
from tests.integration.test_auth_sessions import FakeRedis

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def trial_notifications(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Capture nomination notifications instead of enqueuing to the real broker.

    `nominate_trial_member` fires `dispatch_project_notification.delay`; without
    this stub the shared dev worker would consume a task for a user that only
    exists in the test database and log a spurious failure. Recorded rather
    than dropped so tests can assert where the nominee is actually sent.
    """
    from app.modules.organizations import attestor_application_service as _svc

    sent: list[dict[str, object]] = []

    class _RecordingDispatch:
        def delay(self, **kwargs: object) -> None:
            sent.append(kwargs)

    monkeypatch.setattr(_svc, "dispatch_project_notification", _RecordingDispatch())
    return sent

NDA_VERSION = get_settings().org_member_nda_version

# The eight quality-rubric dimension keys the reviewing member must score.
_QUALITY_DIMENSIONS = (
    "completeness",
    "implementability",
    "accuracy",
    "clarity",
    "version_currency",
    "appropriate_scope",
    "risk_flags",
    "recommended_use_cases",
)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database: None) -> AsyncIterator[FakeRedis]:
    """Reset every touched table in FK-safe order; install a fake Redis."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK order between test runs."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AuditLog))
                await session.execute(delete(FinancialEvent))
                await session.execute(delete(Payout))
                await session.execute(delete(AttestationRubricScore))
                await session.execute(delete(AttestationAnnotation))
                await session.execute(delete(AttestationOffer))
                await session.execute(delete(Attestation))
                await session.execute(delete(Escrow))
                await session.execute(delete(Transaction))
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
                await session.execute(delete(User))

    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    await cleanup()
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


def _auth(user_id: UUID) -> dict[str, str]:
    """Build a bearer Authorization header for one user."""
    return {"Authorization": f"Bearer {create_access_token(user_id, [])}"}


async def _new_user(prefix: str, *, totp_secret: str | None = None) -> UUID:
    """Create a verified user (optionally TOTP-enabled); return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                totp_enabled=totp_secret is not None,
                totp_secret=(
                    encrypt_totp_secret(totp_secret)
                    if totp_secret is not None
                    else None
                ),
            )
            session.add(user)
            await session.flush()
            return user.id


async def _org_with_members(
    owner_id: UUID, member_id: UUID
) -> tuple[UUID, UUID, UUID]:
    """Create an org with a pending attestor capability + owner and member.

    Both members sign the current NDA (needed to nominate/staff them). Returns
    (org_id, owner_member_id, reviewing_member_id).
    """
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"lc-{uuid4().hex[:6]}",
                name="Lifecycle Attestor Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            owner_member = OrgMember(org_id=org.id, user_id=owner_id, role="owner")
            reviewer_member = OrgMember(
                org_id=org.id, user_id=member_id, role="member"
            )
            session.add_all([owner_member, reviewer_member])
            await session.flush()
            session.add_all(
                [
                    OrgMemberNda(member_id=owner_member.id, nda_version=NDA_VERSION),
                    OrgMemberNda(member_id=reviewer_member.id, nda_version=NDA_VERSION),
                    OrgCapability(
                        org_id=org.id, capability="attestor", status="pending"
                    ),
                ]
            )
            return org.id, owner_member.id, reviewer_member.id


async def _org_payout_account(org_id: UUID) -> UUID:
    """Create a verified org-owned payout account; return its id."""
    provider_account_id = f"acct_{uuid4().hex}"
    async with async_session_factory() as session:
        async with session.begin():
            account = PayoutAccount(
                org_id=org_id,
                provider="stripe",
                provider_account_id=encrypt_payout_provider_account_id(
                    provider_account_id
                ),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    provider_account_id
                ),
                account_type="express",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(account)
            await session.flush()
            return account.id


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
                title="Lifecycle Calibration Fixture",
                description="Lifecycle calibration framework fixture.",
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


def _application_body() -> dict[str, object]:
    """Return a complete attestor-application create body."""
    return {
        "legal_name": "Lifecycle Attestations Ltd",
        "registration_number": "RC998877",
        "sectors": ["private_equity"],
        "functions": ["compliance"],
        "jurisdictions": ["united_states"],
        "credentials_summary": "Chartered reviewers with two decades of practice.",
        "sample_work": {"portfolio": "https://example.com/lifecycle"},
        "professional_references": "Jane Roe, MD of Example Capital.",
    }


async def _seed_funded_offer(org_id: UUID) -> tuple[UUID, UUID, UUID]:
    """Seed an offered, fully funded attestation for the org.

    Mirrors the post-payment state matching would produce: a held fee escrow
    and a completed ``attestation_fee`` transaction with no payee yet (the org
    is credited only at settlement). Returns (requestor_id, attestation_id,
    offer_id).
    """
    requestor_id = await _new_user("requestor")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="contributor",
                target_id=uuid4(),
                requestor_id=requestor_id,
                status="offered",
                review_type="quality",
                fee_amount=Decimal("500.00"),
                currency="USD",
                requested_specializations=["tax"],
                requested_jurisdictions=["US"],
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=requestor_id,
                payee_id=None,
                payee_org_id=None,
                amount=Decimal("500.00"),
                currency="USD",
                # Stamped at the 10% attestation rate, as settlement writes it.
                platform_commission=Decimal("50.00"),
                net_amount=Decimal("450.00"),
                transaction_type="attestation_fee",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_{uuid4().hex}",
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=attestation.id,
                ref_type="attestation",
                amount=Decimal("500.00"),
                currency="USD",
                status="held",
                release_conditions={"kind": "attestation"},
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            attestation.escrow_id = escrow.id
            offer = AttestationOffer(
                attestation_id=attestation.id,
                org_id=org_id,
                cohort_index=0,
                status="offered",
                offered_at=now,
                expires_at=now + timedelta(hours=48),
            )
            session.add(offer)
            await session.flush()
            return requestor_id, attestation.id, offer.id


async def _pass_trial(application_id: UUID) -> None:
    """Grade the (stubbed) calibration trial as passed.

    Calibration grading is an out-of-band admin activity with no shipped
    endpoint; the approval gate only reads the passed flag.
    """
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(AttestorTrial)
                .where(AttestorTrial.org_application_id == application_id)
                .values(status="passed")
            )


async def test_org_attestor_full_lifecycle(
    client: AsyncClient,
    clean_state: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    trial_notifications: list[dict[str, object]],
) -> None:
    """One organization travels application → activation → attested settlement.

    Proves the shipped endpoints compose: activation makes the capability real,
    a staffed member performs a real review, settlement credits the org (never a
    member), and the org's public identity carries the attestation.
    """
    del clean_state
    # Uploads reserve S3 keys but never PUT objects in tests, so treat the
    # objects as present for the KYB-verify existence gate.
    from app.integrations import s3

    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: True)
    owner_secret = pyotp.random_base32()
    owner_id = await _new_user("owner", totp_secret=owner_secret)
    reviewer_user_id = await _new_user("reviewer")
    fixture_id = await _create_calibration_fixture(owner_id)
    org_id, _owner_member_id, reviewer_member_id = await _org_with_members(
        owner_id, reviewer_user_id
    )
    payout_account_id = await _org_payout_account(org_id)
    admin_secret = pyotp.random_base32()
    admin_id = await _new_user("admin", totp_secret=admin_secret)
    admin_headers = {
        "Authorization": f"Bearer {create_access_token(admin_id, ['admin'])}"
    }
    app_base = f"/v1/orgs/{org_id}/attestor-application"

    # --- Activation: owner-driven gates ----------------------------------
    created = await client.post(
        app_base, json=_application_body(), headers=_auth(owner_id)
    )
    assert created.status_code == 201
    application_id = UUID(created.json()["id"])

    linked = await client.patch(
        app_base,
        json={"payout_account_id": str(payout_account_id)},
        headers=_auth(owner_id),
    )
    assert linked.status_code == 200

    tax = await client.post(
        f"{app_base}/tax-document",
        json={
            "tax_document_type": "w9",
            "file_name": "w9.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
        },
        headers=_auth(owner_id),
    )
    assert tax.status_code == 200

    undertakings = await client.post(
        f"{app_base}/sign-undertakings",
        json={
            "declarations": [],
            "accept_policy": True,
            "accept_confidentiality": True,
            "totp_code": pyotp.TOTP(owner_secret).now(),
        },
        headers=_auth(owner_id),
    )
    assert undertakings.status_code == 200

    nominated = await client.post(
        f"{app_base}/nominate-trial-member",
        json={"member_id": str(reviewer_member_id)},
        headers=_auth(owner_id),
    )
    assert nominated.status_code == 200
    # The nominee is a plain member, so the link has to land on a page a member
    # can actually open. The attestor-application tab behind /attestor is
    # owner/admin only, and pointing there left the nominee staring at a load
    # failure on the one page they were told to open.
    nomination = next(
        call
        for call in trial_notifications
        if call["notification_type"] == "org_attestor_trial_nominated"
    )
    assert nomination["link"] == (
        f"/dashboard/organizations/{org_id}/attestor-trial"
    )

    submitted = await client.post(f"{app_base}/submit", headers=_auth(owner_id))
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"

    # --- Business verification (KYB) --------------------------------------
    # Precedes every capability now, so the org establishes and verifies its
    # legal identity before the attestor gate walk can approve anything.
    legal = await client.put(
        f"/v1/orgs/{org_id}/legal-profile",
        json={
            "legal_name": "Auracles Attestations Ltd",
            "registration_number": "RC123456",
            # TOTP is single-use (M4) and only ±1 step is accepted, so the
            # three owner step-ups in this test take one step each: undertakings
            # spends `now`, the payout below spends `+30`, and this takes `-30`.
            "totp_code": pyotp.TOTP(owner_secret).at(
                datetime.now(UTC) - timedelta(seconds=30)
            ),
        },
        headers=_auth(owner_id),
    )
    assert legal.status_code in (200, 201), legal.text
    doc = await client.post(
        f"/v1/orgs/{org_id}/kyb/incorporation-document",
        json={
            "file_name": "certificate.pdf",
            "content_type": "application/pdf",
            "size_bytes": 4096,
        },
        headers=_auth(owner_id),
    )
    assert doc.status_code == 200
    submitted_kyb = await client.post(
        f"/v1/orgs/{org_id}/kyb/submit", headers=_auth(owner_id)
    )
    assert submitted_kyb.status_code == 200, submitted_kyb.text
    assert submitted_kyb.json()["kyb_status"] == "pending"
    reviewed = await client.post(
        f"/v1/admin/orgs/{org_id}/kyb/review",
        json={
            "verdict": "verified",
            "totp_code": pyotp.TOTP(admin_secret).now(),
        },
        headers=admin_headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["kyb_status"] == "verified"

    # --- Activation: admin gate walk -------------------------------------
    admin_base = f"/v1/admin/org-attestor-applications/{application_id}"
    assert (
        await client.post(
            f"{admin_base}/start-trial",
            headers=admin_headers,
            json={"framework_id": str(fixture_id)},
        )
    ).status_code == 200
    await _pass_trial(application_id)
    approved = await client.post(f"{admin_base}/approve", headers=admin_headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    async with async_session_factory() as session:
        capability = await session.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == "attestor",
            )
        )
        derived_role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == reviewer_user_id, UserRole.role == "attestor"
            )
        )
    assert capability is not None and capability.status == "active"
    assert derived_role is not None  # member gained the derived attestor role

    # --- Offer accepted and staffed --------------------------------------
    requestor_id, attestation_id, offer_id = await _seed_funded_offer(org_id)
    staffed = await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{offer_id}/accept",
        json={"reviewing_member_id": str(reviewer_member_id)},
        headers=_auth(owner_id),
    )
    assert staffed.status_code == 200
    assert staffed.json()["status"] == "accepted"

    # --- Reviewing member performs the review ----------------------------
    acked = await client.post(
        f"/v1/attestations/{attestation_id}/content-ack",
        json={"content_ack": True, "ack_version": "v1"},
        headers=_auth(reviewer_user_id),
    )
    assert acked.status_code == 200

    started = await client.post(
        f"/v1/attestations/{attestation_id}/start-review",
        headers=_auth(reviewer_user_id),
    )
    assert started.status_code == 200
    assert started.json()["status"] == "in_review"

    for dimension_key in _QUALITY_DIMENSIONS:
        scored = await client.put(
            f"/v1/attestations/{attestation_id}/rubric/{dimension_key}",
            json={
                "score": 5,
                "comment": (
                    f"The {dimension_key} dimension is fully addressed and "
                    "supports an approval determination without reservation."
                ),
            },
            headers=_auth(reviewer_user_id),
        )
        assert scored.status_code == 200

    report = await client.post(
        f"/v1/attestations/{attestation_id}/report",
        json={
            "outcome": "approved",
            "summary": " ".join(["evidence"] * 250),
            "scope": "Credential, process, and sample evidence review of record.",
            "conditions": None,
            "evidence_references": {},
        },
        headers=_auth(reviewer_user_id),
    )
    assert report.status_code == 200
    assert report.json()["status"] == "report_submitted"

    # --- Requestor accepts; escrow settles to the org --------------------
    # The accept-report route is requestor-gated (contributor/operator role
    # claim); the attestation requestor holds the contributor role.
    requestor_headers = {
        "Authorization": f"Bearer {create_access_token(requestor_id, ['contributor'])}"
    }
    accepted = await client.post(
        f"/v1/attestations/{attestation_id}/accept-report",
        headers=requestor_headers,
    )
    assert accepted.status_code == 200

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.ref_id == attestation_id)
        )
        escrow = await session.scalar(
            select(Escrow).where(Escrow.ref_id == attestation_id)
        )
    assert transaction is not None
    assert transaction.payee_org_id == org_id  # org credited
    assert transaction.payee_id is None  # never the reviewing member
    assert escrow is not None and escrow.status == "released"

    # --- Org earnings + TOTP-gated org payout ----------------------------
    earnings = await client.get(
        f"/v1/orgs/{org_id}/financials/earnings", headers=_auth(owner_id)
    )
    assert earnings.status_code == 200
    # 500 gross less the 10% attestation commission clears to 450 available.
    assert Decimal(str(earnings.json()["available_balance"])) == Decimal("450.00")

    dispatched: list[str] = []

    class _FakePayoutTask:
        """Capture the dispatched payout id in place of the Celery task."""

        def delay(self, payout_id: str) -> None:
            dispatched.append(payout_id)

    monkeypatch.setattr(
        financials_service, "process_payout", _FakePayoutTask(), raising=False
    )
    payout = await client.post(
        f"/v1/orgs/{org_id}/financials/payouts",
        json={
            "amount": "100.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
            # Fresh code from the next step (TOTP is single-use now, M4).
            "totp_code": pyotp.TOTP(owner_secret).at(
                datetime.now(UTC) + timedelta(seconds=30)
            ),
        },
        headers=_auth(owner_id),
    )
    assert payout.status_code == 200

    async with async_session_factory() as session:
        payout_row = await session.scalar(select(Payout))
    assert payout_row is not None
    assert payout_row.org_id == org_id  # payout keyed to the org
    assert payout_row.contributor_id is None
    assert dispatched == [str(payout_row.id)]

    # --- Public identity: the directory lists the organization -----------
    directory = await client.get("/v1/attestor-orgs")
    assert directory.status_code == 200
    listing = {entry["org_id"]: entry for entry in directory.json()["attestors"]}
    assert str(org_id) in listing
    assert listing[str(org_id)]["name"] == "Lifecycle Attestor Org"

    profile = await client.get(f"/v1/attestor-orgs/{org_id}")
    assert profile.status_code == 200
    assert profile.json()["org_id"] == str(org_id)
