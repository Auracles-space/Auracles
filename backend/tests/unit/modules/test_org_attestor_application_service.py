"""Unit tests for the org attestor application (org-side) service.

Covers the draft → submit lifecycle, owner-signed undertakings (TOTP-gated),
tax-document and payout gates, trial-member nomination (NDA-gated), and the
per-gate checklist derived from a single application row. Enforces the
application flow of docs/superpowers/specs/2026-07-04-org-attestor-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import encrypt_totp_secret, hash_password
from app.main import app
from app.modules.attestation.models import AttestorTrial
from app.modules.auth.models import User
from app.modules.financials.models import PayoutAccount
from app.modules.organizations import attestor_application_service as svc
from app.modules.organizations import nda_service
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from app.modules.organizations.schemas import (
    OrgAttestorApplicationCreateRequest,
    OrgAttestorApplicationUpdateRequest,
    OrgAttestorTaxDocumentRequest,
    OrgUndertakingsSignRequest,
)
from tests.integration.test_auth_sessions import FakeRedis
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current database schema exists for the service tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def app_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset org attestor, payout, and identity rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK order before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(AttestorTrial))
            await session.execute(delete(OrgAttestorApplication))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_org(
    *,
    attestor_status: str | None = None,
    totp: bool = False,
) -> tuple[UUID, OwnerFixture]:
    """Create user + org + owner member; return (org_id, owner fixture)."""
    suffix = uuid4().hex[:8]
    secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"orgatt-{suffix}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=f"orgatt-{suffix}",
                email_verified=True,
                totp_enabled=totp,
                totp_secret=encrypt_totp_secret(secret) if totp else None,
            )
            session.add(user)
            await session.flush()
            org = Organization(
                slug=f"orgatt-{suffix}",
                name="Org Attestor Test",
                country="US",
                created_by=user.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
            session.add(member)
            await session.flush()
            if attestor_status is not None:
                session.add(
                    OrgCapability(
                        org_id=org.id,
                        capability="attestor",
                        status=attestor_status,
                    )
                )
            return org.id, OwnerFixture(
                user_id=user.id, member_id=member.id, totp_secret=secret
            )


class OwnerFixture:
    """Test fixture carrying the owner's ids and TOTP secret."""

    def __init__(self, *, user_id: UUID, member_id: UUID, totp_secret: str) -> None:
        self.user_id = user_id
        self.member_id = member_id
        self.totp_secret = totp_secret


def _valid_create() -> OrgAttestorApplicationCreateRequest:
    """Return a complete, valid create request payload."""
    return OrgAttestorApplicationCreateRequest(
        legal_name="Acme Attestations Ltd",
        registration_number="RC123456",
        incorporation_doc_keys=["kyb/acme/cert.pdf"],
        sectors=["PE"],
        framework_categories=["Compliance"],
        jurisdictions=["US"],
        credentials_summary="Two decades of PE compliance attestation experience.",
        sample_work={"portfolio": "https://example.com/samples"},
        professional_references="Jane Roe, MD of Example Capital.",
    )


async def _load_user(user_id: UUID) -> User:
    """Load a User row by id for TOTP-dependent service calls."""
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        return user


async def test_create_rejects_second_live_application(app_state: None) -> None:
    """A second live application for the same org raises 409."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.create_application(
                session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
            )
    assert exc.value.status_code == 409


async def test_update_after_submit_rejected(app_state: None) -> None:
    """Editing an application already submitted raises 409."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    async with async_session_factory() as session:
        await svc.submit_application(session, org_id=org_id, actor_id=owner.user_id)
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.update_application(
                session,
                org_id=org_id,
                actor_id=owner.user_id,
                payload=OrgAttestorApplicationUpdateRequest(legal_name="New Name Ltd"),
            )
    assert exc.value.status_code == 409


async def test_submit_incomplete_kyb_rejected(app_state: None) -> None:
    """Submitting without KYB fields raises 422."""
    org_id, owner = await _create_org()
    async with async_session_factory() as session:
        payload = _valid_create()
        payload.legal_name = None
        payload.registration_number = None
        payload.incorporation_doc_keys = []
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=payload
        )
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.submit_application(
                session, org_id=org_id, actor_id=owner.user_id
            )
    assert exc.value.status_code == 422


