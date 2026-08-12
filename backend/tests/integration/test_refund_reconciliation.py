"""Integration tests for Paystack refund reconciliation.

Paystack settles refunds asynchronously and tells us the outcome by webhook.
A webhook that never arrives leaves a purchase marked refunded forever with
the money never returned, and nothing else in the system notices. These tests
pin the sweeper that closes that hole by asking Paystack directly.

Maps to: FR-FIN-* (Nigerian corridor refunds).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.integrations import paystack
from app.integrations.paystack import PaystackProviderError, PaystackRefund
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import FinancialEvent, Transaction
from app.modules.financials.reconciliation import reconcile_pending_refunds
from app.modules.frameworks.models import Framework, License
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio

REFUND_ID = "rf_stuck_001"


@pytest.fixture
async def reconciliation_context() -> AsyncIterator[dict[str, Any]]:
    """Clear refund-flow rows before and after each test."""
    await engine.dispose()
    await _reset()
    try:
        yield {}
    finally:
        await _reset()
        await engine.dispose()


async def _reset() -> None:
    """Remove reconciliation rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(FinancialEvent))
        await session.execute(delete(License))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


async def _seed_stuck_refund(
    *,
    requested_ago: timedelta,
    refund_id: str = REFUND_ID,
) -> tuple[UUID, UUID]:
    """Create a refunded purchase whose settlement event never arrived.

    Mirrors what `refund_framework_purchase` leaves behind: the purchase is
    already `refunded` and the licence already `revoked`, with a
    `refund_requested` ledger row carrying the provider's refund id, and no
    settlement event following it.
    """
    async with async_session_factory() as session:
        async with session.begin():
            contributor = User(
                email=f"recon-contributor-{uuid4()}@auracles.space",
                password_hash=hash_password("password"),
                display_name="Recon Contributor",
                email_verified=True,
            )
            operator = User(
                email=f"recon-operator-{uuid4()}@auracles.space",
                password_hash=hash_password("password"),
                display_name="Recon Operator",
                email_verified=True,
            )
            session.add_all([contributor, operator])
            await session.flush()
            framework = Framework(
                contributor_id=contributor.id,
                title="Reconciliation Framework",
                description="Framework used by refund reconciliation tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["refund"],
                price=Decimal("149.00"),
                currency="USD",
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            transaction = Transaction(
                payer_id=operator.id,
                payee_id=contributor.id,
                amount=Decimal("149.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("149.00"),
                transaction_type="purchase",
                status="refunded",
                provider="paystack",
                provider_ref=f"ref_paystack_{uuid4().hex[:8]}",
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            license_row = License(
                framework_id=framework.id,
                operator_id=operator.id,
                transaction_id=transaction.id,
                license_type="single_user",
                status="revoked",
                version_at_grant=framework.version,
                seats_used=1,
                seats_total=1,
            )
            session.add(license_row)
            event = FinancialEvent(
                entity_type="transaction",
                entity_id=transaction.id,
                event_type="refund_requested",
                from_status="completed",
                to_status="refunded",
                amount=Decimal("149.00"),
                currency="USD",
                provider="paystack",
                provider_ref=refund_id,
                actor_id=operator.id,
                occurred_at=datetime.now(UTC) - requested_ago,
            )
            session.add(event)
            await session.flush()
            return transaction.id, license_row.id


async def _event_types(transaction_id: UUID) -> list[str]:
    """Return every ledger event type recorded against a transaction."""
    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(FinancialEvent.event_type).where(
                        FinancialEvent.entity_id == transaction_id
                    )
                )
            )
            .scalars()
            .all()
        )
    return sorted(rows)


async def test_settled_refund_is_closed_out_in_the_ledger(
    reconciliation_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refund Paystack says it processed is recorded as settled."""
    del reconciliation_context
    transaction_id, license_id = await _seed_stuck_refund(
        requested_ago=timedelta(hours=96)
    )

    async def fake_fetch(*, refund_id: str, **_: Any) -> PaystackRefund:
        assert refund_id == REFUND_ID
        return PaystackRefund(id=refund_id, status="processed")

    monkeypatch.setattr(paystack, "fetch_refund", fake_fetch)

    async with async_session_factory() as db:
        async with db.begin():
            result = await reconcile_pending_refunds(db)

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.get(License, license_id)

    assert result == {"checked": 1, "settled": 1, "reversed": 0, "unresolved": 0}
    assert await _event_types(transaction_id) == ["refund_requested", "refund_settled"]
    # A settled refund changes nothing: the state was already correct.
    assert transaction is not None
    assert transaction.status == "refunded"
    assert license_row is not None
    assert license_row.status == "revoked"


async def test_failed_refund_is_reversed_without_the_webhook(
    reconciliation_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refund Paystack declined is reversed exactly as the webhook would.

    This is the case the sweeper exists for: without it the buyer has paid,
    holds nothing, and never gets their money back.
    """
    del reconciliation_context
    transaction_id, license_id = await _seed_stuck_refund(
        requested_ago=timedelta(hours=96)
    )

    async def fake_fetch(*, refund_id: str, **_: Any) -> PaystackRefund:
        return PaystackRefund(id=refund_id, status="failed")

    monkeypatch.setattr(paystack, "fetch_refund", fake_fetch)

    async with async_session_factory() as db:
        async with db.begin():
            result = await reconcile_pending_refunds(db)

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.get(License, license_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "refund_failed")
        )

    assert result == {"checked": 1, "settled": 0, "reversed": 1, "unresolved": 0}
    assert transaction is not None
    assert transaction.status == "completed"
    assert license_row is not None
    assert license_row.status == "active"
    assert audit is not None
    assert await _event_types(transaction_id) == ["refund_failed", "refund_requested"]


