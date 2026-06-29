"""Integration tests for the gated Attestor onboarding flow (Module 1)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.integrations import s3
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationUploadSession,
    AttestorApplication,
    AttestorProfile,
    AttestorTrial,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PayoutAccount
from app.shared.models.audit_log import AuditLog

# Reuse shared fixtures/helpers from the existing application test module
# rather than duplicating them. The fixture imports are referenced by name
# (pytest fixture injection + `usefixtures`), which static analysis cannot
# see, hence the targeted noqa.
from tests.integration.test_attestor_applications import (  # noqa: F401
    FakeRedis,
    auth_headers,
    create_admin_user,
    create_user,
    migrated_database,
)


@pytest.fixture
async def attestor_application_context() -> FakeRedis:
    """Reset attestation/auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(AttestorApplication))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))

    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AttestationUploadSession))
                await session.execute(delete(Attestation))
                await session.execute(delete(AttestorProfile))
                await session.execute(delete(AttestorApplication))
                await session.execute(delete(AuditLog))
                await session.execute(delete(UserRole))
                await session.execute(delete(User))
        await engine.dispose()


def _admin_totp(secret: str) -> pyotp.TOTP:
    """Return a live TOTP generator for the seeded admin secret."""
    return pyotp.TOTP(secret)


async def _seed_submitted_application(
    verified_kyc: bool,
) -> tuple[UUID, dict[str, str], pyotp.TOTP]:
    """Create a submitted application plus a TOTP-enabled admin reviewer."""
    applicant_id = await create_user(
        (
            "attestor-applicant-"
            f"{'verified' if verified_kyc else 'unverified'}@example.com"
        ),
        roles=["contributor"],
    )
    admin_id, admin_secret = await create_admin_user()
    async with async_session_factory() as session:
        async with session.begin():
            applicant = await session.scalar(
                select(User).where(User.id == applicant_id)
            )
            assert applicant is not None
            applicant.kyc_status = "verified" if verified_kyc else "unverified"
            application = AttestorApplication(
                user_id=applicant_id,
                status="submitted",
                specializations=[],
                legal_name="Jane Q Attestor",
                linkedin_url="https://linkedin.com/in/jane",
                professional_body_numbers={"cfa_institute": "12345"},
                sectors=["PE"],
                framework_categories=["Compliance"],
                jurisdictions=["US"],
                credentials_summary="Twenty years compliance.",
                sample_work={},
                professional_references="ref",
            )
            session.add(application)
            await session.flush()
            application_id = application.id

    return application_id, auth_headers(admin_id, ["admin"]), _admin_totp(admin_secret)


async def _seed_identity_verified_application_with_credential() -> tuple[
    UUID, UUID, dict[str, str], pyotp.TOTP
]:
    """Create an identity-verified application and one owned credential."""
    applicant_id = await create_user(
        "attestor-credential-applicant@example.com",
        roles=["contributor"],
    )
    admin_id, admin_secret = await create_admin_user()
    async with async_session_factory() as session:
        async with session.begin():
            application = AttestorApplication(
                user_id=applicant_id,
                status="identity_verified",
                specializations=[],
                legal_name="Jane Q Attestor",
                linkedin_url="https://linkedin.com/in/jane",
                professional_body_numbers={"cfa_institute": "12345"},
                sectors=["PE"],
                framework_categories=["Compliance"],
                jurisdictions=["US"],
                credentials_summary="Twenty years compliance.",
                sample_work={},
                professional_references="ref",
            )
            credential = Credential(
                user_id=applicant_id,
                title="Chartered Financial Analyst",
                issuer="CFA Institute",
                issued_date=date(2020, 1, 15),
                evidence_file_keys=["credentials/cfa.pdf"],
            )
            session.add(application)
            session.add(credential)
            await session.flush()
            application_id = application.id
            credential_id = credential.id

    return (
        application_id,
        credential_id,
        auth_headers(admin_id, ["admin"]),
        _admin_totp(admin_secret),
    )


async def _seed_professional_verified_application() -> tuple[
    UUID, dict[str, str], pyotp.TOTP
]:
    """Create a professional-verified application ready for trial assignment."""
    applicant_id = await create_user(
        "attestor-trial-applicant@example.com",
        roles=["contributor"],
    )
    admin_id, admin_secret = await create_admin_user()
    async with async_session_factory() as session:
        async with session.begin():
            application = AttestorApplication(
                user_id=applicant_id,
                status="professional_verified",
                specializations=[],
                legal_name="Jane Q Attestor",
                linkedin_url="https://linkedin.com/in/jane",
                professional_body_numbers={"cfa_institute": "12345"},
                sectors=["PE"],
                framework_categories=["Compliance"],
                jurisdictions=["US"],
                credentials_summary="Twenty years compliance.",
                sample_work={},
                professional_references="ref",
            )
            session.add(application)
            await session.flush()
            application_id = application.id

    return application_id, auth_headers(admin_id, ["admin"]), _admin_totp(admin_secret)


