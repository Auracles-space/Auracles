"""Tests for Contributor payout transfer processing.

The task is the only place a Contributor's money leaves the platform, so the
rail is chosen from the payout account's own provider rather than a global
setting: a Stripe-booked account must never be paid through Paystack, or the
transfer would be addressed to a recipient code the other provider never issued.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import (
    encrypt_payout_provider_account_id,
    hash_password,
    hash_payout_provider_account_id,
)
from app.integrations.paystack import PaystackProviderError
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Payout, PayoutAccount
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import payouts


class FakeStripeTransfer:
    """Stand-in for a Stripe transfer result."""

    def __init__(self, transfer_id: str) -> None:
        """Store the provider transfer id."""
        self.id = transfer_id
        self.status = FakePaystackTransfer.next_status


class FakePaystackTransfer:
    """Stand-in for a Paystack transfer result."""

    # Status the next fake transfer reports; tests set "otp" to simulate an
    # account that holds every transfer for a one-time code.
    next_status = "pending"

    def __init__(self, transfer_id: str, transfer_code: str) -> None:
        """Store the provider transfer id, status, and transfer code."""
        self.id = transfer_id
        self.status = FakePaystackTransfer.next_status
        self.transfer_code = transfer_code


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure payout tables exist for task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
def payout_task_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, list[dict[str, Any]]]]:
    """Reset payout rows and replace both providers' transfer calls."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    calls: dict[str, list[dict[str, Any]]] = {"stripe": [], "paystack": []}

    def cleanup() -> None:
        """Delete payout rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(Payout))
            session.execute(delete(PayoutAccount))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    async def fake_stripe_transfer(
        *,
        amount: Decimal,
        currency: str,
        destination_account_id: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> FakeStripeTransfer:
        """Record a Stripe transfer."""
        calls["stripe"].append(
            {
                "amount": amount,
                "currency": currency,
                "destination_account_id": destination_account_id,
                "metadata": metadata,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeTransfer("tr_contributor_123")

    async def fake_paystack_transfer(
        *,
        amount: Decimal,
        currency: str,
        recipient: str,
        reason: str,
        reference: str,
    ) -> FakePaystackTransfer:
        """Record a Paystack transfer."""
        calls["paystack"].append(
            {
                "amount": amount,
                "currency": currency,
                "recipient": recipient,
                "reason": reason,
                "reference": reference,
            }
        )
        return FakePaystackTransfer("998877", "TRF_contributor_123")

    notifications: list[dict[str, Any]] = []
    calls["notifications"] = notifications
    FakePaystackTransfer.next_status = "pending"
    cleanup()
    monkeypatch.setattr(
        payouts,
        "notify_admins_review_pending",
        lambda **kwargs: notifications.append(kwargs),
    )
    monkeypatch.setattr(payouts.stripe, "create_transfer", fake_stripe_transfer)
    monkeypatch.setattr(payouts.paystack, "initiate_transfer", fake_paystack_transfer)
    try:
        yield calls
    finally:
        cleanup()
        sync_engine.dispose()


def create_pending_payout(*, provider: str, provider_account_id: str) -> UUID:
    """Create a pending Contributor payout on the given rail."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        contributor = User(
            email=f"payout-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Payout Contributor",
            email_verified=True,
            kyc_status="verified",
        )
        session.add(contributor)
        session.flush()
        session.add(
            UserRole(
                user_id=contributor.id,
                role="contributor",
                approved_at=datetime.now(UTC),
            )
        )
        payout_account = PayoutAccount(
            user_id=contributor.id,
            provider=provider,
            provider_account_id=encrypt_payout_provider_account_id(provider_account_id),
            provider_account_lookup_hash=hash_payout_provider_account_id(
                provider_account_id
            ),
            account_type="nuban" if provider == "paystack" else "express",
            is_default=True,
            verified_at=datetime.now(UTC),
        )
        session.add(payout_account)
        session.flush()
        payout = Payout(
            contributor_id=contributor.id,
            payout_account_id=payout_account.id,
            amount=Decimal("100.00"),
            currency="USD",
            commission_deducted=Decimal("15.00"),
            net_amount=Decimal("85.00"),
            status="pending",
        )
        session.add(payout)
        session.commit()
        payout_id: UUID = payout.id
    sync_engine.dispose()
    return payout_id


