"""Unit tests for attestation clarification SLA-pause math."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import clarification_service
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationArtifactAccess,
    AttestationClarification,
    AttestationDispute,
    AttestationOffer,
    AttestationRubricScore,
    AttestationUploadSession,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear clarification-test rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationClarification))
            await session.execute(delete(AttestationAnnotation))
            await session.execute(delete(AttestationRubricScore))
            await session.execute(delete(AttestationArtifactAccess))
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
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
    """Clean clarification state before and after each test."""
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
    """Provide an async session for clarification service calls."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _make_user(role: str, prefix: str) -> User:
    """Create one verified user with one approved role row."""
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


async def _in_review_attestation() -> tuple[User, User, Attestation]:
    """Create one in-review org attestation with a reviewing member and requestor."""
    attestor = await _make_user("attestor", "attestor")
    requestor = await _make_user("operator", "requestor")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        org = Organization(
            slug=f"clar-u-org-{uuid4().hex[:6]}",
            name="Clarification Unit Org LLP",
            country="US",
            created_by=attestor.id,
        )
        session.add(org)
        await session.flush()
        member = OrgMember(org_id=org.id, user_id=attestor.id, role="owner")
        session.add(member)
        session.add(
            OrgAttestorProfile(
                org_id=org.id,
                specializations=["tax"],
                jurisdictions=["US"],
                sectors=["tax"],
                functions=[],
                active=True,
                approved_at=now,
                coi_signed_at=now,
                coi_expires_at=now + timedelta(days=365),
            )
        )
        await session.flush()
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor.id,
            attestor_org_id=org.id,
            reviewing_member_id=member.id,
            status="in_review",
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            completion_due_at=now + timedelta(days=7),
        )
        session.add(attestation)
        await session.commit()
        await session.refresh(attestation)
    return attestor, requestor, attestation


async def _force_answer(db_session, clarification_id: UUID) -> None:
    """Mark one clarification answered so a follow-up send is not open-blocked."""
    clarification = await db_session.get(AttestationClarification, clarification_id)
    assert clarification is not None
    clarification.status = "answered"
    clarification.responded_at = datetime.now(UTC)
    clarification.response = "answered"
    await db_session.commit()


async def _requestor_of(attestation: Attestation) -> User:
    """Load the requestor for one attestation."""
    async with async_session_factory() as session:
        requestor = await session.get(User, attestation.requestor_id)
        assert requestor is not None
        return requestor


async def test_send_extends_completion_deadline(db_session) -> None:
    """Sending a clarification pushes completion_due_at out by the 48h window."""
    attestor, _requestor, attestation = await _in_review_attestation()
    before = attestation.completion_due_at
    assert before is not None
    now = datetime.now(UTC)

    clarification = await clarification_service.send_clarification(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        question="Which framework version is in scope?",
        now=now,
    )
    refreshed = await db_session.get(Attestation, attestation.id)
    assert refreshed is not None

    assert clarification.response_due_at == now + timedelta(hours=48)
    assert refreshed.completion_due_at == before + timedelta(hours=48)


async def test_third_clarification_rejected(db_session) -> None:
    """No more than two clarifications may be sent for one assignment."""
    attestor, _requestor, attestation = await _in_review_attestation()

    for index in range(2):
        clarification = await clarification_service.send_clarification(
            db_session,
            attestor=attestor,
            attestation_id=attestation.id,
            question=f"q{index}",
        )
        await _force_answer(db_session, clarification.id)

    with pytest.raises(HTTPException) as exc:
        await clarification_service.send_clarification(
            db_session,
            attestor=attestor,
            attestation_id=attestation.id,
            question="q3",
        )

    assert exc.value.status_code == 422


async def test_respond_trims_unused_remainder(db_session) -> None:
    """Answering early returns the unused clarification remainder to the SLA."""
    attestor, _requestor, attestation = await _in_review_attestation()
    sent_at = datetime.now(UTC)
    clarification = await clarification_service.send_clarification(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        question="Which version is in scope?",
        now=sent_at,
    )
    refreshed = await db_session.get(Attestation, attestation.id)
    assert refreshed is not None
    extended_due_at = refreshed.completion_due_at
    assert extended_due_at is not None

    responded_at = sent_at + timedelta(hours=10)
    requestor = await _requestor_of(attestation)
    await clarification_service.respond_to_clarification(
        db_session,
        requestor=requestor,
        attestation_id=attestation.id,
        clarification_id=clarification.id,
        response="Use version 2.",
        now=responded_at,
    )

    refreshed = await db_session.get(Attestation, attestation.id)
    assert refreshed is not None
    assert refreshed.completion_due_at == extended_due_at - timedelta(hours=38)


async def test_only_requestor_can_respond(db_session) -> None:
    """A non-requestor cannot answer a clarification on the assignment."""
    attestor, _requestor, attestation = await _in_review_attestation()
    clarification = await clarification_service.send_clarification(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        question="Which version is in scope?",
    )

    with pytest.raises(HTTPException) as exc:
        await clarification_service.respond_to_clarification(
            db_session,
            requestor=attestor,
            attestation_id=attestation.id,
            clarification_id=clarification.id,
            response="Version 2.",
        )

    assert exc.value.status_code == 404


async def test_expire_closes_overdue_open(db_session) -> None:
    """An open clarification past its due time is expired by the sweep."""
    attestor, _requestor, attestation = await _in_review_attestation()
    now = datetime.now(UTC)
    clarification = await clarification_service.send_clarification(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        question="Which version is in scope?",
        now=now - timedelta(hours=49),
    )

    count = await clarification_service.expire_clarifications(db_session, now=now)
    refreshed = await db_session.get(AttestationClarification, clarification.id)
    assert refreshed is not None

    assert count == 1
    assert refreshed.status == "expired"