async def test_refund_still_pending_at_paystack_is_left_alone(
    reconciliation_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unfinished refund is re-checked later, not guessed at."""
    del reconciliation_context
    transaction_id, _ = await _seed_stuck_refund(requested_ago=timedelta(hours=96))

    async def fake_fetch(*, refund_id: str, **_: Any) -> PaystackRefund:
        return PaystackRefund(id=refund_id, status="pending")

    monkeypatch.setattr(paystack, "fetch_refund", fake_fetch)

    async with async_session_factory() as db:
        async with db.begin():
            result = await reconcile_pending_refunds(db)

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)

    assert result == {"checked": 1, "settled": 0, "reversed": 0, "unresolved": 1}
    assert await _event_types(transaction_id) == ["refund_requested"]
    assert transaction is not None
    assert transaction.status == "refunded"


async def test_recent_refund_is_not_chased(
    reconciliation_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refund inside the settlement window is not queried at all.

    Paystack is still expected to deliver its webhook; chasing every refund
    the moment it is created would spend a provider call on every one.
    """
    del reconciliation_context
    transaction_id, _ = await _seed_stuck_refund(requested_ago=timedelta(hours=1))
    calls: list[str] = []

    async def fake_fetch(*, refund_id: str, **_: Any) -> PaystackRefund:
        calls.append(refund_id)
        return PaystackRefund(id=refund_id, status="failed")

    monkeypatch.setattr(paystack, "fetch_refund", fake_fetch)

    async with async_session_factory() as db:
        async with db.begin():
            result = await reconcile_pending_refunds(db)

    assert result == {"checked": 0, "settled": 0, "reversed": 0, "unresolved": 0}
    assert calls == []
    assert await _event_types(transaction_id) == ["refund_requested"]


async def test_provider_failure_leaves_the_refund_for_the_next_run(
    reconciliation_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable provider must not be read as a verdict.

    Treating a failed lookup as a failed refund would restore access to a
    buyer who has already been paid back.
    """
    del reconciliation_context
    transaction_id, license_id = await _seed_stuck_refund(
        requested_ago=timedelta(hours=96)
    )

    async def fake_fetch(*, refund_id: str, **_: Any) -> PaystackRefund:
        raise PaystackProviderError("Paystack is unreachable.")

    monkeypatch.setattr(paystack, "fetch_refund", fake_fetch)

    async with async_session_factory() as db:
        async with db.begin():
            result = await reconcile_pending_refunds(db)

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.get(License, license_id)

    assert result == {"checked": 1, "settled": 0, "reversed": 0, "unresolved": 1}
    assert await _event_types(transaction_id) == ["refund_requested"]
    assert transaction is not None
    assert transaction.status == "refunded"
    assert license_row is not None
    assert license_row.status == "revoked"


async def test_settled_refund_is_not_reconciled_twice(
    reconciliation_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refund the webhook already closed is invisible to the sweeper."""
    del reconciliation_context
    transaction_id, _ = await _seed_stuck_refund(requested_ago=timedelta(hours=96))
    calls: list[str] = []

    async def fake_fetch(*, refund_id: str, **_: Any) -> PaystackRefund:
        calls.append(refund_id)
        return PaystackRefund(id=refund_id, status="processed")

    monkeypatch.setattr(paystack, "fetch_refund", fake_fetch)

    async with async_session_factory() as db:
        async with db.begin():
            await reconcile_pending_refunds(db)
    async with async_session_factory() as db:
        async with db.begin():
            second = await reconcile_pending_refunds(db)

    assert len(calls) == 1
    assert second == {"checked": 0, "settled": 0, "reversed": 0, "unresolved": 0}