def _load_payout(payout_id: UUID) -> Payout:
    """Read a payout row back after task execution."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        payout = session.scalar(select(Payout).where(Payout.id == payout_id))
        assert payout is not None
        session.expunge(payout)
    sync_engine.dispose()
    return payout


def test_stripe_payout_creates_a_connect_transfer(
    migrated_database: None,
    payout_task_context: dict[str, list[dict[str, Any]]],
) -> None:
    """A Stripe-booked payout still settles through Stripe Connect."""
    payout_id = create_pending_payout(
        provider="stripe",
        provider_account_id="acct_contributor_1",
    )

    result = payouts.process_payout.apply(args=[str(payout_id)]).get()

    assert result["status"] == "processing"
    assert result["provider_ref"] == "tr_contributor_123"
    assert payout_task_context["paystack"] == []
    assert len(payout_task_context["stripe"]) == 1
    stripe_call = payout_task_context["stripe"][0]
    assert stripe_call["destination_account_id"] == "acct_contributor_1"
    assert stripe_call["amount"] == Decimal("85.00")


def test_paystack_payout_transfers_to_the_registered_recipient(
    migrated_database: None,
    payout_task_context: dict[str, list[dict[str, Any]]],
) -> None:
    """A Paystack-booked payout transfers to its NUBAN recipient code.

    The transfer carries our own reference rather than Paystack's id, because
    that reference is both the idempotency key for a retried transfer and the
    only thing the `transfer.success` webhook can be matched back to.
    """
    payout_id = create_pending_payout(
        provider="paystack",
        provider_account_id="RCP_contributor_1",
    )

    result = payouts.process_payout.apply(args=[str(payout_id)]).get()

    assert result["status"] == "processing"
    assert payout_task_context["stripe"] == []
    assert len(payout_task_context["paystack"]) == 1
    paystack_call = payout_task_context["paystack"][0]
    assert paystack_call["recipient"] == "RCP_contributor_1"
    assert paystack_call["amount"] == Decimal("85.00")
    assert paystack_call["reference"] == f"payout-{payout_id}"
    # The stored ref must be the reference, not the provider id, or the
    # webhook that settles this payout will never find its row.
    assert _load_payout(payout_id).provider_ref == f"payout-{payout_id}"


def test_paystack_payout_records_the_rail_in_its_audit_row(
    migrated_database: None,
    payout_task_context: dict[str, list[dict[str, Any]]],
) -> None:
    """The audit trail must name the rail money actually left on."""
    payout_id = create_pending_payout(
        provider="paystack",
        provider_account_id="RCP_contributor_2",
    )

    payouts.process_payout.apply(args=[str(payout_id)]).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "payout_processing")
        )
        assert audit is not None
        assert audit.metadata_["provider"] == "paystack"
    sync_engine.dispose()


def test_processing_a_payout_twice_does_not_transfer_twice(
    migrated_database: None,
    payout_task_context: dict[str, list[dict[str, Any]]],
) -> None:
    """Celery retries must not send a Contributor's money a second time."""
    payout_id = create_pending_payout(
        provider="paystack",
        provider_account_id="RCP_contributor_3",
    )

    first = payouts.process_payout.apply(args=[str(payout_id)]).get()
    second = payouts.process_payout.apply(args=[str(payout_id)]).get()

    assert first["provider_ref"] == second["provider_ref"]
    assert len(payout_task_context["paystack"]) == 1


