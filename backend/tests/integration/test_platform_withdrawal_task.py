"""Integration tests for the Celery task that sends a platform withdrawal.

The task is the only code that asks Paystack to move the platform's money, so
it must send exactly the recorded amount to the recorded account under our
own reference, never send twice, and mark the withdrawal failed (returning
the amount to withdrawable) when Paystack will not accept the transfer.

Maps to: platform treasury design §Withdrawal, decision 8.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.core.security import encrypt_payout_provider_account_id
from app.integrations.paystack import PaystackTransfer
from app.modules.auth.models import User
from app.modules.financials.models import PlatformBankAccount, PlatformWithdrawal
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import platform_withdrawals as task_module
from tests.support.db_cleanup import clear_identity_state_async


@pytest.fixture
async def task_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install Paystack transfer and notification doubles."""
    await engine.dispose()
    async with async_session_factory() as session:
        await clear_identity_state_async(session)
        await session.commit()
    context: dict[str, Any] = {
        "transfers": [],
        "notifications": [],
        "status": "pending",
    }

    async def fake_initiate_transfer(**kwargs: Any) -> PaystackTransfer:
        """Record the transfer request and report the configured status."""
        context["transfers"].append(kwargs)
        return PaystackTransfer(id="1", status=context["status"], transfer_code="TRF_1")

    def fake_notify(**kwargs: Any) -> None:
        """Capture admin notifications."""
        context["notifications"].append(kwargs)

    monkeypatch.setattr(
        task_module.paystack, "initiate_transfer", fake_initiate_transfer
    )
    monkeypatch.setattr(task_module, "notify_admins_review_pending", fake_notify)
    try:
        yield context
    finally:
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()
        await engine.dispose()


async def _withdrawal(status: str = "pending") -> UUID:
    """Insert a super-admin, a usable bank account and one withdrawal."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"task-admin-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Task Admin",
                email_verified=True,
                is_superadmin=True,
            )
            session.add(user)
            await session.flush()
            account = PlatformBankAccount(
                provider="paystack",
                bank_code="058",
                bank_name="Guaranty Trust Bank",
                account_last4="6789",
                account_name="AURACLES TECHNOLOGIES LTD",
                recipient_code_encrypted=encrypt_payout_provider_account_id(
                    "RCP_platform"
                ),
                usable_from=datetime.now(UTC) - timedelta(days=1),
                created_by=user.id,
            )
            session.add(account)
            await session.flush()
            withdrawal_id = uuid4()
            session.add(
                PlatformWithdrawal(
                    id=withdrawal_id,
                    bank_account_id=account.id,
                    amount=Decimal("10000.00"),
                    currency="NGN",
                    status=status,
                    provider_ref=f"platform-withdrawal-{withdrawal_id}",
                    requested_by=user.id,
                )
            )
        return withdrawal_id


async def _load(withdrawal_id: UUID) -> PlatformWithdrawal:
    """Reload a withdrawal row."""
    async with async_session_factory() as session:
        withdrawal = await session.get(PlatformWithdrawal, withdrawal_id)
        assert withdrawal is not None
        return withdrawal


async def test_pending_withdrawal_is_sent_to_the_platform_recipient(
    task_context: dict[str, Any],
) -> None:
    """The transfer carries the recorded amount, recipient and our reference."""
    withdrawal_id = await _withdrawal()

    result = await task_module._send_platform_withdrawal(str(withdrawal_id))

    assert result["status"] == "processing"
    assert task_context["transfers"] == [
        {
            "amount": Decimal("10000.00"),
            "currency": "NGN",
            "recipient": "RCP_platform",
            "reason": "Auracles platform withdrawal",
            "reference": f"platform-withdrawal-{withdrawal_id}",
        }
    ]
    assert (await _load(withdrawal_id)).status == "processing"
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "platform_withdrawal_processing")
        )
    assert audit is not None


async def test_a_withdrawal_already_sent_is_never_sent_again(
    task_context: dict[str, Any],
) -> None:
    """A retry after the transfer was accepted does nothing."""
    withdrawal_id = await _withdrawal(status="processing")

    result = await task_module._send_platform_withdrawal(str(withdrawal_id))

    assert result["status"] == "processing"
    assert task_context["transfers"] == []


async def test_initiation_failure_fails_the_withdrawal_and_alerts_admins(
    task_context: dict[str, Any],
) -> None:
    """After retries run out the withdrawal fails and its amount is released."""
    withdrawal_id = await _withdrawal()

    await task_module._fail_platform_withdrawal_initiation(
        str(withdrawal_id), "Paystack returned 400."
    )

    withdrawal = await _load(withdrawal_id)
    assert withdrawal.status == "failed"
    assert withdrawal.failed_at is not None
    assert withdrawal.failure_reason == "Paystack did not accept the transfer."
    assert task_context["notifications"][0]["domain"] == "platform_withdrawal_failed"


async def test_initiation_failure_leaves_a_sent_withdrawal_alone(
    task_context: dict[str, Any],
) -> None:
    """Only a still-pending withdrawal can be failed by the task."""
    withdrawal_id = await _withdrawal(status="processing")

    await task_module._fail_platform_withdrawal_initiation(
        str(withdrawal_id), "late error"
    )

    assert (await _load(withdrawal_id)).status == "processing"
    assert task_context["notifications"] == []


async def test_a_withdrawal_held_for_otp_is_flagged_and_alerts_admins(
    task_context: dict[str, Any],
) -> None:
    """Paystack holding the transfer for an OTP is visible, not silent."""
    withdrawal_id = await _withdrawal()
    task_context["status"] = "otp"

    await task_module._send_platform_withdrawal(str(withdrawal_id))

    withdrawal = await _load(withdrawal_id)
    assert withdrawal.status == "processing"
    assert withdrawal.awaiting_otp is True
    assert [n["domain"] for n in task_context["notifications"]] == [
        "paystack_transfer_otp"
    ]


async def test_a_withdrawal_sent_straight_away_is_not_flagged(
    task_context: dict[str, Any],
) -> None:
    """A transfer Paystack accepted without an OTP raises nothing."""
    withdrawal_id = await _withdrawal()

    await task_module._send_platform_withdrawal(str(withdrawal_id))

    assert (await _load(withdrawal_id)).awaiting_otp is False
    assert task_context["notifications"] == []