async def _seed_owner_application(
    status: str = "submitted",
) -> tuple[UUID, UUID, dict[str, str]]:
    """Create an application owned by an authenticated applicant."""
    applicant_id = await create_user(
        f"attestor-owner-{status}@example.com",
        roles=["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            application = AttestorApplication(
                user_id=applicant_id,
                status=status,
                specializations=[],
                legal_name="Jane Q Attestor",
                linkedin_url="https://linkedin.com/in/jane",
                professional_body_numbers={"cfa_institute": "12345"},
                sectors=["PE"],
                framework_categories=["Compliance"],
                jurisdictions=["US"],
                credentials_summary="Twenty years compliance.",
                sample_work={},
                professional_references="ref",
            )
            session.add(application)
            await session.flush()
            application_id = application.id

    return application_id, applicant_id, auth_headers(applicant_id, ["contributor"])


async def _seed_directory_attestor(
    *,
    email: str,
    profile_active: bool,
    sectors: list[str],
    framework_categories: list[str],
    jurisdictions: list[str],
    completed_statuses: list[str],
) -> UUID:
    """Create an Attestor profile plus public-safe and private credential rows."""
    user_id = await create_user(email, roles=["contributor"])
    requestor_id = await create_user(
        f"requestor-for-{email}",
        roles=["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.display_name = email.split("@")[0].replace("-", " ").title()

            session.add(
                AttestorProfile(
                    user_id=user_id,
                    specializations=sectors + framework_categories,
                    jurisdictions=jurisdictions,
                    active=profile_active,
                    verification_level=4,
                    sectors=sectors,
                    framework_categories=framework_categories,
                    coi_declarations=[
                        {
                            "entity": "Hidden Capital",
                            "entity_type": "firm",
                            "relationship": "advisory",
                            "within_24mo": True,
                        }
                    ],
                    coi_signed_at=datetime(2026, 6, 1),
                    coi_expires_at=datetime(2027, 6, 1),
                )
            )
            session.add(
                Credential(
                    user_id=user_id,
                    title="Chartered Financial Analyst",
                    issuer="CFA Institute",
                    issued_date=date(2021, 1, 15),
                    credential_type="CFA",
                    verification_status="verified",
                    reference_number="PRIVATE-REF-001",
                    verification_url="https://secret.example.com/verify",
                    evidence_file_keys=["credentials/private.pdf"],
                    registry_reference="registry-hidden-001",
                )
            )
            session.add(
                Credential(
                    user_id=user_id,
                    title="Pending Credential",
                    issuer="Pending Body",
                    issued_date=date(2024, 1, 15),
                    verification_status="pending",
                )
            )
            for index, status in enumerate(completed_statuses, start=1):
                session.add(
                    Attestation(
                        target_type="framework",
                        target_id=user_id,
                        requestor_id=requestor_id,
                        attestor_id=user_id,
                        status=status,
                        fee_amount=Decimal("100.00") + index,
                        requested_specializations=["Compliance"],
                        requested_jurisdictions=["US"],
                    )
                )

    return user_id


@pytest.mark.usefixtures("migrated_database")
async def test_submit_application_starts_submitted_with_taxonomy(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """A submitted application is in 'submitted' state with controlled tags."""
    user_id = await create_user("appl@example.com", roles=["contributor"])
    resp = await client.post(
        "/v1/attestor/applications",
        headers={
            "Authorization": (
                f"Bearer {create_access_token(user_id, roles=['contributor'])}"
            )
        },
        json={
            "legal_name": "Jane Q Attestor",
            "linkedin_url": "https://linkedin.com/in/jane",
            "professional_body_numbers": {"cfa_institute": "12345"},
            "sectors": ["PE"],
            "framework_categories": ["Compliance"],
            "jurisdictions": ["US"],
            "credentials_summary": "Twenty years compliance.",
            "sample_work": {},
            "professional_references": "ref",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "submitted"
    assert body["sectors"] == ["PE"]
    assert body["framework_categories"] == ["Compliance"]


@pytest.mark.usefixtures("migrated_database")
async def test_submit_rejects_unknown_sector(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Unknown taxonomy values are rejected with 422."""
    user_id = await create_user("appl2@example.com", roles=["contributor"])
    resp = await client.post(
        "/v1/attestor/applications",
        headers={
            "Authorization": (
                f"Bearer {create_access_token(user_id, roles=['contributor'])}"
            )
        },
        json={"legal_name": "X", "sectors": ["Crypto"],
              "framework_categories": ["Compliance"], "jurisdictions": ["US"],
              "credentials_summary": "x" * 12, "sample_work": {},
              "professional_references": "r"},
    )
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_database")
async def test_verify_kyc_advances_to_identity_verified(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Admin KYC verify moves a submitted application to identity_verified."""
    application_id, admin_headers, totp = await _seed_submitted_application(
        verified_kyc=True
    )

    resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/verify-kyc",
        headers=admin_headers,
        json={"name_match": True, "totp_code": totp.now()},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "identity_verified"


@pytest.mark.usefixtures("migrated_database")
async def test_verify_kyc_rejects_unverified_applicant(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Admin KYC verify rejects applicants whose platform KYC is not verified."""
    application_id, admin_headers, totp = await _seed_submitted_application(
        verified_kyc=False
    )

    resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/verify-kyc",
        headers=admin_headers,
        json={"name_match": True, "totp_code": totp.now()},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Applicant KYC is not verified."


@pytest.mark.usefixtures("migrated_database")
async def test_verify_credential_advances_to_professional_verified(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Admin credential cross-check advances identity_verified applications."""
    application_id, credential_id, admin_headers, totp = (
        await _seed_identity_verified_application_with_credential()
    )

    resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/verify-credential",
        headers=admin_headers,
        json={
            "credential_id": str(credential_id),
            "issuing_body": "cfa_institute",
            "good_standing": True,
            "registry_reference": "registry-check-001",
            "totp_code": totp.now(),
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "professional_verified"

    async with async_session_factory() as session:
        credential = await session.get(Credential, credential_id)
        admin = await session.scalar(
            select(User).where(User.email == "attestor-review-admin@auracles.space")
        )

    assert credential is not None
    assert admin is not None
    assert credential.good_standing is True
    assert credential.registry_checked_by == admin.id


@pytest.mark.usefixtures("migrated_database")
async def test_verify_credential_rejects_bad_standing_and_rolls_back(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """A rejected registry check must not persist credential mutations."""
    application_id, credential_id, admin_headers, totp = (
        await _seed_identity_verified_application_with_credential()
    )

    resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/verify-credential",
        headers=admin_headers,
        json={
            "credential_id": str(credential_id),
            "issuing_body": "cfa_institute",
            "good_standing": False,
            "registry_reference": "registry-check-002",
            "totp_code": totp.now(),
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Credential not in good standing."

    async with async_session_factory() as session:
        application = await session.get(AttestorApplication, application_id)
        credential = await session.get(Credential, credential_id)

    assert application is not None
    assert credential is not None
    assert application.status == "identity_verified"
    assert credential.good_standing is None
    assert credential.registry_checked_by is None
    assert credential.registry_reference is None


@pytest.mark.usefixtures("migrated_database")
async def test_assign_trial_creates_first_assigned_attempt(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Assigning a calibration trial creates attempt 1 in assigned state."""
    application_id, admin_headers, totp = (
        await _seed_professional_verified_application()
    )

    resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial",
        headers=admin_headers,
        json={"seeded_framework_id": None, "totp_code": totp.now()},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["application_id"] == str(application_id)
    assert body["seeded_framework_id"] is None
    assert body["status"] == "assigned"
    assert body["attempt"] == 1

    async with async_session_factory() as session:
        trial = await session.get(AttestorTrial, UUID(body["id"]))

    assert trial is not None
    assert trial.status == "assigned"
    assert trial.attempt == 1


@pytest.mark.usefixtures("migrated_database")
async def test_decide_trial_pass_promotes_application_to_expert_verified(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Passing a trial promotes the application to expert_verified."""
    application_id, admin_headers, totp = (
        await _seed_professional_verified_application()
    )

    assign_resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial",
        headers=admin_headers,
        json={"seeded_framework_id": None, "totp_code": totp.now()},
    )
    assert assign_resp.status_code == 200, assign_resp.text
    trial_id = UUID(assign_resp.json()["id"])

    decide_resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial/{trial_id}/decide",
        headers=admin_headers,
        json={"passed": True, "feedback": "Strong judgment.", "totp_code": totp.now()},
    )

    assert decide_resp.status_code == 200, decide_resp.text
    assert decide_resp.json()["status"] == "expert_verified"

    async with async_session_factory() as session:
        application = await session.get(AttestorApplication, application_id)
        trial = await session.get(AttestorTrial, trial_id)

    assert application is not None
    assert trial is not None
    assert application.status == "expert_verified"
    assert trial.status == "passed"


@pytest.mark.usefixtures("migrated_database")
async def test_decide_trial_fail_twice_holds_application_and_blocks_third_assign(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Two failed trials hold the application and exhaust assignment attempts."""
    application_id, admin_headers, totp = (
        await _seed_professional_verified_application()
    )

    first_assign = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial",
        headers=admin_headers,
        json={"seeded_framework_id": None, "totp_code": totp.now()},
    )
    assert first_assign.status_code == 200, first_assign.text
    first_trial_id = UUID(first_assign.json()["id"])

    first_decide = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial/{first_trial_id}/decide",
        headers=admin_headers,
        json={"passed": False, "feedback": "Needs work.", "totp_code": totp.now()},
    )
    assert first_decide.status_code == 200, first_decide.text
    assert first_decide.json()["status"] == "professional_verified"

    second_assign = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial",
        headers=admin_headers,
        json={"seeded_framework_id": None, "totp_code": totp.now()},
    )
    assert second_assign.status_code == 200, second_assign.text
    assert second_assign.json()["attempt"] == 2
    second_trial_id = UUID(second_assign.json()["id"])

    second_decide = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial/{second_trial_id}/decide",
        headers=admin_headers,
        json={"passed": False, "feedback": "Still not ready.", "totp_code": totp.now()},
    )
    assert second_decide.status_code == 200, second_decide.text
    assert second_decide.json()["status"] == "held"

    third_assign = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial",
        headers=admin_headers,
        json={"seeded_framework_id": None, "totp_code": totp.now()},
    )
    assert third_assign.status_code == 409
    assert (
        third_assign.json()["detail"]
        == "Trial attempts exhausted; application held."
    )

    async with async_session_factory() as session:
        application = await session.get(AttestorApplication, application_id)
        first_trial = await session.get(AttestorTrial, first_trial_id)
        second_trial = await session.get(AttestorTrial, second_trial_id)

    assert application is not None
    assert first_trial is not None
    assert second_trial is not None
    assert application.status == "held"
    assert first_trial.status == "failed"
    assert second_trial.status == "failed"


@pytest.mark.usefixtures("migrated_database")
async def test_sign_coi_sets_timestamps_and_declarations(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Signing CoI stores declarations and sets a one-year expiry window."""
    application_id, applicant_id, owner_headers = await _seed_owner_application()

    resp = await client.post(
        f"/v1/attestor/applications/{application_id}/coi",
        headers=owner_headers,
        json={
            "declarations": [
                {
                    "entity": "Northwind Capital",
                    "entity_type": "fund",
                    "relationship": "financial",
                    "within_24mo": True,
                },
                {
                    "entity": "Jane Advisor LLC",
                    "entity_type": "firm",
                    "relationship": "advisory",
                    "within_24mo": False,
                },
            ],
            "accept_policy": True,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    signed_at = datetime.fromisoformat(body["coi_signed_at"])
    expires_at = datetime.fromisoformat(body["coi_expires_at"])
    assert len(body["coi_declarations"]) == 2
    assert abs((expires_at - signed_at) - timedelta(days=365)) < timedelta(seconds=1)

    async with async_session_factory() as session:
        application = await session.scalar(
            select(AttestorApplication).where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == applicant_id,
            )
        )

    assert application is not None
    assert application.coi_signed_at is not None
    assert application.coi_expires_at is not None
    assert len(application.coi_declarations) == 2
    assert (
        abs(
            (application.coi_expires_at - application.coi_signed_at)
            - timedelta(days=365)
        )
        < timedelta(seconds=1)
    )


@pytest.mark.usefixtures("migrated_database")
async def test_sign_coi_requires_policy_acceptance(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Reject signing when the applicant does not accept the CoI policy."""
    application_id, applicant_id, owner_headers = await _seed_owner_application()

    resp = await client.post(
        f"/v1/attestor/applications/{application_id}/coi",
        headers=owner_headers,
        json={
            "declarations": [
                {
                    "entity": "Northwind Capital",
                    "entity_type": "fund",
                    "relationship": "financial",
                    "within_24mo": True,
                }
            ],
            "accept_policy": False,
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "CoI policy must be accepted."

    async with async_session_factory() as session:
        application = await session.scalar(
            select(AttestorApplication).where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == applicant_id,
            )
        )

    assert application is not None
    assert application.coi_signed_at is None
    assert application.coi_expires_at is None
    assert application.coi_declarations == []


@pytest.mark.usefixtures("migrated_database")
async def test_attach_payout_sets_owned_payout_account_on_application(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Applicants can attach one of their own payout accounts to the application."""
    application_id, applicant_id, owner_headers = await _seed_owner_application()
    async with async_session_factory() as session:
        async with session.begin():
            payout_account = PayoutAccount(
                user_id=applicant_id,
                provider="stripe",
                provider_account_id="acct_attestor_owner_001",
                provider_account_lookup_hash="hash-attestor-owner-001",
                account_type="express",
                is_default=True,
            )
            session.add(payout_account)
            await session.flush()
            payout_account_id = payout_account.id

    resp = await client.post(
        f"/v1/attestor/applications/{application_id}/payout",
        headers=owner_headers,
        json={"payout_account_id": str(payout_account_id)},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["payout_account_id"] == str(payout_account_id)

    async with async_session_factory() as session:
        application = await session.scalar(
            select(AttestorApplication).where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == applicant_id,
            )
        )

    assert application is not None
    assert application.payout_account_id == payout_account_id


@pytest.mark.usefixtures("migrated_database")
async def test_attach_payout_rejects_accounts_owned_by_someone_else(
    client: AsyncClient, attestor_application_context,  # noqa: F811
) -> None:
    """Applicants cannot attach payout accounts they do not own."""
    application_id, applicant_id, owner_headers = await _seed_owner_application()
    outsider_id = await create_user(
        "attestor-payout-outsider@example.com",
        roles=["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            payout_account = PayoutAccount(
                user_id=outsider_id,
                provider="stripe",
                provider_account_id="acct_attestor_outsider_001",
                provider_account_lookup_hash="hash-attestor-outsider-001",
                account_type="express",
                is_default=False,
            )
            session.add(payout_account)
            await session.flush()
            payout_account_id = payout_account.id

    resp = await client.post(
        f"/v1/attestor/applications/{application_id}/payout",
        headers=owner_headers,
        json={"payout_account_id": str(payout_account_id)},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Payout account not found."

    async with async_session_factory() as session:
        application = await session.scalar(
            select(AttestorApplication).where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == applicant_id,
            )
        )

    assert application is not None
    assert application.payout_account_id is None


@pytest.mark.usefixtures("migrated_database")
async def test_set_tax_document_creates_upload_session_and_persists_key(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tax document upload creates a presigned session linked to the application."""
    application_id, applicant_id, owner_headers = await _seed_owner_application()
    presigned_calls: list[tuple[str, str, str, int, int]] = []

    def fake_presigned_post(
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, object]:
        """Return deterministic presigned POST data without calling AWS."""
        presigned_calls.append((bucket, key, mime_type, max_size, expires_in))
        return {
            "url": f"https://s3.local/{bucket}",
            "fields": {
                "key": key,
                "Content-Type": mime_type,
                "max_size": str(max_size),
                "expires_in": str(expires_in),
            },
        }

    monkeypatch.setattr(s3.storage, "presigned_post", fake_presigned_post)

    resp = await client.post(
        f"/v1/attestor/applications/{application_id}/tax-document",
        headers=owner_headers,
        json={
            "tax_document_type": "w9",
            "file_name": "Form W-9.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["url"] == "https://s3.local/auracles-artifacts-dev"
    assert body["fields"]
    assert body["s3_key"].startswith(
        f"attestor-tax-documents/{application_id}/{applicant_id}/"
    )

    async with async_session_factory() as session:
        application = await session.scalar(
            select(AttestorApplication).where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == applicant_id,
            )
        )
        upload_session = await session.scalar(
            select(AttestationUploadSession).where(
                AttestationUploadSession.s3_key == body["s3_key"]
            )
        )

    assert application is not None
    assert upload_session is not None
    assert application.tax_document_type == "w9"
    assert application.tax_document_key == body["s3_key"]
    assert upload_session.application_id == application_id
    assert upload_session.user_id == applicant_id
    assert upload_session.purpose == "attestor_tax_document"
    assert presigned_calls == [
        (
            "auracles-artifacts-dev",
            body["s3_key"],
            "application/pdf",
            10 * 1024 * 1024,
            300,
        )
    ]


@pytest.mark.usefixtures("migrated_database")
async def test_activate_attestor_promotes_expert_verified_application_to_active(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activation creates the live profile and approves the Attestor role."""
    applicant_id = await create_user(
        "attestor-activation-owner@example.com",
        roles=["contributor"],
    )
    admin_id, admin_secret = await create_admin_user()
    owner_headers = auth_headers(applicant_id, ["contributor"])
    admin_headers = auth_headers(admin_id, ["admin"])
    totp = _admin_totp(admin_secret)

    submit_resp = await client.post(
        "/v1/attestor/applications",
        headers=owner_headers,
        json={
            "legal_name": "Jane Q Attestor",
            "linkedin_url": "https://linkedin.com/in/jane",
            "professional_body_numbers": {"cfa_institute": "12345"},
            "sectors": ["PE"],
            "framework_categories": ["Compliance"],
            "jurisdictions": ["US"],
            "credentials_summary": "Twenty years compliance.",
            "sample_work": {},
            "professional_references": "ref",
        },
    )
    assert submit_resp.status_code == 201, submit_resp.text
    application_id = UUID(submit_resp.json()["id"])

    async with async_session_factory() as session:
        async with session.begin():
            applicant = await session.get(User, applicant_id)
            assert applicant is not None
            applicant.kyc_status = "verified"
            credential = Credential(
                user_id=applicant_id,
                title="Chartered Financial Analyst",
                issuer="CFA Institute",
                issued_date=date(2020, 1, 15),
                evidence_file_keys=["credentials/cfa.pdf"],
            )
            payout_account = PayoutAccount(
                user_id=applicant_id,
                provider="stripe",
                provider_account_id="acct_attestor_activation_001",
                provider_account_lookup_hash="hash-attestor-activation-001",
                account_type="express",
                is_default=True,
            )
            session.add(credential)
            session.add(payout_account)
            await session.flush()
            credential_id = credential.id
            payout_account_id = payout_account.id

    kyc_resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/verify-kyc",
        headers=admin_headers,
        json={"name_match": True, "totp_code": totp.now()},
    )
    assert kyc_resp.status_code == 200, kyc_resp.text

    credential_resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/verify-credential",
        headers=admin_headers,
        json={
            "credential_id": str(credential_id),
            "issuing_body": "cfa_institute",
            "good_standing": True,
            "registry_reference": "registry-check-activation",
            "totp_code": totp.now(),
        },
    )
    assert credential_resp.status_code == 200, credential_resp.text

    assign_resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial",
        headers=admin_headers,
        json={"seeded_framework_id": None, "totp_code": totp.now()},
    )
    assert assign_resp.status_code == 200, assign_resp.text
    trial_id = UUID(assign_resp.json()["id"])

    decide_resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/trial/{trial_id}/decide",
        headers=admin_headers,
        json={"passed": True, "feedback": "Ready.", "totp_code": totp.now()},
    )
    assert decide_resp.status_code == 200, decide_resp.text

    coi_resp = await client.post(
        f"/v1/attestor/applications/{application_id}/coi",
        headers=owner_headers,
        json={
            "declarations": [
                {
                    "entity": "Northwind Capital",
                    "entity_type": "fund",
                    "relationship": "financial",
                    "within_24mo": True,
                }
            ],
            "accept_policy": True,
        },
    )
    assert coi_resp.status_code == 200, coi_resp.text

    payout_resp = await client.post(
        f"/v1/attestor/applications/{application_id}/payout",
        headers=owner_headers,
        json={"payout_account_id": str(payout_account_id)},
    )
    assert payout_resp.status_code == 200, payout_resp.text

    def fake_presigned_post(
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, object]:
        """Return deterministic presigned POST data without calling AWS."""
        del max_size, expires_in
        return {
            "url": f"https://s3.local/{bucket}",
            "fields": {
                "key": key,
                "Content-Type": mime_type,
            },
        }

    monkeypatch.setattr(s3.storage, "presigned_post", fake_presigned_post)
    tax_resp = await client.post(
        f"/v1/attestor/applications/{application_id}/tax-document",
        headers=owner_headers,
        json={
            "tax_document_type": "w9",
            "file_name": "Form W-9.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
        },
    )
    assert tax_resp.status_code == 201, tax_resp.text

    activate_resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/activate",
        headers=admin_headers,
        json={"totp_code": totp.now()},
    )

    assert activate_resp.status_code == 200, activate_resp.text
    assert activate_resp.json()["status"] == "active"

    async with async_session_factory() as session:
        application = await session.get(AttestorApplication, application_id)
        profile = await session.scalar(
            select(AttestorProfile).where(AttestorProfile.user_id == applicant_id)
        )
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == applicant_id,
                UserRole.role == "attestor",
            )
        )

    assert application is not None
    assert profile is not None
    assert role is not None
    assert application.status == "active"
    assert profile.active is True
    assert profile.verification_level == 4
    assert profile.sectors == ["PE"]
    assert role.approved_at is not None


@pytest.mark.usefixtures("migrated_database")
async def test_activate_attestor_rejects_missing_tax_document(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
) -> None:
    """Activation must fail until the applicant has set a tax document."""
    application_id, applicant_id, owner_headers = await _seed_owner_application(
        status="expert_verified",
    )
    admin_id, admin_secret = await create_admin_user()
    admin_headers = auth_headers(admin_id, ["admin"])
    totp = _admin_totp(admin_secret)

    async with async_session_factory() as session:
        async with session.begin():
            payout_account = PayoutAccount(
                user_id=applicant_id,
                provider="stripe",
                provider_account_id="acct_attestor_missing_tax_001",
                provider_account_lookup_hash="hash-attestor-missing-tax-001",
                account_type="express",
                is_default=True,
            )
            session.add(payout_account)
            await session.flush()
            payout_account_id = payout_account.id

    coi_resp = await client.post(
        f"/v1/attestor/applications/{application_id}/coi",
        headers=owner_headers,
        json={
            "declarations": [
                {
                    "entity": "Northwind Capital",
                    "entity_type": "fund",
                    "relationship": "financial",
                    "within_24mo": True,
                }
            ],
            "accept_policy": True,
        },
    )
    assert coi_resp.status_code == 200, coi_resp.text

    payout_resp = await client.post(
        f"/v1/attestor/applications/{application_id}/payout",
        headers=owner_headers,
        json={"payout_account_id": str(payout_account_id)},
    )
    assert payout_resp.status_code == 200, payout_resp.text

    activate_resp = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/activate",
        headers=admin_headers,
        json={"totp_code": totp.now()},
    )

    assert activate_resp.status_code == 422
    assert "tax_document" in activate_resp.json()["detail"]

    async with async_session_factory() as session:
        application = await session.get(AttestorApplication, application_id)
        profile = await session.scalar(
            select(AttestorProfile).where(AttestorProfile.user_id == applicant_id)
        )

    assert application is not None
    assert profile is None
    assert application.status == "expert_verified"


@pytest.mark.usefixtures("migrated_database")
async def test_admin_rejects_expert_verified_attestor_application(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
) -> None:
    """Admins can reject a non-active application after onboarding gates."""
    application_id, applicant_id, _owner_headers = await _seed_owner_application(
        status="expert_verified",
    )
    admin_id, admin_secret = await create_admin_user()

    response = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/reject",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "feedback": "Manual review found unresolved trust concerns.",
            "totp_code": _admin_totp(admin_secret).now(),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"
    assert (
        response.json()["admin_feedback"]
        == "Manual review found unresolved trust concerns."
    )
    assert response.json()["reviewed_by"] == str(admin_id)

    async with async_session_factory() as session:
        application = await session.get(AttestorApplication, application_id)
        profile = await session.scalar(
            select(AttestorProfile).where(AttestorProfile.user_id == applicant_id)
        )

    assert application is not None
    assert profile is None
    assert application.status == "rejected"


@pytest.mark.usefixtures("migrated_database")
async def test_list_public_attestor_directory_shows_only_active_safe_entries(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
) -> None:
    """The public directory lists active Attestors only and strips sensitive data."""
    visible_attestor_id = await _seed_directory_attestor(
        email="active-directory-attestor@example.com",
        profile_active=True,
        sectors=["PE"],
        framework_categories=["Compliance"],
        jurisdictions=["US"],
        completed_statuses=["released", "resolved", "closed"],
    )
    hidden_attestor_id = await _seed_directory_attestor(
        email="inactive-directory-attestor@example.com",
        profile_active=False,
        sectors=["VC"],
        framework_categories=["ESG"],
        jurisdictions=["UK"],
        completed_statuses=["released"],
    )

    response = await client.get("/v1/attestors")

    assert response.status_code == 200, response.text
    body = response.json()
    attestors = body["attestors"]
    assert [entry["user_id"] for entry in attestors] == [str(visible_attestor_id)]
    assert str(hidden_attestor_id) not in response.text

    entry = attestors[0]
    assert entry["display_name"] == "Active Directory Attestor"
    assert entry["sectors"] == ["PE"]
    assert entry["framework_categories"] == ["Compliance"]
    assert entry["jurisdictions"] == ["US"]
    assert entry["verification_level"] == 4
    assert entry["completed_attestations"] == 3
    assert entry["reputation"] is None
    assert [credential["title"] for credential in entry["credentials"]] == [
        "Chartered Financial Analyst"
    ]

    serialized = response.text
    assert "Pending Credential" not in serialized
    assert "PRIVATE-REF-001" not in serialized
    assert "https://secret.example.com/verify" not in serialized
    assert "credentials/private.pdf" not in serialized
    assert "registry-hidden-001" not in serialized
    assert "coi" not in serialized.lower()
    assert "tax" not in serialized.lower()
    assert "payout" not in serialized.lower()


@pytest.mark.usefixtures("migrated_database")
async def test_list_public_attestor_directory_filters_by_sector(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
) -> None:
    """The public directory applies sector filters against active profiles."""
    pe_attestor_id = await _seed_directory_attestor(
        email="pe-directory-attestor@example.com",
        profile_active=True,
        sectors=["PE"],
        framework_categories=["Compliance"],
        jurisdictions=["US"],
        completed_statuses=["released"],
    )
    await _seed_directory_attestor(
        email="vc-directory-attestor@example.com",
        profile_active=True,
        sectors=["VC"],
        framework_categories=["ESG"],
        jurisdictions=["UK"],
        completed_statuses=["closed"],
    )

    response = await client.get("/v1/attestors", params={"sector": "PE"})

    assert response.status_code == 200, response.text
    assert [entry["user_id"] for entry in response.json()["attestors"]] == [
        str(pe_attestor_id)
    ]


@pytest.mark.usefixtures("migrated_database")
async def test_get_public_attestor_directory_profile_returns_active_attestor(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
) -> None:
    """The public directory detail endpoint returns one active Attestor profile."""
    attestor_id = await _seed_directory_attestor(
        email="detail-directory-attestor@example.com",
        profile_active=True,
        sectors=["PE"],
        framework_categories=["Compliance"],
        jurisdictions=["US"],
        completed_statuses=["released", "closed"],
    )

    response = await client.get(f"/v1/attestors/{attestor_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(attestor_id)
    assert body["display_name"] == "Detail Directory Attestor"
    assert body["sectors"] == ["PE"]
    assert body["completed_attestations"] == 2
    assert [credential["title"] for credential in body["credentials"]] == [
        "Chartered Financial Analyst"
    ]


# Each admin onboarding gate verifies TOTP *before* loading or mutating the
# application, so an invalid code must fail regardless of the gate's required
# source state — seed one submitted application and assert it never changes.
_ADMIN_GATES = [
    ("/verify-kyc", {"name_match": True}),
    (
        "/verify-credential",
        {
            "credential_id": str(uuid4()),
            "issuing_body": "cfa_institute",
            "good_standing": True,
            "registry_reference": "REF-1",
        },
    ),
    ("/trial", {}),
    (f"/trial/{uuid4()}/decide", {"passed": True}),
    ("/activate", {}),
]


@pytest.mark.usefixtures("migrated_database")
@pytest.mark.parametrize(("path_suffix", "body"), _ADMIN_GATES)
async def test_admin_onboarding_gate_rejects_invalid_totp(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
    path_suffix: str,
    body: dict[str, object],
) -> None:
    """An invalid admin TOTP code is rejected before any state change at each gate."""
    application_id, _applicant_id, _headers = await _seed_owner_application(
        status="submitted",
    )
    admin_id, _secret = await create_admin_user()

    response = await client.post(
        f"/v1/admin/attestor/applications/{application_id}{path_suffix}",
        headers=auth_headers(admin_id, ["admin"]),
        json={**body, "totp_code": "000000"},
    )

    assert response.status_code == 422, response.text
    async with async_session_factory() as session:
        application = await session.get(AttestorApplication, application_id)
    assert application is not None
    assert application.status == "submitted"


@pytest.mark.usefixtures("migrated_database")
async def test_admin_onboarding_gate_requires_admin_role(
    client: AsyncClient,
    attestor_application_context,  # noqa: F811
) -> None:
    """A non-admin caller cannot reach an admin onboarding gate (RBAC denies first)."""
    application_id, _applicant_id, applicant_headers = await _seed_owner_application(
        status="submitted",
    )

    response = await client.post(
        f"/v1/admin/attestor/applications/{application_id}/verify-kyc",
        headers=applicant_headers,
        json={"name_match": True, "totp_code": "000000"},
    )

    assert response.status_code == 403, response.text
    async with async_session_factory() as session:
        application = await session.get(AttestorApplication, application_id)
    assert application is not None
    assert application.status == "submitted"


@pytest.mark.usefixtures("migrated_database")
async def test_second_submitted_application_blocked_by_unique_index(
    attestor_application_context,  # noqa: F811
) -> None:
    """The DB partial unique index blocks a second submitted application per user.

    Guards against the submit_application TOCTOU race: two concurrent submits can
    both pass the non-locking pre-check, so the database is the real backstop.
    """
    user_id = await create_user("dup-submit@example.com", roles=["contributor"])

    def _application() -> AttestorApplication:
        return AttestorApplication(
            user_id=user_id,
            status="submitted",
            specializations=[],
            sectors=["PE"],
            framework_categories=["Compliance"],
            jurisdictions=["US"],
            credentials_summary="x",
            sample_work={},
            professional_references="x",
        )

    async with async_session_factory() as session:
        async with session.begin():
            session.add(_application())

    with pytest.raises(IntegrityError):
        async with async_session_factory() as session:
            async with session.begin():
                session.add(_application())
