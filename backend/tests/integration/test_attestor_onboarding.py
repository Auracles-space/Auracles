"""Integration tests for the gated Attestor onboarding flow (Module 1)."""

from __future__ import annotations

from uuid import UUID

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.attestation.models import AttestorApplication
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
