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
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Payout, PayoutAccount
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import payouts


class FakeStripeTransfer:
    """Stand-in for a Stripe transfer result."""

    def __init__(self, transfer_id: str) -> None:
        """Store the provider transfer id."""
        self.id = transfer_id
        self.status = "pending"


class FakePaystackTransfer:
    """Stand-in for a Paystack transfer result."""

    def __init__(self, transfer_id: str, transfer_code: str) -> None:
        """Store the provider transfer id, status, and transfer code."""
        self.id = transfer_id
        self.status = "pending"
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

    cleanup()
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
            provider_account_id=encrypt_payout_provider_account_id(
                provider_account_id
            ),
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
