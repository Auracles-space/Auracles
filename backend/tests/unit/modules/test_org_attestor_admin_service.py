"""Unit tests for the org attestor admin review pipeline and activation.

Covers the platform-admin gate walk: KYB verification, needs-info, trial
start, gated approval (creating the profile, activating the capability, and
granting the org-derived attestor role to every member), terminal rejection,
and capability suspend/reinstate/revoke. Enforces the admin-review section of
docs/superpowers/specs/2026-07-04-org-attestor-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation.models import AttestorTrial
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PayoutAccount
from app.modules.organizations import attestor_application_service as svc
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]

# The six approval gates, keyed by the attribute a test clears to omit each.
_GATE_FIELDS = (
    "kyb_verified_at",
    "coi_signed_at",
    "confidentiality_signed_at",
    "payout_account_id",
    "tax_document_key",
    "trial",
)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current database schema exists for the admin tests."""
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
async def admin_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset org attestor, profile, payout, and identity rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK order before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(AttestorTrial))
            await session.execute(delete(OrgAttestorProfile))
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


async def _new_user(prefix: str) -> UUID:
    """Create a verified user; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def _org_with_members(member_count: int = 1) -> tuple[UUID, UUID, list[UUID]]:
    """Create org + pending attestor capability + owner and N plain members.

    Returns (org_id, admin_id, member_user_ids) where member_user_ids includes
    the owner and any plain members.
    """
    admin_id = await _new_user("platform-admin")
    owner_id = await _new_user("owner")
    member_ids = [owner_id]
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"admin-{uuid4().hex[:6]}",
                name="Admin Test Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            session.add(
                OrgCapability(org_id=org.id, capability="attestor", status="pending")
            )
            org_id = org.id
    for i in range(member_count - 1):
        uid = await _new_user(f"member{i}")
        member_ids.append(uid)
        async with async_session_factory() as session:
            async with session.begin():
                session.add(OrgMember(org_id=org_id, user_id=uid, role="member"))
    return org_id, admin_id, member_ids


async def _gated_application(
    org_id: UUID,
    owner_member_user_id: UUID,
    *,
    omit: str | None = None,
) -> UUID:
    """Create a submitted application with all approval gates satisfied.

    Args:
        org_id: Organization owning the application.
        owner_member_user_id: The owner's user id (for the trial member).
        omit: When set, the named gate is left unsatisfied.

    Returns:
        The application id.
    """
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            member = await session.scalar(
                select(OrgMember).where(
                    OrgMember.org_id == org_id,
                    OrgMember.user_id == owner_member_user_id,
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
                legal_name="Acme Attestations Ltd",
                registration_number="RC123456",
                incorporation_doc_keys=["kyb/acme/cert.pdf"],
                sectors=["private_equity"],
                functions=["compliance"],
                jurisdictions=["united_states"],
                credentials_summary=(
                    "Two decades of private equity compliance experience."
                ),
                sample_work={"portfolio": "https://example.com"},
                professional_references="Jane Roe, MD.",
                kyb_verified_at=None if omit == "kyb_verified_at" else now,
                kyb_verified_by=None,
                coi_declarations=[],
                coi_signed_at=None if omit == "coi_signed_at" else now,
                coi_expires_at=now,
                confidentiality_signed_at=(
                    None if omit == "confidentiality_signed_at" else now
                ),
                payout_account_id=(
                    None if omit == "payout_account_id" else account.id
                ),
                tax_document_type="w9",
                tax_document_key=(
                    None if omit == "tax_document_key" else "org-tax/key.pdf"
                ),
                trial_member_id=member.id,
            )
            session.add(application)
            await session.flush()
            if omit != "trial":
                session.add(
                    AttestorTrial(
                        org_application_id=application.id,
                        org_id=org_id,
                        member_id=member.id,
                        status="passed",
                    )
                )
            return application.id


async def _role_count(user_id: UUID) -> int:
    """Return how many attestor UserRole rows a user holds."""
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.role == "attestor",
                )
            )
        ).all()
    return len(rows)


@pytest.mark.parametrize("omit", _GATE_FIELDS)
async def test_approve_blocked_when_gate_missing(
    admin_state: None, omit: str
) -> None:
    """Approval is rejected (422) when any single gate is unsatisfied."""
    org_id, admin_id, members = await _org_with_members()
    application_id = await _gated_application(org_id, members[0], omit=omit)
    with pytest.raises(HTTPException) as exc:
        async with async_session_factory() as session:
            await svc.admin_approve(
                session, application_id=application_id, admin_id=admin_id
            )
    assert exc.value.status_code == 422


async def test_approve_activates_and_grants_roles_to_all_members(
    admin_state: None,
) -> None:
    """Approval creates the profile, activates the capability, and grants roles."""
    org_id, admin_id, members = await _org_with_members(member_count=2)
    application_id = await _gated_application(org_id, members[0])

    async with async_session_factory() as session:
        application = await svc.admin_approve(
            session, application_id=application_id, admin_id=admin_id
        )
    assert application.status == "approved"

    async with async_session_factory() as session:
        profile = await session.scalar(
            select(OrgAttestorProfile).where(OrgAttestorProfile.org_id == org_id)
        )
        assert profile is not None and profile.active is True
        capability = await session.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == "attestor",
            )
        )
        assert capability is not None and capability.status == "active"
    # Every member — owner and plain member — gains the derived attestor role.
    assert await _role_count(members[0]) == 1
    assert await _role_count(members[1]) == 1


async def test_reject_is_terminal_and_allows_reapply(admin_state: None) -> None:
    """Rejection is terminal; the org may open a fresh application afterwards."""
    org_id, admin_id, members = await _org_with_members()
    application_id = await _gated_application(org_id, members[0])
    async with async_session_factory() as session:
        application = await svc.admin_reject(
            session,
            application_id=application_id,
            admin_id=admin_id,
            feedback="Insufficient references.",
        )
    assert application.status == "rejected"

    from app.modules.organizations.schemas import OrgAttestorApplicationCreateRequest

    async with async_session_factory() as session:
        reapplied = await svc.create_application(
            session,
            org_id=org_id,
            actor_id=members[0],
            payload=OrgAttestorApplicationCreateRequest(
                sectors=["private_equity"],
                functions=["compliance"],
                jurisdictions=["united_states"],
                credentials_summary="Reapplication with new references provided.",
                professional_references="New references list.",
            ),
        )
    assert reapplied.status == "draft"


async def test_suspend_revokes_and_reinstate_regrants_roles(
    admin_state: None,
) -> None:
    """Suspend revokes the sole-org derived role; reinstate restores it."""
    org_id, admin_id, members = await _org_with_members()
    application_id = await _gated_application(org_id, members[0])
    async with async_session_factory() as session:
        await svc.admin_approve(
            session, application_id=application_id, admin_id=admin_id
        )
    assert await _role_count(members[0]) == 1

    async with async_session_factory() as session:
        await svc.admin_set_capability_status(
            session, org_id=org_id, admin_id=admin_id, status_value="suspended"
        )
    assert await _role_count(members[0]) == 0

    async with async_session_factory() as session:
        await svc.admin_set_capability_status(
            session, org_id=org_id, admin_id=admin_id, status_value="active"
        )
    assert await _role_count(members[0]) == 1


async def test_verify_kyb_and_needs_info_transitions(
    admin_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KYB verification stamps the row; needs-info moves submitted → needs_info."""
    # Reserved doc keys have no uploaded object in tests; treat them as present
    # so the KYB-verify existence gate does not block this transition test.
    monkeypatch.setattr(svc.s3.storage, "object_exists", lambda bucket, key: True)
    org_id, admin_id, members = await _org_with_members()
    application_id = await _gated_application(
        org_id, members[0], omit="kyb_verified_at"
    )

    async with async_session_factory() as session:
        verified = await svc.admin_verify_kyb(
            session, application_id=application_id, admin_id=admin_id
        )
    assert verified.kyb_verified_at is not None
    assert verified.kyb_verified_by == admin_id

    async with async_session_factory() as session:
        held = await svc.admin_needs_info(
            session,
            application_id=application_id,
            admin_id=admin_id,
            feedback="Please clarify jurisdiction coverage.",
        )
    assert held.status == "needs_info"
    assert held.admin_feedback == "Please clarify jurisdiction coverage."
