"""Integration tests for the timestamps Treasury history is rebuilt from.

The monthly statement reconstructs past months from dates. Two changes had
none: an escrow being refunded and a partner commission being voided. Each
state change must now stamp its time, and undoing it must clear the stamp,
so a past month is not rewritten by what happened later.

Maps to: platform treasury design §Statement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.database import async_session_factory, engine
from app.modules.developer import commission_service
from app.modules.developer.models import PartnerCommission
from app.modules.financials import escrow_service, refunds
from app.modules.financials import service as financials_service
from app.modules.financials.models import Escrow, Transaction
from tests.integration.test_admin_treasury_summary import _reset, _user
from tests.integration.test_treasury_statement import _partner_commission


@pytest.fixture
async def timestamp_context() -> AsyncIterator[None]:
    """Reset treasury state around each test."""
    await engine.dispose()
    await _reset()
    try:
        yield
    finally:
        await _reset()
        await engine.dispose()


async def _held_milestone_escrow() -> tuple[UUID, UUID, UUID]:
    """Create a completed milestone charge with held escrow."""
    operator_id = await _user("operator")
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=operator_id,
                amount=Decimal("20000.00"),
                currency="NGN",
                platform_commission=Decimal("3000.00"),
                net_amount=Decimal("17000.00"),
                transaction_type="milestone",
                status="completed",
                provider="paystack",
                provider_ref=f"ts-{uuid4().hex[:8]}",
                ref_id=uuid4(),
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=transaction.ref_id,
                ref_type="project_milestone",
                amount=Decimal("20000.00"),
                currency="NGN",
                status="held",
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            return escrow.id, transaction.id, operator_id


async def test_refunding_escrow_stamps_the_time_and_a_declined_refund_clears_it(
    timestamp_context: None,
) -> None:
    """refunded_at is set on refund and cleared when the provider declines it."""
    escrow_id, transaction_id, operator_id = await _held_milestone_escrow()

    async with async_session_factory() as session:
        async with session.begin():
            await escrow_service.refund(
                session, escrow_id=escrow_id, actor_id=operator_id, reason="cancelled"
            )
    async with async_session_factory() as session:
        refunded = await session.get(Escrow, escrow_id)
        assert refunded is not None
        refunded_at = refunded.refunded_at

    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.get(Transaction, transaction_id)
            assert transaction is not None
            await refunds.reverse_refund(session, transaction, source="webhook")
    async with async_session_factory() as session:
        restored = await session.get(Escrow, escrow_id)

    assert refunded_at is not None
    assert restored is not None
    assert restored.status == "held"
    assert restored.refunded_at is None


async def _voidable_commission() -> tuple[UUID, UUID, UUID]:
    """Create a refunded sale with a pending partner commission."""
    ids = await _partner_commission(sale_status="refunded", status="pending")
    return ids["commission_id"], ids["transaction_id"], ids["operator_id"]


async def test_clearing_task_void_stamps_voided_at(timestamp_context: None) -> None:
    """The clearing task's void records when the commission was voided."""
    commission_id, _, _ = await _voidable_commission()

    async with async_session_factory() as session:
        async with session.begin():
            await commission_service.clear_partner_commissions(session)
    async with async_session_factory() as session:
        commission = await session.get(PartnerCommission, commission_id)

    assert commission is not None
    assert commission.status == "voided"
    assert commission.voided_at is not None


async def test_refund_void_stamps_and_reinstatement_clears_voided_at(
    timestamp_context: None,
) -> None:
    """A refund void records its time; a declined refund's reinstatement clears it."""
    commission_id, transaction_id, operator_id = await _voidable_commission()

    async with async_session_factory() as session:
        async with session.begin():
            await financials_service._void_partner_commission_for_refund(
                session, transaction_id=transaction_id, operator_id=operator_id
            )
    async with async_session_factory() as session:
        voided = await session.get(PartnerCommission, commission_id)
        assert voided is not None
        voided_at = voided.voided_at

    async with async_session_factory() as session:
        async with session.begin():
            transaction = await session.get(Transaction, transaction_id)
            assert transaction is not None
            await refunds._reinstate_voided_commissions(session, transaction)
    async with async_session_factory() as session:
        reinstated = await session.get(PartnerCommission, commission_id)

    assert voided_at is not None
    assert reinstated is not None
    assert reinstated.status == "pending"
    assert reinstated.voided_at is None
