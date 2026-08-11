"""Unit tests for the provider-neutral financial event ledger helper.

Covers the guarantees the ledger exists to provide: a money state change is
recorded with its cause, the record is atomic with the change it describes, and
provider payloads never leak secrets into durable storage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.modules.financials.ledger import (
    FinancialLedgerError,
    record_financial_event,
)
from app.modules.financials.models import FinancialEvent


async def _truncate() -> None:
    """Clear the ledger between tests."""
    async with async_session_factory() as session:
        await session.execute(
            text(f"TRUNCATE TABLE {FinancialEvent.__tablename__} RESTART IDENTITY")
        )
        await session.commit()


@pytest.fixture
async def ledger_session(migrated_database: None) -> AsyncIterator[AsyncSession]:
    """Provide a clean async session scoped to one ledger test."""
    await engine.dispose()
    await _truncate()
    session = async_session_factory()
    yield session
    await session.close()
    await _truncate()
    await engine.dispose()


@pytest.mark.asyncio
async def test_records_transition_with_normalized_failure_reason(
    ledger_session: AsyncSession,
) -> None:
    """A failed payment records both its transition and why it failed.

    This is the gap the ledger closes: `transactions.status` alone says
    `failed` without a cause, and the prior status is overwritten.
    """
    transaction_id = uuid4()
    await record_financial_event(
        ledger_session,
        entity_type="transaction",
        entity_id=transaction_id,
        event_type="purchase_failed",
        from_status="pending",
        to_status="failed",
        amount=Decimal("120.00"),
        currency="NGN",
        provider="paystack",
        provider_ref="ref_abc123",
        reason_code="insufficient_funds",
        reason_message="Declined by issuing bank.",
    )
    await ledger_session.commit()

    event = await ledger_session.scalar(
        select(FinancialEvent).where(FinancialEvent.entity_id == transaction_id)
    )

    assert event is not None
    assert event.from_status == "pending"
    assert event.to_status == "failed"
    assert event.reason_code == "insufficient_funds"
    assert event.reason_message == "Declined by issuing bank."
    assert event.provider == "paystack"
    assert event.amount == Decimal("120.00")


@pytest.mark.asyncio
async def test_event_is_atomic_with_the_change_it_describes(
    ledger_session: AsyncSession,
) -> None:
    """The helper must not commit, so a rolled-back money change leaves no event.

    A ledger row that outlives a failed transaction would claim money moved
    when it did not.
    """
    transaction_id = uuid4()
    await record_financial_event(
        ledger_session,
        entity_type="transaction",
        entity_id=transaction_id,
        event_type="purchase_initiated",
        to_status="pending",
    )
    await ledger_session.rollback()

    event = await ledger_session.scalar(
        select(FinancialEvent).where(FinancialEvent.entity_id == transaction_id)
    )

    assert event is None


@pytest.mark.asyncio
async def test_amount_without_currency_is_rejected(
    ledger_session: AsyncSession,
) -> None:
    """An amount with no currency is unreadable money and must not persist."""
    with pytest.raises(FinancialLedgerError):
        await record_financial_event(
            ledger_session,
            entity_type="transaction",
            entity_id=uuid4(),
            event_type="purchase_initiated",
            amount=Decimal("10.00"),
        )


@pytest.mark.asyncio
async def test_unknown_entity_type_is_rejected(ledger_session: AsyncSession) -> None:
    """An unrecognised entity type is a typo in a money path, not a new feature."""
    with pytest.raises(FinancialLedgerError):
        await record_financial_event(
            ledger_session,
            entity_type="framework",
            entity_id=uuid4(),
            event_type="purchase_initiated",
        )


@pytest.mark.asyncio
async def test_sensitive_metadata_keys_are_stripped(
    ledger_session: AsyncSession,
) -> None:
    """Provider payload fragments must never persist secrets.

    Enforces CLAUDE.md: no tokens, API keys, or webhook payloads in logs. The
    ledger is durable storage, so the rule applies more strictly here.
    """
    transaction_id = uuid4()
    await record_financial_event(
        ledger_session,
        entity_type="transaction",
        entity_id=transaction_id,
        event_type="purchase_failed",
        metadata={
            "provider_event": "charge.failed",
            "authorization_code": "AUTH_secret_value",
            "card_number": "4242424242424242",
        },
    )
    await ledger_session.commit()

    event = await ledger_session.scalar(
        select(FinancialEvent).where(FinancialEvent.entity_id == transaction_id)
    )

    assert event is not None
    assert event.metadata_["provider_event"] == "charge.failed"
    assert "authorization_code" not in event.metadata_
    assert "card_number" not in event.metadata_


@pytest.mark.asyncio
async def test_entity_history_is_append_only_and_ordered(
    ledger_session: AsyncSession,
) -> None:
    """Events written in one transaction stay individually ordered.

    Postgres `now()` returns transaction-start time, so a default of `now()`
    would stamp every event in a commit identically and make the timeline
    unorderable — precisely the case that matters, since a release and its
    payout are written together.
    """
    transaction_id = uuid4()
    for event_type, from_status, to_status in (
        ("purchase_initiated", None, "pending"),
        ("purchase_failed", "pending", "failed"),
        ("purchase_retried", "failed", "pending"),
    ):
        await record_financial_event(
            ledger_session,
            entity_type="transaction",
            entity_id=transaction_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
        )
    await ledger_session.commit()

    events = (
        await ledger_session.scalars(
            select(FinancialEvent)
            .where(FinancialEvent.entity_id == transaction_id)
            .order_by(FinancialEvent.occurred_at)
        )
    ).all()

    assert [event.event_type for event in events] == [
        "purchase_initiated",
        "purchase_failed",
        "purchase_retried",
    ]
    timestamps = [event.occurred_at for event in events]
    assert len(set(timestamps)) == 3, "events in one transaction share a timestamp"
