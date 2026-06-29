"""Integration tests for the gated Attestor onboarding flow (Module 1)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.attestation.models import (
    AttestorApplication,
    AttestorTrial,
    Credential,
)
from app.modules.auth.models import User

# Reuse shared fixtures/helpers from the existing application test module
# rather than duplicating them. The fixture imports are referenced by name
# (pytest fixture injection + `usefixtures`), which static analysis cannot
# see, hence the targeted noqa.
from tests.integration.test_attestor_applications import (  # noqa: F401
    attestor_application_context,
    auth_headers,
    create_admin_user,
    create_user,
    migrated_database,
)


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
