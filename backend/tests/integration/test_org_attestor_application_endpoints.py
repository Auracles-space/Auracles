"""Integration tests for org attestor application endpoints.

Covers the seven /v1/orgs/{org_id}/attestor-application routes: create, read,
edit, submit (rate-limited), owner-signed undertakings (step-up), tax-document
upload session, and trial-member nomination — with RBAC (401/403), suspended
org, and NDA gating.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.attestation.models import AttestorTrial
from app.modules.auth.models import User
from app.modules.financials.models import PayoutAccount
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgCapability,
    OrgLegalProfile,
    OrgMember,
    OrgMemberNda,
)
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.integration.test_auth_sessions import FakeRedis

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _stub_trial_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent trial-nomination endpoints from enqueuing to the real broker.

    `nominate_trial_member` fires `dispatch_project_notification.delay`; without
    this stub the shared dev worker would consume a task for a user that only
    exists in the test database and log a spurious failure.
    """
    from app.modules.organizations import attestor_application_service as _svc

    class _NoDispatch:
        def delay(self, **kwargs: object) -> None:
            return None

    monkeypatch.setattr(_svc, "dispatch_project_notification", _NoDispatch())


_APPLICATION_PATH = "/v1/orgs/{org_id}/attestor-application"


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
            await session.execute(delete(AttestorTrial))
            await session.execute(delete(OrgAttestorApplication))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Organization))
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


def auth(user_id: UUID) -> dict[str, str]:
    """Build an Authorization header for the given user."""
    return {"Authorization": f"Bearer {create_access_token(user_id, [])}"}


async def _create_user(prefix: str, *, totp_secret: str | None = None) -> UUID:
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


async def _create_org(
    owner_id: UUID,
    *,
    attestor_status: str | None = "pending",
    suspended: bool = False,
    kyb_verified: bool = True,
    country: str = "US",
) -> UUID:
    """Insert org + owner member (+ attestor capability); return org id.

    Business-verified by default: an organization cannot open an attestor
    application until it is, so every other case in this file starts from a
    verified org.
    """
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"orgatt-{uuid4().hex[:6]}",
                name="Org Attestor Endpoint",
                country=country,
                created_by=owner_id,
                suspended_at=datetime.now(UTC) if suspended else None,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            if attestor_status is not None:
                session.add(
                    OrgCapability(
                        org_id=org.id,
                        capability="attestor",
                        status=attestor_status,
                    )
                )
            if kyb_verified:
                session.add(
                    OrgLegalProfile(
                        org_id=org.id,
                        legal_name="Org Attestor Endpoint Ltd",
                        registration_number="RC123456",
                        incorporation_doc_keys=["org-incorporation-docs/c.pdf"],
                        kyb_status="verified",
                        kyb_verified_at=datetime.now(UTC),
                    )
                )
            return org.id