def test_paystack_holding_a_payout_for_otp_alerts_admins(
    migrated_database: None,
    payout_task_context: dict[str, list[dict[str, Any]]],
) -> None:
    """A transfer Paystack holds for an OTP never moves on its own.

    With transfer OTP switched on in Paystack, every payout stops at `otp`
    and no webhook follows, so admins must be told to finalize it or turn the
    setting off.
    """
    FakePaystackTransfer.next_status = "otp"
    payout_id = create_pending_payout(
        provider="paystack",
        provider_account_id="RCP_contributor_1",
    )

    payouts.process_payout.apply(args=[str(payout_id)]).get()

    notices = payout_task_context["notifications"]
    assert [notice["domain"] for notice in notices] == ["paystack_transfer_otp"]
    assert notices[0]["target_id"] == payout_id
    assert "OTP" in notices[0]["body"]
    payout = _load_payout(payout_id)
    assert payout.status == "processing"
    assert payout.awaiting_otp is True


def test_a_payout_paystack_sends_straight_away_raises_no_otp_alert(
    migrated_database: None,
    payout_task_context: dict[str, list[dict[str, Any]]],
) -> None:
    """Only a held transfer alerts."""
    payout_id = create_pending_payout(
        provider="paystack",
        provider_account_id="RCP_contributor_1",
    )

    payouts.process_payout.apply(args=[str(payout_id)]).get()

    assert payout_task_context["notifications"] == []
    assert _load_payout(payout_id).awaiting_otp is False


def test_a_payout_the_balance_cannot_fund_says_so_and_stays_pending(
    migrated_database: None,
    payout_task_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shortfall leaves the payout waiting with a reason, not silently stuck.

    The hourly sweeper already retries a pending payout until it goes
    through, so the money is never lost — but the beneficiary saw `pending`
    for days with their balance locked and nothing to explain it. The reason
    is what turns an unexplained wait into a visible one.
    """

    async def refuse_for_balance(**_: Any) -> None:
        """Refuse the transfer the way Paystack refuses an unfunded one."""
        raise PaystackProviderError(
            "Paystack returned 400.",
            message="Your balance is not enough to fulfil this request",
            status_code=400,
        )

    monkeypatch.setattr(payouts.paystack, "initiate_transfer", refuse_for_balance)
    payout_id = create_pending_payout(
        provider="paystack", provider_account_id="RCP_balance"
    )

    result = payouts.process_payout.apply(args=[str(payout_id)]).get()

    payout = _load_payout(payout_id)
    assert payout.status == "pending"
    assert payout.delay_reason == "insufficient_platform_balance"
    assert payout.provider_ref is None
    assert result["status"] == "deferred"
    # Admins are told, because only they can act on a platform shortfall.
    assert payout_task_context["notifications"]


def test_an_unrelated_refusal_still_fails_loudly(
    migrated_database: None,
    payout_task_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal retrying cannot fix must not be dressed up as a funding wait.

    Deferring it would leave a broken payout retrying hourly forever while
    telling the beneficiary to wait for money that was never the problem.
    """

    async def refuse_outright(**_: Any) -> None:
        """Refuse for a cause no retry will clear."""
        raise PaystackProviderError(
            "Paystack returned 400.",
            message="Recipient specified does not exist",
            status_code=400,
        )

    monkeypatch.setattr(payouts.paystack, "initiate_transfer", refuse_outright)
    payout_id = create_pending_payout(
        provider="paystack", provider_account_id="RCP_broken"
    )

    with pytest.raises(PaystackProviderError):
        payouts.process_payout.apply(args=[str(payout_id)]).get()

    payout = _load_payout(payout_id)
    assert payout.delay_reason is None


def test_a_retry_that_succeeds_drops_the_waiting_reason(
    migrated_database: None,
    payout_task_context: dict[str, Any],
) -> None:
    """Once the transfer is accepted the payout no longer explains a wait.

    The sweeper retries a deferred payout hourly, so the run that finally
    succeeds is the one that has to clear the reason — otherwise a paid
    contributor is still told the platform balance is short.
    """
    payout_id = create_pending_payout(
        provider="paystack", provider_account_id="RCP_recovered"
    )
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    with sessionmaker(sync_engine)() as session:
        waiting = session.get(Payout, payout_id)
        assert waiting is not None
        waiting.delay_reason = "insufficient_platform_balance"
        session.commit()
    sync_engine.dispose()

    payouts.process_payout.apply(args=[str(payout_id)]).get()

    payout = _load_payout(payout_id)
    assert payout.status == "processing"
    assert payout.delay_reason is None
