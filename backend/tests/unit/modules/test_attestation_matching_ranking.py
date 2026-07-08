"""Unit tests for overdue-assignment revocation in the attestation beat.

Org-based eligibility, screening, and ranking of ``_rank_eligible_attestors``
now live in ``test_org_attestation_matching_service.py``; this module retains
the SLA revoke-beat coverage that operates on the ``attestor_id`` assignment.

Maps to: spec §4.8 (completion SLA revocation).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import matching_service
from app.modules.attestation.models import (
    Attestation,
    AttestationOffer,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Remove ranking-test rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is at alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Clean attestation state before and after each test."""
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
    """Provide an async session for ranking service calls."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _make_user(role: str, prefix: str) -> User:
    """Create one user with an approved role row."""
    async with async_session_factory() as session:
        user = User(
            email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name=prefix,
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC)))
        await session.commit()
        await session.refresh(user)
    return user


async def _make_attestor_org(owner_id: UUID) -> tuple[UUID, UUID]:
    """Create an active attestor org owned by ``owner_id``.

    Returns ``(org_id, member_id)``.
    """
    async with async_session_factory() as session:
        org = Organization(
            slug=f"revoke-org-{uuid4().hex[:6]}",
            name="Revoke Org LLP",
            country="US",
            created_by=owner_id,
        )
        session.add(org)
        await session.flush()
        member = OrgMember(org_id=org.id, user_id=owner_id, role="owner")
        session.add(member)
        session.add(
            OrgAttestorProfile(
                org_id=org.id,
                specializations=["tax"],
                jurisdictions=["US"],
                active=True,
            )
        )
        await session.commit()
        await session.refresh(member)
    return org.id, member.id


async def _make_assigned_attestation_with_funding(
    requestor_id: UUID,
    org_id: UUID,
    member_id: UUID,
    *,
    status_value: str,
    completion_due_at: datetime,
) -> Attestation:
    """Create one funded org-staffed attestation for revoke-beat tests."""
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="contributor",
            target_id=requestor_id,
            requestor_id=requestor_id,
            attestor_org_id=org_id,
            reviewing_member_id=member_id,
            status=status_value,
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            accepted_at=datetime.now(UTC) - timedelta(days=1),
            completion_due_at=completion_due_at,
        )
        session.add(attestation)
        await session.flush()
        offer = AttestationOffer(
            attestation_id=attestation.id,
            org_id=org_id,
            cohort_index=1,
            status="accepted",
            offered_at=datetime.now(UTC) - timedelta(days=2),
            responded_at=datetime.now(UTC) - timedelta(days=1),
            expires_at=datetime.now(UTC) - timedelta(days=1, hours=1),
            match_score=0.950,
            score_breakdown={"fit": 0.950},
        )
        session.add(offer)
        transaction = Transaction(
            payer_id=requestor_id,
            payee_id=None,
            amount=Decimal("500.00"),
            currency="USD",
            platform_commission=Decimal("0.00"),
            net_amount=Decimal("500.00"),
            transaction_type="attestation_fee",
            status="completed",
            provider="stripe",
            provider_ref=f"pi_attestation_{uuid4()}",
            ref_id=attestation.id,
            ref_type="attestation",
        )
        session.add(transaction)
        await session.commit()
        await session.refresh(attestation)
    return attestation


async def test_revoke_overdue_attestations_includes_in_review_past_grace(
    db_session,
) -> None:
    """An in-review assignment past the grace window is revoked."""
    requestor = await _make_user("operator", "req")
    attestor = await _make_user("attestor", "att")
    org_id, member_id = await _make_attestor_org(attestor.id)
    attestation = await _make_assigned_attestation_with_funding(
        requestor.id,
        org_id,
        member_id,
        status_value="in_review",
        completion_due_at=datetime.now(UTC) - timedelta(hours=25),
    )

    count = await matching_service.revoke_overdue_attestations(db_session)
    refreshed = await db_session.get(Attestation, attestation.id)
    transaction = await db_session.scalar(
        select(Transaction).where(Transaction.ref_id == attestation.id)
    )
    offer = await db_session.scalar(
        select(AttestationOffer).where(
            AttestationOffer.attestation_id == attestation.id
        )
    )
    assert refreshed is not None
    assert transaction is not None
    assert offer is not None

    assert count == 1
    assert refreshed.attestor_org_id is None
    assert refreshed.reviewing_member_id is None
    assert refreshed.completion_due_at is None
    assert refreshed.status == "needs_admin"
    assert transaction.payee_id is None
    assert offer.status == "superseded"


async def test_revoke_overdue_attestations_respects_completion_grace(
    db_session,
) -> None:
    """An in-review assignment inside the grace window is left untouched."""
    requestor = await _make_user("operator", "req")
    attestor = await _make_user("attestor", "att")
    org_id, member_id = await _make_attestor_org(attestor.id)
    attestation = await _make_assigned_attestation_with_funding(
        requestor.id,
        org_id,
        member_id,
        status_value="in_review",
        completion_due_at=datetime.now(UTC) - timedelta(hours=23),
    )

    count = await matching_service.revoke_overdue_attestations(db_session)
    refreshed = await db_session.get(Attestation, attestation.id)
    transaction = await db_session.scalar(
        select(Transaction).where(Transaction.ref_id == attestation.id)
    )
    offer = await db_session.scalar(
        select(AttestationOffer).where(
            AttestationOffer.attestation_id == attestation.id
        )
    )
    assert refreshed is not None
    assert transaction is not None
    assert offer is not None

    assert count == 0
    assert refreshed.attestor_org_id == org_id
    assert refreshed.reviewing_member_id == member_id
    assert refreshed.status == "in_review"
    assert transaction.payee_id is None
    assert offer.status == "accepted"
