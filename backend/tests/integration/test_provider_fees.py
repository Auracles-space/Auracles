"""Integration tests for recording Paystack fees as platform costs.

The platform absorbs the provider's fee on every charge, so Treasury can only
report the platform's real earnings if each fee is recorded when the charge
settles. A fee is keyed by the provider reference it was charged on: a
webhook redelivery must not count it twice, while a second, distinct charge
against the same transaction (a double charge) is a second real cost.

Maps to: FR-FIN-* (platform treasury, decision 6 and 12).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.modules.financials.models import ProviderFee
from app.modules.financials.provider_fees import record_provider_fee
from tests.integration.test_paystack_webhooks import (  # noqa: F401
    charge_event,
    create_pending_paystack_milestone_escrow,
    create_pending_paystack_purchase,
    escrow_charge_event,
    paystack_context,
    post_webhook,
)


async def _fees() -> list[ProviderFee]:
    """Return every recorded provider fee."""
    async with async_session_factory() as session:
        return list((await session.execute(select(ProviderFee))).scalars().all())


async def test_purchase_charge_success_records_the_paystack_fee(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
) -> None:
    """A settled purchase charge records Paystack's fee against the transaction."""
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    event = charge_event(
        "charge.success", transaction_id=transaction_id, framework_id=framework_id
    )
    event["data"]["fees"] = 2235
    paystack_context["event"] = event

    response = await post_webhook(client)

    fees = await _fees()
    assert response.json() == {"received": True, "status": "processed"}
    assert len(fees) == 1
    fee = fees[0]
    assert fee.provider == "paystack"
    assert fee.source_type == "transaction"
    assert fee.source_id == transaction_id
    assert fee.amount == Decimal("22.35")
    assert fee.currency == "USD"
    assert fee.provider_ref == event["data"]["reference"]
    assert fee.origin == "webhook"


async def test_escrow_charge_success_records_the_paystack_fee(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
) -> None:
    """Escrow funding charges carry a fee the platform absorbs as well."""
    (
        transaction_id,
        project_id,
        milestone_id,
        _,
    ) = await create_pending_paystack_milestone_escrow()
    event = escrow_charge_event(
        "charge.success",
        transaction_id=transaction_id,
        project_id=project_id,
        milestone_id=milestone_id,
    )
    event["data"]["fees"] = 20000
    paystack_context["event"] = event

    await post_webhook(client)

    fees = await _fees()
    assert len(fees) == 1
    assert fees[0].source_id == transaction_id
    assert fees[0].amount == Decimal("200.00")


async def test_charge_without_fees_records_nothing(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
) -> None:
    """A charge whose payload names no fee (or a zero fee) adds no cost row."""
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    event = charge_event(
        "charge.success", transaction_id=transaction_id, framework_id=framework_id
    )
    event["data"]["fees"] = 0
    paystack_context["event"] = event

    await post_webhook(client)

    assert await _fees() == []


async def test_amount_mismatch_still_records_the_fee(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
) -> None:
    """Paystack keeps its fee even when the charge never settles locally.

    The money reached the Paystack balance, so the fee is a real cost whether
    or not the amount matched the transaction.
    """
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    event = charge_event(
        "charge.success", transaction_id=transaction_id, framework_id=framework_id
    )
    event["data"]["amount"] = 9900
    event["data"]["fees"] = 1485
    paystack_context["event"] = event

    await post_webhook(client)

    fees = await _fees()
    assert len(fees) == 1
    assert fees[0].amount == Decimal("14.85")


async def test_charge_for_an_unknown_transaction_records_nothing(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
) -> None:
    """A fee is only recorded against a Paystack transaction Auracles booked."""
    transaction_id, framework_id, _ = await create_pending_paystack_purchase()
    event = charge_event(
        "charge.success", transaction_id=transaction_id, framework_id=framework_id
    )
    event["data"]["fees"] = 2235
    event["data"]["metadata"] = {"kind": "purchase"}
    paystack_context["event"] = event

    await post_webhook(client)

    assert await _fees() == []


async def test_recording_the_same_fee_twice_keeps_one_row(
    paystack_context: dict[str, Any],  # noqa: F811
) -> None:
    """Recording is idempotent on (provider, source type, provider reference)."""
    transaction_id, _, _ = await create_pending_paystack_purchase()

    for _ in range(2):
        async with async_session_factory() as session:
            async with session.begin():
                await record_provider_fee(
                    session,
                    provider="paystack",
                    source_type="transaction",
                    source_id=transaction_id,
                    amount_minor=2235,
                    currency="NGN",
                    provider_ref="auracles_ref_ngn_001",
                    origin="webhook",
                )

    async with async_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(ProviderFee))
    assert count == 1


async def test_a_second_charge_on_the_same_transaction_is_a_second_fee(
    paystack_context: dict[str, Any],  # noqa: F811
) -> None:
    """A double charge (a distinct reference) is a distinct, real cost."""
    transaction_id, _, _ = await create_pending_paystack_purchase()

    async with async_session_factory() as session:
        async with session.begin():
            for reference in ("auracles_ref_ngn_001", "auracles_ref_ngn_002"):
                await record_provider_fee(
                    session,
                    provider="paystack",
                    source_type="transaction",
                    source_id=transaction_id,
                    amount_minor=2235,
                    currency="NGN",
                    provider_ref=reference,
                    origin="webhook",
                )

    assert len(await _fees()) == 2
