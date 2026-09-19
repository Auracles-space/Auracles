"""Tests for reconciling transfers Paystack holds for a one-time code.

A transfer held for an OTP produces no webhook, and Paystack abandons it about
an hour later — also without a webhook. The payout row is left at
``processing`` forever, which is not merely cosmetic: that status both blocks
the beneficiary from requesting another payout and keeps the amount counted
against their available balance. Without reconciliation a single unanswered
OTP locks a contributor out of their own earnings permanently.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import (
    FinancialEvent,
    Payout,
    PayoutAccount,
    PlatformBankAccount,
    PlatformWithdrawal,
    ProviderFee,
)
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import transfer_reconcile


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
def reconcile_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Reset payout rows and stand in for Paystack's transfer verification."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    state: dict[str, Any] = {
        "status": "abandoned",
        "fee_charged": 0,
        "verified": [],
        "notices": [],
    }

    def cleanup() -> None:
        """Delete payout rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(FinancialEvent))
            session.execute(delete(ProviderFee))
            session.execute(delete(PlatformWithdrawal))
            session.execute(delete(PlatformBankAccount))
            session.execute(delete(Payout))
            session.execute(delete(PayoutAccount))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    async def fake_verify(*, reference: str) -> dict[str, Any]:
        """Report the status the test asked for, recording the lookup."""
        state["verified"].append(reference)
        return {
            "status": state["status"],
            "reference": reference,
            "fee_charged": state["fee_charged"],
        }

    cleanup()
    monkeypatch.setattr(transfer_reconcile.paystack, "verify_transfer", fake_verify)
    monkeypatch.setattr(
        transfer_reconcile,
        "notify_admins_review_pending",
        lambda **kwargs: state["notices"].append(kwargs),
    )
    try:
        yield state
    finally:
        cleanup()
        sync_engine.dispose()


def create_held_payout(
    *,
    awaiting_otp: bool = True,
    status: str = "processing",
    provider: str = "paystack",
    age: timedelta | None = None,
) -> UUID:
    """Create a Paystack payout sitting in the held-for-OTP state."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        contributor = User(
            email=f"held-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Held Contributor",
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
        account = PayoutAccount(
            user_id=contributor.id,
            provider=provider,
            provider_account_id=encrypt_payout_provider_account_id("RCP_held"),
            provider_account_lookup_hash=hash_payout_provider_account_id("RCP_held"),
            account_type="nuban",
            is_default=True,
            verified_at=datetime.now(UTC),
        )
        session.add(account)
        session.flush()
        payout = Payout(
            contributor_id=contributor.id,
            payout_account_id=account.id,
            amount=Decimal("315000.00"),
            currency="NGN",
            commission_deducted=Decimal("0.00"),
            net_amount=Decimal("315000.00"),
            status=status,
            provider_ref=f"payout-{uuid4()}",
            awaiting_otp=awaiting_otp,
            initiated_at=datetime.now(UTC) - (age or timedelta(0)),
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


def test_abandoned_transfer_releases_the_contributor(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """A transfer Paystack abandoned fails the payout so the money is freed.

    While the row sits at `processing` the beneficiary is refused another
    payout and the amount stays counted against their balance, so leaving it
    there locks them out of earnings for a transfer that will never be sent.
    """
    reconcile_context["status"] = "abandoned"
    payout_id = create_held_payout()

    result = transfer_reconcile.reconcile_held_transfers.apply().get()

    payout = _load_payout(payout_id)
    assert payout.status == "failed"
    assert payout.awaiting_otp is False
    assert result["reconciled"] == 1
    # An admin is told, because a payout that died at the provider is not
    # something the contributor can resolve on their own.
    assert reconcile_context["notices"]


def test_transfer_still_awaiting_its_code_is_left_alone(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """A transfer still inside its OTP window keeps waiting.

    Failing it early would refuse money Paystack is still willing to send.
    """
    reconcile_context["status"] = "otp"
    payout_id = create_held_payout()

    result = transfer_reconcile.reconcile_held_transfers.apply().get()

    payout = _load_payout(payout_id)
    assert payout.status == "processing"
    assert payout.awaiting_otp is True
    assert result["reconciled"] == 0


def test_transfer_that_succeeded_without_a_webhook_completes(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """A held transfer that went through is completed even if no webhook came.

    Reconciliation exists because the provider's word is the truth; it has to
    settle the happy path too, or a delivered payout stays "processing".
    """
    reconcile_context["status"] = "success"
    payout_id = create_held_payout()

    transfer_reconcile.reconcile_held_transfers.apply().get()

    payout = _load_payout(payout_id)
    assert payout.status == "completed"
    assert payout.awaiting_otp is False


def test_a_reconciled_success_records_the_provider_fee(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """A payout settled here records its fee, as the webhook path does.

    The platform absorbs Paystack's transfer fee, so treasury subtracts every
    recorded fee from the platform's own money. A payout completed by this
    task rather than by a webhook must therefore cost the same, or the
    platform's available balance reads higher than the money that exists.
    """
    reconcile_context["status"] = "success"
    reconcile_context["fee_charged"] = 10000
    payout_id = create_held_payout()

    transfer_reconcile.reconcile_held_transfers.apply().get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        fee = session.scalar(select(ProviderFee))
        assert fee is not None
        source_type = fee.source_type
        source_id = fee.source_id
        amount = str(fee.amount)
    sync_engine.dispose()

    assert source_type == "payout"
    assert source_id == payout_id
    assert amount == "100.00"


def test_payouts_not_held_for_a_code_are_never_verified(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """Only transfers held for an OTP are checked against the provider.

    Every other payout has a webhook path of its own; verifying them here
    would spend provider calls re-deciding settled money.
    """
    create_held_payout(awaiting_otp=False)

    result = transfer_reconcile.reconcile_held_transfers.apply().get()

    assert reconcile_context["verified"] == []
    assert result["checked"] == 0


def create_held_withdrawal() -> str:
    """Create a platform withdrawal sitting in the held-for-OTP state."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    reference = f"platform-withdrawal-{uuid4()}"
    with session_factory() as session:
        admin = User(
            email=f"withdrawal-admin-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Treasury Admin",
            email_verified=True,
        )
        session.add(admin)
        session.flush()
        bank_account = PlatformBankAccount(
            provider="paystack",
            bank_code="070",
            bank_name="Fidelity Bank",
            account_last4="5047",
            account_name="Auracles platform",
            recipient_code_encrypted=encrypt_payout_provider_account_id("RCP_platform"),
            usable_from=datetime.now(UTC),
            created_by=admin.id,
        )
        session.add(bank_account)
        session.flush()
        session.add(
            PlatformWithdrawal(
                bank_account_id=bank_account.id,
                amount=Decimal("10000.00"),
                currency="NGN",
                status="processing",
                provider_ref=reference,
                awaiting_otp=True,
                requested_by=admin.id,
            )
        )
        session.commit()
    sync_engine.dispose()
    return reference


