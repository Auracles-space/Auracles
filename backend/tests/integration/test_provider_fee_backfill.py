"""Integration tests for backfilling Paystack fees on past charges.

Fees were not recorded before slice 1, so Treasury would overstate the
platform's money for every earlier charge. The backfill looks each settled
Paystack charge up once, records its fee as a backfilled cost dated when the
charge was paid, skips charges that already have a fee, survives individual
lookup failures, and is safe to run again.

Maps to: platform treasury design, decision 7.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.integrations.paystack import PaystackProviderError, PaystackTransaction
from app.main import app
from app.modules.financials import provider_fee_backfill
from app.modules.financials.models import ProviderFee, Transaction
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.integration.test_admin_config import FakeRedis
from tests.integration.test_admin_treasury_summary import _reset, _user
from tests.integration.test_admin_treasury_withdrawals import _admin, _headers

PATH = "/v1/admin/treasury/fee-backfill"
PAID_AT = datetime(2026, 8, 1, 10, 15, tzinfo=UTC)


@pytest.fixture
async def backfill_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install a Paystack lookup double with no rate-limit sleep."""
    await engine.dispose()
    await _reset()
    context: dict[str, Any] = {"lookups": [], "failing": set(), "fees": {}}

    async def fake_fetch_transaction(
        *, reference: str, **_: Any
    ) -> PaystackTransaction:
        """Return the configured fee, or fail for references marked failing."""
        context["lookups"].append(reference)
        if reference in context["failing"]:
            raise PaystackProviderError("Paystack returned 500.")
        return PaystackTransaction(
            reference=reference,
            status="success",
            currency="NGN",
            fees_minor=context["fees"].get(reference, 15000),
            paid_at=PAID_AT,
        )

    async def no_sleep(_: float) -> None:
        """Skip the rate-limit pause."""

    monkeypatch.setattr(
        provider_fee_backfill.paystack, "fetch_transaction", fake_fetch_transaction
    )
    monkeypatch.setattr(provider_fee_backfill.asyncio, "sleep", no_sleep)
    try:
        yield context
    finally:
        await _reset()
        await engine.dispose()


async def _transaction(
    *,
    reference: str,
    status: str = "completed",
    provider: str = "paystack",
    transaction_type: str = "purchase",
) -> UUID:
    """Insert one charge transaction."""
    payer_id = await _user("operator")
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=payer_id,
                amount=Decimal("10000.00"),
                currency="NGN",
                platform_commission=Decimal("1500.00"),
                net_amount=Decimal("8500.00"),
                transaction_type=transaction_type,
                status=status,
                provider=provider,
                provider_ref=reference,
                ref_id=uuid4(),
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id


async def _fees() -> list[ProviderFee]:
    """Return every recorded fee."""
    async with async_session_factory() as session:
        return list((await session.execute(select(ProviderFee))).scalars())


async def test_backfill_records_fees_for_settled_paystack_charges(
    backfill_context: dict[str, Any],
) -> None:
    """Completed and refunded Paystack charges get a backfilled fee; others do not."""
    completed_id = await _transaction(reference="bf-completed")
    refunded_id = await _transaction(reference="bf-refunded", status="refunded")
    await _transaction(reference="bf-pending", status="pending")
    await _transaction(reference="pi_stripe", provider="stripe")
    await _transaction(
        reference="bf-refund-row", status="refunded", transaction_type="refund"
    )

    result = await provider_fee_backfill.backfill_paystack_fees()

    assert sorted(backfill_context["lookups"]) == ["bf-completed", "bf-refunded"]
    assert result == {"checked": 2, "recorded": 2, "failed": 0}
    fees = {fee.source_id: fee for fee in await _fees()}
    assert set(fees) == {completed_id, refunded_id}
    fee = fees[completed_id]
    assert fee.amount == Decimal("150.00")
    assert fee.origin == "backfill"
    assert fee.occurred_at == PAID_AT


async def test_backfill_skips_charges_that_already_have_a_fee(
    backfill_context: dict[str, Any],
) -> None:
    """A charge whose fee the webhook recorded is never looked up."""
    transaction_id = await _transaction(reference="bf-known")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                ProviderFee(
                    provider="paystack",
                    source_type="transaction",
                    source_id=transaction_id,
                    amount=Decimal("150.00"),
                    currency="NGN",
                    provider_ref="bf-known",
                    origin="webhook",
                )
            )

    result = await provider_fee_backfill.backfill_paystack_fees()

    assert backfill_context["lookups"] == []
    assert result == {"checked": 0, "recorded": 0, "failed": 0}


async def test_split_rows_sharing_a_charge_are_looked_up_once(
    backfill_context: dict[str, Any],
) -> None:
    """An escrow split's release row reuses the charge reference; one fee only."""
    await _transaction(reference="bf-split", status="refunded")
    await _transaction(reference="bf-split")

    result = await provider_fee_backfill.backfill_paystack_fees()

    assert backfill_context["lookups"] == ["bf-split"]
    assert result["recorded"] == 1
    assert len(await _fees()) == 1


async def test_a_failed_lookup_does_not_stop_the_run(
    backfill_context: dict[str, Any],
) -> None:
    """One provider error is counted and the rest still backfill; a rerun retries it."""
    await _transaction(reference="bf-broken")
    await _transaction(reference="bf-fine")
    backfill_context["failing"] = {"bf-broken"}

    first = await provider_fee_backfill.backfill_paystack_fees()
    backfill_context["failing"] = set()
    backfill_context["lookups"].clear()
    second = await provider_fee_backfill.backfill_paystack_fees()

    assert first == {"checked": 2, "recorded": 1, "failed": 1}
    assert backfill_context["lookups"] == ["bf-broken"]
    assert second == {"checked": 1, "recorded": 1, "failed": 0}


async def test_a_charge_with_no_fee_is_checked_but_not_recorded(
    backfill_context: dict[str, Any],
) -> None:
    """Paystack reporting no fee records nothing."""
    await _transaction(reference="bf-free")
    backfill_context["fees"] = {"bf-free": None}

    result = await provider_fee_backfill.backfill_paystack_fees()

    assert result == {"checked": 1, "recorded": 0, "failed": 0}
    assert await _fees() == []


async def test_only_the_superadmin_with_step_up_queues_the_backfill(
    client: AsyncClient,
    backfill_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backfill is queued, audited, and refused to other admins."""
    queued: list[str] = []

    class FakeTask:
        """Capture the dispatch."""

        def delay(self, actor_id: str) -> None:
            """Record the requesting super-admin."""
            queued.append(actor_id)

    fake_redis = FakeRedis()

    async def override_redis() -> FakeRedis:
        """Return the Redis test double."""
        return fake_redis

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(provider_fee_backfill, "backfill_provider_fees", FakeTask())
    try:
        admin_id = await _admin(superadmin=False)
        superadmin_id = await _admin(superadmin=True)
        await open_step_up_window(fake_redis, admin_id)
        await open_step_up_window(fake_redis, superadmin_id)

        by_admin = await client.post(PATH, headers=_headers(admin_id))
        by_superadmin = await client.post(PATH, headers=_headers(superadmin_id))
    finally:
        app.dependency_overrides.pop(get_redis, None)

    assert by_admin.status_code == 403
    assert by_superadmin.status_code == 202
    assert by_superadmin.json() == {"status": "queued"}
    assert queued == [str(superadmin_id)]
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "provider_fee_backfill_requested")
        )
    assert audit is not None
    assert audit.actor_id == superadmin_id
