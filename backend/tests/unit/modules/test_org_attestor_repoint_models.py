"""Re-point column persistence tests (org attestor migration wave 2).

Covers the additive columns from
docs/superpowers/specs/2026-07-04-org-attestor-design.md: attestation
org assignment, offer org key, trial org re-key, payout account org
ownership XOR, and transaction single-payee constraint.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationOffer,
    AttestorTrial,
)
from app.modules.auth.models import User
from app.modules.financials.models import PayoutAccount, Transaction
from app.modules.organizations.models import Organization, OrgMember
from tests.support.db_cleanup import clear_identity_state_async

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current database schema exists for model tests."""
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
async def repoint_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset attestation, financial, org, and identity rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK order before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(AttestorTrial))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Transaction))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_identity() -> tuple[User, Organization, OrgMember]:
    """Create a user, an organization, and the owner membership row."""
    suffix = uuid4().hex[:8]
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"repoint-{suffix}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=f"repoint-{suffix}",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            org = Organization(
                slug=f"repoint-{suffix}",
                name="Repoint Audit Ltd",
                country="US",
                created_by=user.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
            session.add(member)
            await session.flush()
            await session.refresh(user)
            await session.refresh(org)
            await session.refresh(member)
    return user, org, member


def _attestation(requestor_id: object) -> Attestation:
    """Build a minimal framework-target attestation row."""
    return Attestation(
        target_type="framework",
        target_id=uuid4(),
        requestor_id=requestor_id,
        fee_amount=Decimal("100.00"),
    )


async def test_attestation_org_assignment_round_trip(repoint_state: None) -> None:
    """Attestation persists attestor_org_id + reviewing_member_id."""
    user, org, member = await _create_identity()
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=uuid4(),
                requestor_id=user.id,
                fee_amount=Decimal("100.00"),
                attestor_org_id=org.id,
                reviewing_member_id=member.id,
            )
            session.add(attestation)
            await session.flush()
            await session.refresh(attestation)
            assert attestation.attestor_org_id == org.id
            assert attestation.reviewing_member_id == member.id
            assert attestation.attestor_id is None


async def test_offer_org_key_and_unique(repoint_state: None) -> None:
    """Offers persist org_id without attestor_id; (attestation, org) unique."""
    user, org, _ = await _create_identity()
    async with async_session_factory() as session:
        async with session.begin():
            attestation = _attestation(user.id)
            session.add(attestation)
            await session.flush()
            attestation_id = attestation.id
            session.add(
                AttestationOffer(
                    attestation_id=attestation_id,
                    org_id=org.id,
                    cohort_index=0,
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                )
            )
    async with async_session_factory() as session:
        session.add(
            AttestationOffer(
                attestation_id=attestation_id,
                org_id=org.id,
                cohort_index=1,
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_trial_org_re_key_round_trip(repoint_state: None) -> None:
    """Trials persist org_id + member_id with application_id left NULL."""
    _, org, member = await _create_identity()
    async with async_session_factory() as session:
        async with session.begin():
            trial = AttestorTrial(org_id=org.id, member_id=member.id)
            session.add(trial)
            await session.flush()
            await session.refresh(trial)
            assert trial.org_id == org.id
            assert trial.member_id == member.id
            assert trial.application_id is None
            assert trial.org_application_id is None
            assert trial.status == "assigned"


def _payout_account(**owner: object) -> PayoutAccount:
    """Build a payout account row with the given owner column(s)."""
    return PayoutAccount(
        provider="stripe",
        provider_account_id=f"acct_{uuid4().hex[:10]}",
        provider_account_lookup_hash=uuid4().hex,
        account_type="express",
        **owner,
    )


async def test_payout_account_org_owned(repoint_state: None) -> None:
    """An org-owned payout account persists with user_id NULL."""
    _, org, _ = await _create_identity()
    async with async_session_factory() as session:
        async with session.begin():
            account = _payout_account(org_id=org.id)
            session.add(account)
            await session.flush()
            await session.refresh(account)
            assert account.org_id == org.id
            assert account.user_id is None


async def test_payout_account_owner_xor_rejects_both_and_neither(
    repoint_state: None,
) -> None:
    """The XOR CHECK rejects accounts owned by both or neither party."""
    user, org, _ = await _create_identity()
    async with async_session_factory() as session:
        session.add(_payout_account(user_id=user.id, org_id=org.id))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    async with async_session_factory() as session:
        session.add(_payout_account())
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_transaction_org_payee_round_trip(repoint_state: None) -> None:
    """A transaction credits payee_org_id with payee_id NULL."""
    user, org, _ = await _create_identity()
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=user.id,
                payee_org_id=org.id,
                amount=Decimal("90.00"),
                net_amount=Decimal("90.00"),
                transaction_type="attestation_fee",
            )
            session.add(transaction)
            await session.flush()
            await session.refresh(transaction)
            assert transaction.payee_org_id == org.id
            assert transaction.payee_id is None


async def test_transaction_single_payee_check(repoint_state: None) -> None:
    """The single-payee CHECK rejects both payee kinds on one transaction."""
    user, org, _ = await _create_identity()
    async with async_session_factory() as session:
        session.add(
            Transaction(
                payer_id=user.id,
                payee_id=user.id,
                payee_org_id=org.id,
                amount=Decimal("90.00"),
                net_amount=Decimal("90.00"),
                transaction_type="attestation_fee",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
