"""Entitlement matrix for the Attestation access package (§2.5).

Verifies that ``attestation_access_scope`` derives preview / full / none
from live Attestation and Offer status without a persistent grant table.
Full access additionally requires a recorded content-use acknowledgment.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import access_service
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
    AttestorApplication,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, Transaction
from app.modules.frameworks.models import Framework
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Cleanup — mirrors test_attestation_requests.reset_attestation_state
# ---------------------------------------------------------------------------


async def _reset_state() -> None:
    """Remove attestation/user test rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(AttestorApplication))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(Framework))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is at alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Clean attestation/user state before and after the test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


@pytest.fixture
async def operator(clean_state) -> User:
    """Seed an operator user for attestation request ownership."""
    del clean_state
    async with async_session_factory() as session:
        user = User(
            email="entitlement-operator@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="entitlement-operator",
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role="operator",
                approved_at=datetime.now(UTC),
            )
        )
        await session.commit()
        await session.refresh(user)
    return user


@pytest.fixture
async def attestor(clean_state) -> User:
    """Seed an attestor user for access scope checks."""
    del clean_state
    async with async_session_factory() as session:
        user = User(
            email="entitlement-attestor@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="entitlement-attestor",
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role="attestor",
                approved_at=datetime.now(UTC),
            )
        )
        await session.commit()
        await session.refresh(user)
    return user


@pytest.fixture
async def published_framework(operator) -> Framework:
    """Seed a published framework as the entitlement target placeholder."""
    async with async_session_factory() as session:
        framework = Framework(
            contributor_id=operator.id,
            title="Entitlement Test Framework",
            description="Published framework for access-scope tests.",
            status="published",
            category="compliance",
            tags=["test"],
            price=Decimal("199.00"),
            license_types=["single_user"],
            published_at=datetime.now(UTC),
        )
        session.add(framework)
        await session.commit()
        await session.refresh(framework)
    return framework


@pytest.fixture
async def db_session(clean_state) -> AsyncIterator:
    """Provide an async DB session for service calls and assertions."""
    del clean_state
    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_attestation(
    *,
    requestor: User,
    framework: Framework,
    attestor_id: UUID | None,
    status_value: str,
    ack: bool = True,
) -> Attestation:
    """Create an Attestation with optional content acknowledgment."""
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="framework",
            target_id=framework.id,
            requestor_id=requestor.id,
            attestor_id=attestor_id,
            status=status_value,
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            content_ack_at=datetime.now(UTC) if ack else None,
            content_ack_version="v1" if ack else None,
        )
        session.add(attestation)
        await session.commit()
        await session.refresh(attestation)
    return attestation


# ---------------------------------------------------------------------------
# Full access — assigned attestor + review status + ack
# ---------------------------------------------------------------------------


async def test_assigned_accepted_with_ack_is_full(
    db_session, operator, attestor, published_framework
):
    """The assigned attestor with an acknowledgment and accepted status gets full."""
    att = await _make_attestation(
        requestor=operator,
        framework=published_framework,
        attestor_id=attestor.id,
        status_value="accepted",
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "full"


@pytest.mark.parametrize("status_value", ["report_submitted", "disputed"])
async def test_review_states_are_full(
    db_session, operator, attestor, published_framework, status_value
):
    """Report-submitted and disputed keep full access for the assigned attestor."""
    att = await _make_attestation(
        requestor=operator,
        framework=published_framework,
        attestor_id=attestor.id,
        status_value=status_value,
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "full"


# ---------------------------------------------------------------------------
# No ack → no full access
# ---------------------------------------------------------------------------


async def test_accepted_without_ack_is_none(
    db_session, operator, attestor, published_framework
):
    """Accepted but missing the acknowledgment yields no access."""
    att = await _make_attestation(
        requestor=operator,
        framework=published_framework,
        attestor_id=attestor.id,
        status_value="accepted",
        ack=False,
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "none"


# ---------------------------------------------------------------------------
# Terminal states revoke full access
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status_value", ["released", "resolved", "refunded", "closed", "cancelled"]
)
async def test_terminal_states_revoke_full(
    db_session, operator, attestor, published_framework, status_value
):
    """Terminal statuses (including resolved) drop the assigned attestor to none."""
    att = await _make_attestation(
        requestor=operator,
        framework=published_framework,
        attestor_id=attestor.id,
        status_value=status_value,
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "none"


# ---------------------------------------------------------------------------
# Preview — cohort offer
# ---------------------------------------------------------------------------


async def test_cohort_offer_is_preview(
    db_session, operator, attestor, published_framework
):
    """A cohort member with a live offer gets preview, not full."""
    att = await _make_attestation(
        requestor=operator,
        framework=published_framework,
        attestor_id=None,
        status_value="offered",
    )
    async with async_session_factory() as seed_session:
        seed_session.add(
            AttestationOffer(
                attestation_id=att.id,
                attestor_id=attestor.id,
                cohort_index=0,
                status="offered",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )
        await seed_session.commit()

    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "preview"


# ---------------------------------------------------------------------------
# Outsider — no assignment, no offer
# ---------------------------------------------------------------------------


async def test_outsider_is_none(db_session, operator, attestor, published_framework):
    """A user with neither assignment nor a live offer gets none."""
    att = await _make_attestation(
        requestor=operator,
        framework=published_framework,
        attestor_id=None,
        status_value="offered",
    )
    scope = await access_service.attestation_access_scope(
        db_session, attestation=att, user=attestor
    )
    assert scope == "none"