async def _add_member(org_id: UUID, user_id: UUID, role: str) -> UUID:
    """Add a member with the given role; return the org_member id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return member.id


def _create_body() -> dict[str, object]:
    """Return a complete create-request body."""
    return {
        "sectors": ["private_equity"],
        "functions": ["compliance"],
        "jurisdictions": ["united_states"],
        "credentials_summary": "Two decades of PE compliance attestation work.",
        "sample_work": {"portfolio": "https://example.com/samples"},
        "professional_references": "Jane Roe, MD of Example Capital.",
    }


async def test_unverified_org_cannot_open_an_attestor_application(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Attestor onboarding is behind business verification like everything else.

    Verification precedes every capability, so an unverified organization must
    not be able to start the attestor gate walk either — otherwise the flow has
    to carry a KYB step of its own, which is what it used to do.
    """
    owner_id = await _create_user("unverified-owner")
    org_id = await _create_org(owner_id, kyb_verified=False)

    response = await client.post(
        _APPLICATION_PATH.format(org_id=org_id),
        json=_create_body(),
        headers=auth(owner_id),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "org_kyb_required"


async def test_create_get_and_edit_flow(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Owner creates, reads (with checklist), and edits the application."""
    owner_id = await _create_user("owner")
    org_id = await _create_org(owner_id)
    path = _APPLICATION_PATH.format(org_id=org_id)

    created = await client.post(path, json=_create_body(), headers=auth(owner_id))
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "draft"
    assert body["gate_checklist"]["undertakings_signed"] is False

    fetched = await client.get(path, headers=auth(owner_id))
    assert fetched.status_code == 200
    assert fetched.json()["credentials_summary"].startswith("Two decades")
    # The application no longer carries a legal identity of its own: KYB is
    # established on the organization before it can apply at all.
    assert "legal_name" not in fetched.json()

    edited = await client.patch(
        path,
        json={"credentials_summary": "Three decades of PE compliance work."},
        headers=auth(owner_id),
    )
    assert edited.status_code == 200
    assert edited.json()["credentials_summary"].startswith("Three decades")


async def test_create_accepts_canonical_functions(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Attestor application create accepts canonical functions and slugs."""
    owner_id = await _create_user("canonical-owner")
    org_id = await _create_org(owner_id)
    payload = {
        "sectors": ["private_equity"],
        "functions": ["compliance", "investment_management"],
        "jurisdictions": ["united_states", "nigeria"],
        "credentials_summary": (
            "Attests private-equity compliance and operating models."
        ),
        "sample_work": {"portfolio": "https://example.com/canonical"},
        "professional_references": "John Roe, Operating Partner.",
    }

    response = await client.post(
        _APPLICATION_PATH.format(org_id=org_id),
        json=payload,
        headers=auth(owner_id),
    )

    assert response.status_code == 201
    assert response.json()["functions"] == ["compliance", "investment_management"]


async def test_create_rejects_off_vocabulary_functions(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Legacy function labels are rejected once canonical taxonomy is enforced."""
    owner_id = await _create_user("off-vocabulary-owner")
    org_id = await _create_org(owner_id)
    payload = {**_create_body(), "functions": ["Compliance"]}

    response = await client.post(
        _APPLICATION_PATH.format(org_id=org_id),
        json=payload,
        headers=auth(owner_id),
    )

    assert response.status_code == 422


async def test_create_requires_authentication(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Unauthenticated create returns 401."""
    owner_id = await _create_user("owner")
    org_id = await _create_org(owner_id)
    res = await client.post(
        _APPLICATION_PATH.format(org_id=org_id), json=_create_body()
    )
    assert res.status_code == 401


async def test_create_rejects_non_member_and_plain_member(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """A non-member and a plain member are both denied create (admin-gated)."""
    owner_id = await _create_user("owner")
    outsider_id = await _create_user("outsider")
    member_id = await _create_user("member")
    org_id = await _create_org(owner_id)
    await _add_member(org_id, member_id, "member")
    path = _APPLICATION_PATH.format(org_id=org_id)

    outsider = await client.post(path, json=_create_body(), headers=auth(outsider_id))
    assert outsider.status_code == 403
    member = await client.post(path, json=_create_body(), headers=auth(member_id))
    assert member.status_code == 403


async def test_create_rejected_on_suspended_org(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """A suspended organization blocks the application with 403."""
    owner_id = await _create_user("owner")
    org_id = await _create_org(owner_id, suspended=True)
    res = await client.post(
        _APPLICATION_PATH.format(org_id=org_id),
        json=_create_body(),
        headers=auth(owner_id),
    )
    assert res.status_code == 403


async def test_submit_rate_limited(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Submitting past the per-org daily window returns 429."""
    owner_id = await _create_user("owner")
    org_id = await _create_org(owner_id)
    path = _APPLICATION_PATH.format(org_id=org_id)
    await client.post(path, json=_create_body(), headers=auth(owner_id))

    clean_state.counters[f"rate_limit:org_attestor_apply:{org_id}"] = 3
    limited = await client.post(f"{path}/submit", headers=auth(owner_id))
    assert limited.status_code == 429


async def test_sign_undertakings_owner_only_and_step_up(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Admins cannot sign; the owner signs only inside an open step-up window."""
    secret = pyotp.random_base32()
    owner_id = await _create_user("owner", totp_secret=secret)
    admin_id = await _create_user("admin")
    org_id = await _create_org(owner_id)
    await _add_member(org_id, admin_id, "admin")
    path = _APPLICATION_PATH.format(org_id=org_id)
    await client.post(path, json=_create_body(), headers=auth(owner_id))

    body = {
        "declarations": [],
        "accept_policy": True,
        "accept_confidentiality": True,
    }
    denied = await client.post(
        f"{path}/sign-undertakings", json=body, headers=auth(admin_id)
    )
    assert denied.status_code == 403

    no_window = await client.post(
        f"{path}/sign-undertakings", json=body, headers=auth(owner_id)
    )
    assert no_window.status_code == 403
    assert no_window.json()["detail"]["error_code"] == "step_up_required"

    await open_step_up_window(clean_state, owner_id)
    signed = await client.post(
        f"{path}/sign-undertakings", json=body, headers=auth(owner_id)
    )
    assert signed.status_code == 200
    assert signed.json()["gate_checklist"]["undertakings_signed"] is True


async def test_tax_document_upload_session(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """The tax-document endpoint returns a presigned upload session."""
    owner_id = await _create_user("owner")
    org_id = await _create_org(owner_id)
    path = _APPLICATION_PATH.format(org_id=org_id)
    await client.post(path, json=_create_body(), headers=auth(owner_id))

    res = await client.post(
        f"{path}/tax-document",
        json={
            "tax_document_type": "w9",
            "file_name": "w9.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
        },
        headers=auth(owner_id),
    )
    assert res.status_code == 200
    assert res.json()["s3_key"].startswith("org-attestor-tax-documents/")


def _tax_body(tax_document_type: str) -> dict[str, object]:
    """Build a tax-document upload request for the given document type."""
    return {
        "tax_document_type": tax_document_type,
        "file_name": "tax.pdf",
        "content_type": "application/pdf",
        "size_bytes": 2048,
    }


@pytest.mark.parametrize("tax_document_type", ["firs_tin", "tcc", "other"])
async def test_nigerian_org_uploads_nigerian_tax_documents(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    tax_document_type: str,
) -> None:
    """A Nigerian org may upload a FIRS TIN certificate, a TCC, or other."""
    owner_id = await _create_user("owner")
    org_id = await _create_org(owner_id, country="NG")
    path = _APPLICATION_PATH.format(org_id=org_id)
    await client.post(path, json=_create_body(), headers=auth(owner_id))

    res = await client.post(
        f"{path}/tax-document",
        json=_tax_body(tax_document_type),
        headers=auth(owner_id),
    )

    assert res.status_code == 200
    async with async_session_factory() as session:
        application = await session.scalar(
            select(OrgAttestorApplication).where(
                OrgAttestorApplication.org_id == org_id
            )
        )
    assert application is not None
    assert application.tax_document_type == tax_document_type


@pytest.mark.parametrize(
    ("country", "tax_document_type"),
    [("NG", "w9"), ("NG", "w8ben"), ("US", "firs_tin"), ("GB", "tcc")],
)
async def test_tax_document_type_must_match_org_country(
    client: AsyncClient,
    migrated_database: None,
    clean_state: FakeRedis,
    country: str,
    tax_document_type: str,
) -> None:
    """US IRS forms are refused for Nigerian orgs and Nigerian documents elsewhere."""
    owner_id = await _create_user("owner")
    org_id = await _create_org(owner_id, country=country)
    path = _APPLICATION_PATH.format(org_id=org_id)
    await client.post(path, json=_create_body(), headers=auth(owner_id))

    res = await client.post(
        f"{path}/tax-document",
        json=_tax_body(tax_document_type),
        headers=auth(owner_id),
    )

    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "tax_document_type_not_allowed"
    async with async_session_factory() as session:
        application = await session.scalar(
            select(OrgAttestorApplication).where(
                OrgAttestorApplication.org_id == org_id
            )
        )
    assert application is not None
    assert application.tax_document_key is None


async def test_nominate_trial_member_requires_nda(
    client: AsyncClient, migrated_database: None, clean_state: FakeRedis
) -> None:
    """Nomination fails without an NDA and succeeds once signed."""
    owner_id = await _create_user("owner")
    org_id = await _create_org(owner_id)
    path = _APPLICATION_PATH.format(org_id=org_id)
    await client.post(path, json=_create_body(), headers=auth(owner_id))
    owner_member_id = await _owner_member_id(org_id, owner_id)

    unsigned = await client.post(
        f"{path}/nominate-trial-member",
        json={"member_id": str(owner_member_id)},
        headers=auth(owner_id),
    )
    assert unsigned.status_code == 422
    assert unsigned.json()["detail"] == {"error_code": "nda_required"}

    await client.post(f"/v1/orgs/{org_id}/nda/sign", headers=auth(owner_id))
    signed = await client.post(
        f"{path}/nominate-trial-member",
        json={"member_id": str(owner_member_id)},
        headers=auth(owner_id),
    )
    assert signed.status_code == 200
    assert signed.json()["trial_member_id"] == str(owner_member_id)


async def _owner_member_id(org_id: UUID, owner_id: UUID) -> UUID:
    """Return the org_member id for the owner."""
    async with async_session_factory() as session:
        member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == owner_id,
            )
        )
        assert member is not None
        return member.id
