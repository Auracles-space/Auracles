"""Badge publish wiring for attestation close transactions (Module 6c)."""

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
from app.modules.attestation import release_service
from app.modules.attestation.models import Attestation, AttestationBadge
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, Transaction
from app.modules.frameworks.models import Framework, FrameworkVersion
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Remove badge-publish wiring rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationBadge))
            await session.execute(delete(Attestation))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Framework))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database is upgraded to the current alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset state before and after each wiring test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


async def _make_user(*, role: str, prefix: str) -> User:
    """Create one verified user with an approved role row."""
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
            session.add(
                UserRole(
                    user_id=user.id,
                    role=role,
                    approved_at=datetime.now(UTC),
                )
            )
        await session.refresh(user)
        return user


async def _seed_report_submitted_framework_attestation() -> tuple[UUID, UUID]:
    """Create a report-submitted framework attestation ready for acceptance."""
    contributor = await _make_user(role="contributor", prefix="requestor")
    attestor = await _make_user(role="attestor", prefix="attestor")
    current_time = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor.id,
                title="Close-Path Badge Framework",
                description="Published framework for close-path badge wiring.",
                version="1.2",
                status="published",
                category="compliance",
                tags=["badge"],
                price=Decimal("199.00"),
                license_types=["single_user"],
                published_at=current_time - timedelta(days=7),
            )
            session.add(framework)
            await session.flush()
            snapshot = FrameworkVersion(
                framework_id=framework.id,
                version="1.2",
                change_type="improvement",
                change_log="Snapshot for close-path badge wiring.",
                published_at=current_time - timedelta(days=7),
            )
            session.add(snapshot)
            await session.flush()
            attestation = Attestation(
                target_type="framework",
                target_id=framework.id,
                requestor_id=contributor.id,
                attestor_id=attestor.id,
                status="report_submitted",
                outcome="approved",
                review_type="quality",
                framework_version_id=snapshot.id,
                requested_specializations=["governance"],
                requested_jurisdictions=["US"],
                summary="The reviewed framework evidence supports approval.",
                scope="Framework control design review.",
                evidence_references={},
                report_key=f"attestation-reports/{uuid4()}/report.pdf",
                fee_amount=Decimal("500.00"),
                currency="USD",
                accepted_at=current_time - timedelta(days=1),
                completion_due_at=current_time + timedelta(days=6),
                issued_at=current_time - timedelta(hours=1),
                dispute_window_ends_at=current_time + timedelta(days=14),
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=contributor.id,
                payee_id=attestor.id,
                amount=Decimal("500.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("500.00"),
                transaction_type="attestation_fee",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_attestation_release_{uuid4()}",
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
            return contributor.id, attestation.id


async def test_accept_report_publishes_badge(clean_state: None) -> None:
    """Accepting a submitted framework report writes the badge in the close txn."""
    del clean_state
    requestor_id, attestation_id = await _seed_report_submitted_framework_attestation()

    async with async_session_factory() as session:
        requestor = await session.get(User, requestor_id)
        assert requestor is not None
        await release_service.accept_report(
            db=session,
            requestor=requestor,
            attestation_id=attestation_id,
        )

    async with async_session_factory() as session:
        badge = await session.scalar(
            select(AttestationBadge).where(
                AttestationBadge.attestation_id == attestation_id
            )
        )

    assert badge is not None