def test_abandoned_platform_withdrawal_is_settled_too(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """A platform withdrawal strands exactly like a payout, so it is covered.

    It carries the same `awaiting_otp` flag and the same silence from the
    provider; leaving it out would fix the contributor's money and quietly
    keep the platform's own withdrawal stuck at processing forever.
    """
    reconcile_context["status"] = "abandoned"
    reference = create_held_withdrawal()

    result = transfer_reconcile.reconcile_held_transfers.apply().get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        withdrawal = session.scalar(
            select(PlatformWithdrawal).where(
                PlatformWithdrawal.provider_ref == reference
            )
        )
        assert withdrawal is not None
        status = withdrawal.status
        awaiting = withdrawal.awaiting_otp
    sync_engine.dispose()

    assert status == "failed"
    assert awaiting is False
    assert result["reconciled"] == 1


def test_a_processing_payout_whose_webhook_never_came_is_settled(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """A transfer left at `processing` by a lost webhook is asked about.

    Only OTP-held transfers were checked, but the OTP case is one way a
    webhook fails to arrive, not the only one: a dropped delivery, a refused
    signature or an outage at our end strands the payout identically, and the
    beneficiary is blocked from requesting again the whole time.
    """
    reconcile_context["status"] = "success"
    payout_id = create_held_payout(awaiting_otp=False, age=timedelta(hours=2))

    result = transfer_reconcile.reconcile_held_transfers.apply().get()

    payout = _load_payout(payout_id)
    assert payout.status == "completed"
    assert result["reconciled"] == 1


def test_a_transfer_still_within_its_settling_window_is_left_alone(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """A payout created moments ago is not second-guessed.

    Most transfers settle in seconds and their webhook follows immediately.
    Verifying every one of them would spend a provider call per payout to
    re-decide money that is about to settle itself.
    """
    create_held_payout(awaiting_otp=False)

    result = transfer_reconcile.reconcile_held_transfers.apply().get()

    assert reconcile_context["verified"] == []
    assert result["checked"] == 0


def test_a_stripe_payout_is_never_asked_about_at_paystack(
    migrated_database: None,
    reconcile_context: dict[str, Any],
) -> None:
    """Only Paystack payouts are verified against Paystack.

    A Stripe transfer id means nothing to Paystack, so asking would fail on
    every run — and if it somehow answered, the answer would be about
    somebody else's transfer.
    """
    create_held_payout(awaiting_otp=False, provider="stripe", age=timedelta(hours=2))

    result = transfer_reconcile.reconcile_held_transfers.apply().get()

    assert reconcile_context["verified"] == []
    assert result["checked"] == 0
