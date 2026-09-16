"""Integration tests for Paystack transfer webhooks on platform withdrawals.

The transfer webhook is the only authoritative word on whether platform money
reached the bank. Success completes the withdrawal and records Paystack's
transfer fee as a platform cost; failure or reversal fails it, which returns
the amount to withdrawable. Every outcome is announced to all admins.

Maps to: platform treasury design §Withdrawal, decisions 6 and 8.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.modules.financials import platform_withdrawals
from app.modules.financials.models import PlatformWithdrawal, ProviderFee
from app.shared.models.audit_log import AuditLog
from tests.integration.test_paystack_webhooks import (  # noqa: F401
    create_processing_paystack_payout,
    paystack_context,
    post_webhook,
    transfer_event,
)
from tests.integration.test_platform_withdrawal_task import _withdrawal


async def _processing_withdrawal() -> tuple[UUID, str]:
    """Create a withdrawal Paystack has accepted, returning id and reference."""
    withdrawal_id = await _withdrawal(status="processing")
    return withdrawal_id, f"platform-withdrawal-{withdrawal_id}"


def _capture_notifications(monkeypatch: Any) -> list[dict[str, Any]]:
    """Replace admin notifications with a list recorder."""
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        platform_withdrawals,
        "notify_admins_review_pending",
        lambda **kwargs: captured.append(kwargs),
    )
    return captured


async def _load(withdrawal_id: UUID) -> PlatformWithdrawal:
    """Reload a withdrawal row."""
    async with async_session_factory() as session:
        withdrawal = await session.get(PlatformWithdrawal, withdrawal_id)
        assert withdrawal is not None
        return withdrawal


async def test_transfer_success_completes_the_withdrawal_and_records_the_fee(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Success is terminal; Paystack's transfer fee becomes a platform cost."""
    notifications = _capture_notifications(monkeypatch)
    withdrawal_id, reference = await _processing_withdrawal()
    event = transfer_event("transfer.success", reference=reference)
    event["data"]["currency"] = "NGN"
    event["data"]["fee_charged"] = 5375
    paystack_context["event"] = event

    response = await post_webhook(client)

    assert response.json()["status"] == "processed"
    withdrawal = await _load(withdrawal_id)
    assert withdrawal.status == "completed"
    assert withdrawal.completed_at is not None
    async with async_session_factory() as session:
        fee = await session.scalar(select(ProviderFee))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "platform_withdrawal_completed")
        )
    assert fee is not None
    assert fee.source_type == "platform_withdrawal"
    assert fee.source_id == withdrawal_id
    assert str(fee.amount) == "53.75"
    assert audit is not None
    assert [n["domain"] for n in notifications] == ["platform_withdrawal_completed"]


async def test_transfer_failed_fails_the_withdrawal_with_the_reason(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """A failed transfer releases the amount and tells admins why."""
    notifications = _capture_notifications(monkeypatch)
    withdrawal_id, reference = await _processing_withdrawal()
    event = transfer_event(
        "transfer.failed", reference=reference, reason="Account is dormant"
    )
    paystack_context["event"] = event

    await post_webhook(client)

    withdrawal = await _load(withdrawal_id)
    assert withdrawal.status == "failed"
    assert withdrawal.failed_at is not None
    assert withdrawal.failure_reason == "Account is dormant"
    assert [n["domain"] for n in notifications] == ["platform_withdrawal_failed"]


async def test_reversal_after_success_fails_the_withdrawal(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """A reversed transfer put the money back, so the withdrawal no longer counts."""
    _capture_notifications(monkeypatch)
    withdrawal_id, reference = await _processing_withdrawal()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(PlatformWithdrawal)
                .where(PlatformWithdrawal.id == withdrawal_id)
                .values(status="completed")
            )
    paystack_context["event"] = transfer_event(
        "transfer.reversed", reference=reference, reason="Reversed by bank"
    )

    await post_webhook(client)

    assert (await _load(withdrawal_id)).status == "failed"


async def test_success_for_a_withdrawal_the_task_had_failed_completes_it(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """If money actually left after the task gave up, the webhook wins.

    Counting it as failed would offer the same money for withdrawal again.
    """
    _capture_notifications(monkeypatch)
    withdrawal_id = await _withdrawal(status="failed")
    paystack_context["event"] = transfer_event(
        "transfer.success", reference=f"platform-withdrawal-{withdrawal_id}"
    )

    await post_webhook(client)

    assert (await _load(withdrawal_id)).status == "completed"


async def test_user_payout_transfer_fee_is_recorded(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
) -> None:
    """Contributor payout transfer fees are platform costs too."""
    payout_id, reference = await create_processing_paystack_payout()
    event = transfer_event("transfer.success", reference=reference)
    event["data"]["fee_charged"] = 1075
    paystack_context["event"] = event

    await post_webhook(client)

    async with async_session_factory() as session:
        fee = await session.scalar(select(ProviderFee))
    assert fee is not None
    assert fee.source_type == "payout"
    assert fee.source_id == payout_id
    assert str(fee.amount) == "10.75"


async def test_settling_a_withdrawal_clears_its_otp_flag(
    client: AsyncClient,
    paystack_context: dict[str, Any],  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Once Paystack reports the outcome, the transfer is no longer held."""
    _capture_notifications(monkeypatch)
    withdrawal_id, reference = await _processing_withdrawal()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                update(PlatformWithdrawal)
                .where(PlatformWithdrawal.id == withdrawal_id)
                .values(awaiting_otp=True)
            )
    paystack_context["event"] = transfer_event("transfer.success", reference=reference)

    await post_webhook(client)

    withdrawal = await _load(withdrawal_id)
    assert withdrawal.status == "completed"
    assert withdrawal.awaiting_otp is False