async def test_sign_undertakings_wrong_totp_rejected(app_state: None) -> None:
    """Signing undertakings with an invalid TOTP code raises 422."""
    org_id, owner = await _create_org(attestor_status="pending", totp=True)
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    user = await _load_user(owner.user_id)
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.sign_undertakings(
                session,
                FakeRedis(),
                org_id=org_id,
                user=user,
                payload=OrgUndertakingsSignRequest(
                    declarations=[],
                    accept_policy=True,
                    accept_confidentiality=True,
                    totp_code="000000",
                ),
            )
    assert exc.value.status_code == 422


async def test_nominate_unsigned_member_rejected(app_state: None) -> None:
    """Nominating a member without a current NDA signature raises 422."""
    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.nominate_trial_member(
                session,
                org_id=org_id,
                actor_id=owner.user_id,
                member_id=owner.member_id,
            )
    assert exc.value.status_code == 422
    assert exc.value.detail == {"error_code": "nda_required"}


async def test_nominate_signed_member_succeeds(app_state: None) -> None:
    """Nominating an NDA-signed member stamps the trial member."""
    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        await nda_service.sign_nda(session, org_id=org_id, user_id=owner.user_id)
    async with async_session_factory() as session:
        application = await svc.nominate_trial_member(
            session, org_id=org_id, actor_id=owner.user_id, member_id=owner.member_id
        )
    assert application.trial_member_id == owner.member_id


async def test_gate_checklist_reflects_service_stamps(app_state: None) -> None:
    """Signing undertakings, linking payout, and setting tax flip their gates."""
    org_id, owner = await _create_org(attestor_status="pending", totp=True)
    async with async_session_factory() as session:
        await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        _, checklist = await svc.get_application(session, org_id=org_id)
    assert checklist.undertakings_signed is False
    assert checklist.payout_account_linked is False
    assert checklist.tax_document_uploaded is False

    user = await _load_user(owner.user_id)
    code = pyotp.TOTP(owner.totp_secret).now()
    async with async_session_factory() as session:
        await svc.sign_undertakings(
            session,
            FakeRedis(),
            org_id=org_id,
            user=user,
            payload=OrgUndertakingsSignRequest(
                declarations=[],
                accept_policy=True,
                accept_confidentiality=True,
                totp_code=code,
            ),
        )

    # Link an org-owned payout account through the partial update path.
    async with async_session_factory() as session:
        account = PayoutAccount(
            org_id=org_id,
            provider="stripe",
            provider_account_id=f"acct_{uuid4().hex[:12]}",
            provider_account_lookup_hash=uuid4().hex + uuid4().hex,
            account_type="express",
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        account_id = account.id
    async with async_session_factory() as session:
        await svc.update_application(
            session,
            org_id=org_id,
            actor_id=owner.user_id,
            payload=OrgAttestorApplicationUpdateRequest(payout_account_id=account_id),
        )

    async with async_session_factory() as session:
        await svc.set_tax_document(
            session,
            org_id=org_id,
            actor_id=owner.user_id,
            payload=OrgAttestorTaxDocumentRequest(
                tax_document_type="w9",
                file_name="w9.pdf",
                content_type="application/pdf",
                size_bytes=1024,
            ),
        )

    async with async_session_factory() as session:
        _, checklist = await svc.get_application(session, org_id=org_id)
    assert checklist.undertakings_signed is True
    assert checklist.payout_account_linked is True
    assert checklist.tax_document_uploaded is True


async def test_gate_checklist_reflects_admin_and_trial_stamps(app_state: None) -> None:
    """KYB verification, review, and a passed trial flip their gates."""
    from datetime import UTC, datetime

    org_id, owner = await _create_org(attestor_status="pending")
    async with async_session_factory() as session:
        application = await svc.create_application(
            session, org_id=org_id, actor_id=owner.user_id, payload=_valid_create()
        )
        application_id = application.id

    now = datetime.now(UTC)
    async with async_session_factory() as session:
        row = await session.get(OrgAttestorApplication, application_id)
        assert row is not None
        row.kyb_verified_at = now
        row.reviewed_at = now
        row.status = "submitted"
        session.add(
            AttestorTrial(
                org_application_id=application_id,
                org_id=org_id,
                member_id=owner.member_id,
                status="passed",
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        _, checklist = await svc.get_application(session, org_id=org_id)
    assert checklist.kyb_verified is True
    assert checklist.credentials_reviewed is True
    assert checklist.trial_passed is True
