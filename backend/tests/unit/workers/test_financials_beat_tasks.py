"""Tests for scheduled financial reconciliation Celery tasks.

Runs through the Celery task rather than the service so the wiring is covered:
task registration, session handling, and the Beat entry pointing at it. The
outcome logic itself is pinned in tests/integration/test_refund_reconciliation.
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
from app.integrations import paystack
from app.integrations.paystack import PaystackRefund
from app.integrations.stripe import StripeRefund
from app.modules.auth.models import User, UserRole
from app.modules.financials import balance_floor, refund_intents
from app.modules.financials.models import (
    Escrow,
    FinancialEvent,
    Payout,
    PayoutAccount,
    Transaction,
)
from app.modules.frameworks.models import Framework, License
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog
from app.workers.beat_schedule import BEAT_SCHEDULE
from app.workers.tasks import financials_beat

REFUND_ID = "rf_beat_001"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for Beat task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
def reconciliation_context() -> Iterator[None]:
    """Clear refund rows before and after each task test."""
    _reset()
    try:
        yield
    finally:
        _reset()


def _reset() -> None:
    """Remove refund rows in foreign-key-safe order."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        session.execute(delete(WebhookEvent))
        session.execute(delete(AuditLog))
        session.execute(delete(FinancialEvent))
        session.execute(delete(License))
        session.execute(delete(Payout))
        session.execute(delete(PayoutAccount))
        session.execute(delete(Escrow))
        session.execute(delete(Transaction))
        session.execute(delete(Framework))
        session.execute(delete(UserRole))
        session.execute(delete(User))
        session.commit()
    sync_engine.dispose()


def _seed_stuck_refund() -> tuple[UUID, UUID]:
    """Create a refunded purchase whose settlement event never arrived."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        contributor = User(
            email=f"beat-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("password"),
            display_name="Beat Contributor",
            email_verified=True,
        )
        operator = User(
            email=f"beat-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("password"),
            display_name="Beat Operator",
            email_verified=True,
        )
        session.add_all([contributor, operator])
        session.flush()
        framework = Framework(
            contributor_id=contributor.id,
            title="Beat Reconciliation Framework",
            description="Framework used by refund reconciliation Beat tests.",
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
        session.flush()
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
        session.flush()
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
        session.add(
            FinancialEvent(
                entity_type="transaction",
                entity_id=transaction.id,
                event_type="refund_requested",
                from_status="completed",
                to_status="refunded",
                amount=Decimal("149.00"),
                currency="USD",
                provider="paystack",
                provider_ref=REFUND_ID,
                actor_id=operator.id,
                occurred_at=datetime.now(UTC) - timedelta(hours=96),
            )
        )
        session.commit()
        ids = (transaction.id, license_row.id)
    sync_engine.dispose()
    return ids


def test_reconcile_task_reverses_a_declined_refund_once(
    migrated_database: None,
    reconciliation_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduled task reverses a stuck refund, and re-running changes nothing."""
    del migrated_database, reconciliation_context
    transaction_id, license_id = _seed_stuck_refund()

    async def fake_fetch(*, refund_id: str, **_: Any) -> PaystackRefund:
        return PaystackRefund(id=refund_id, status="failed")

    monkeypatch.setattr(paystack, "fetch_refund", fake_fetch)

    first = financials_beat.reconcile_pending_refunds_task.apply().get()
    second = financials_beat.reconcile_pending_refunds_task.apply().get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        transaction = session.get(Transaction, transaction_id)
        license_row = session.get(License, license_id)
    sync_engine.dispose()

    assert first == {"checked": 1, "settled": 0, "reversed": 1, "unresolved": 0}
    assert second == {"checked": 0, "settled": 0, "reversed": 0, "unresolved": 0}
    assert transaction is not None
    assert transaction.status == "completed"
    assert license_row is not None
    assert license_row.status == "active"


def test_reconciliation_is_registered_on_the_beat_schedule() -> None:
    """The task must be scheduled, or the hole it closes stays open."""
    entry = BEAT_SCHEDULE["reconcile-pending-refunds-hourly"]

    assert entry["task"] == (
        "app.workers.tasks.financials_beat.reconcile_pending_refunds_task"
    )
    assert entry["schedule"] == 3600.0


def _seed_held_paystack_escrow(amount: Decimal) -> UUID:
    """Create a held Paystack-funded escrow and return its transaction id."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        operator = User(
            email=f"floor-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("password"),
            display_name="Floor Operator",
            email_verified=True,
        )
        session.add(operator)
        session.flush()
        transaction = Transaction(
            payer_id=operator.id,
            payee_id=None,
            amount=amount,
            currency="USD",
            platform_commission=Decimal("0.00"),
            net_amount=amount,
            transaction_type="milestone",
            status="completed",
            provider="paystack",
            provider_ref=f"floor_ref_{uuid4().hex}",
            ref_id=uuid4(),
            ref_type="project_milestone",
        )
        session.add(transaction)
        session.flush()
        session.add(
            Escrow(
                ref_id=transaction.ref_id,
                ref_type="project_milestone",
                amount=amount,
                currency="USD",
                status="held",
                release_conditions={"kind": "project_milestone"},
                transaction_id=transaction.id,
            )
        )
        transaction_id = transaction.id
        session.commit()
    sync_engine.dispose()
    return transaction_id


def test_balance_floor_task_alerts_when_balance_dips_below_held_escrow(
    migrated_database: None,
    reconciliation_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A platform balance below the held-escrow total must page an admin.

    Escrow on the Paystack rail lives in the shared platform balance, which
    payouts also draw from — if the balance dips under the held total, a
    future release could not be honored, so the dip is CRITICAL and an admin
    is notified immediately.
    """
    del migrated_database, reconciliation_context
    _seed_held_paystack_escrow(Decimal("1500.00"))
    alerts: list[dict[str, Any]] = []

    async def fake_fetch_balance() -> dict[str, int]:
        """Report a balance short of the held total (minor units)."""
        return {"USD": 100000}

    monkeypatch.setattr(paystack, "fetch_balance", fake_fetch_balance)
    monkeypatch.setattr(
        balance_floor,
        "notify_admins_review_pending",
        lambda **kwargs: alerts.append(kwargs),
    )

    result = financials_beat.check_platform_balance_floor_task.apply().get()

    assert result == {"currencies_checked": 1, "alerts": 1}
    assert len(alerts) == 1
    assert "USD" in alerts[0]["body"]

    # The breach leaves a queryable audit row: a dismissed notification and an
    # aged-out log line must not be the only evidence it ever happened.
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        audit = session.execute(
            select(AuditLog).where(
                AuditLog.action == "platform_balance_below_escrow_floor"
            )
        ).scalar_one_or_none()
    sync_engine.dispose()
    assert audit is not None
    assert audit.metadata_["currency"] == "USD"


def test_balance_floor_task_quiet_when_balance_covers_held_escrow(
    migrated_database: None,
    reconciliation_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A balance covering every held escrow raises no alert."""
    del migrated_database, reconciliation_context
    _seed_held_paystack_escrow(Decimal("1500.00"))
    alerts: list[dict[str, Any]] = []

    async def fake_fetch_balance() -> dict[str, int]:
        """Report a balance comfortably above the held total."""
        return {"USD": 500000}

    monkeypatch.setattr(paystack, "fetch_balance", fake_fetch_balance)
    monkeypatch.setattr(
        balance_floor,
        "notify_admins_review_pending",
        lambda **kwargs: alerts.append(kwargs),
    )

    result = financials_beat.check_platform_balance_floor_task.apply().get()

    assert result == {"currencies_checked": 1, "alerts": 0}
    assert alerts == []


def _seed_payout(
    *,
    status: str,
    initiated_at: datetime,
    provider_ref: str | None = None,
) -> UUID:
    """Create one payout row with its contributor and payout account."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        contributor = User(
            email=f"sweep-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("password"),
            display_name="Sweep Contributor",
            email_verified=True,
        )
        session.add(contributor)
        session.flush()
        account = PayoutAccount(
            user_id=contributor.id,
            provider="stripe",
            provider_account_id=encrypt_payout_provider_account_id(
                f"acct_{uuid4().hex[:10]}"
            ),
            provider_account_lookup_hash=hash_payout_provider_account_id(
                f"acct_{uuid4().hex[:10]}"
            ),
            account_type="express",
            is_default=True,
            verified_at=datetime.now(UTC),
        )
        session.add(account)
        session.flush()
        payout = Payout(
            contributor_id=contributor.id,
            payout_account_id=account.id,
            amount=Decimal("100.00"),
            currency="USD",
            commission_deducted=Decimal("15.00"),
            net_amount=Decimal("85.00"),
            status=status,
            provider_ref=provider_ref,
            initiated_at=initiated_at,
        )
        session.add(payout)
        session.commit()
        payout_id = payout.id
    sync_engine.dispose()
    return payout_id


def test_stranded_payout_sweeper_requeues_old_pending_payouts(
    migrated_database: None,
    reconciliation_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending payout past the grace window is re-enqueued for processing.

    A payout stays `pending` only if its Celery dispatch failed or the worker
    died before reaching the provider; the processing worker is idempotent,
    so re-enqueueing is always safe and leaving it stranded never is.
    """
    del migrated_database, reconciliation_context
    stranded_id = _seed_payout(
        status="pending",
        initiated_at=datetime.now(UTC) - timedelta(hours=2),
    )
    fresh_id = _seed_payout(status="pending", initiated_at=datetime.now(UTC))
    _seed_payout(
        status="processing",
        initiated_at=datetime.now(UTC) - timedelta(hours=2),
        provider_ref="tr_in_flight",
    )
    dispatched: list[str] = []

    class FakePayoutTask:
        """Task double recording re-enqueued payout ids."""

        def delay(self, payout_id: str) -> None:
            """Record the payout id that would be sent to Celery."""
            dispatched.append(payout_id)

    monkeypatch.setattr(financials_beat, "process_payout", FakePayoutTask())

    result = financials_beat.requeue_stranded_payouts_task.apply().get()

    assert result == {"checked": 1, "requeued": 1}
    assert dispatched == [str(stranded_id)]
    assert str(fresh_id) not in dispatched


def test_stranded_payout_sweeper_is_registered_on_the_beat_schedule() -> None:
    """The sweeper must be scheduled, or dispatch failures strand money forever."""
    entry = BEAT_SCHEDULE["requeue-stranded-payouts-hourly"]

    assert entry["task"] == (
        "app.workers.tasks.financials_beat.requeue_stranded_payouts_task"
    )
    assert entry["schedule"] == 3600.0


def _seed_refund_intent(
    *,
    intent_key: str,
    occurred_at: datetime,
    provider: str = "stripe",
    resolved: bool = False,
) -> UUID:
    """Insert one refund_initiated event, optionally with its outcome row."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    transaction_id = uuid4()
    with session_factory() as session:
        session.add(
            FinancialEvent(
                entity_type="transaction",
                entity_id=transaction_id,
                event_type="refund_initiated",
                amount=Decimal("149.00"),
                currency="USD",
                provider=provider,
                provider_ref="pi_intent_charge_1",
                occurred_at=occurred_at,
                metadata_={"intent_key": intent_key},
            )
        )
        if resolved:
            session.add(
                FinancialEvent(
                    entity_type="transaction",
                    entity_id=transaction_id,
                    event_type="refund_requested",
                    amount=Decimal("149.00"),
                    currency="USD",
                    provider=provider,
                    provider_ref="re_done_1",
                    occurred_at=occurred_at + timedelta(seconds=1),
                    metadata_={"intent_key": intent_key},
                )
            )
        session.commit()
    sync_engine.dispose()
    return transaction_id


def test_refund_intent_sweep_flags_untracked_provider_refunds(
    migrated_database: None,
    reconciliation_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An orphaned intent whose provider refund exists is flagged CRITICAL.

    A crash between the provider accepting the refund and our commit leaves
    money moved with no local record; the sweep asks the provider directly
    and pages an admin with a durable audit + ledger trail.
    """
    del migrated_database, reconciliation_context
    transaction_id = _seed_refund_intent(
        intent_key="intent-flagged-1",
        occurred_at=datetime.now(UTC) - timedelta(hours=2),
    )
    alerts: list[dict[str, Any]] = []

    async def fake_list_refunds(*, payment_intent_id: str, **_: Any) -> list[Any]:
        """Report one provider refund for the orphaned charge."""
        del payment_intent_id
        return [StripeRefund(id="re_orphan_1", status="succeeded")]

    monkeypatch.setattr(refund_intents.stripe, "list_refunds", fake_list_refunds)
    monkeypatch.setattr(
        refund_intents,
        "notify_admins_review_pending",
        lambda **kwargs: alerts.append(kwargs),
    )

    result = financials_beat.reconcile_refund_intents_task.apply().get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        audit = session.execute(
            select(AuditLog).where(
                AuditLog.action == "untracked_refund_detected"
            )
        ).scalar_one_or_none()
        flagged = session.execute(
            select(FinancialEvent).where(
                FinancialEvent.event_type == "refund_intent_flagged"
            )
        ).scalar_one_or_none()
    sync_engine.dispose()

    assert result == {"checked": 1, "closed": 0, "flagged": 1, "unresolved": 0}
    assert len(alerts) == 1
    assert audit is not None
    assert audit.target_id == transaction_id
    assert flagged is not None
    assert flagged.metadata_["provider_refund_ids"] == ["re_orphan_1"]


def test_refund_intent_sweep_closes_abandoned_attempts(
    migrated_database: None,
    reconciliation_context: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An orphaned intent with no provider refund closes quietly."""
    del migrated_database, reconciliation_context
    _seed_refund_intent(
        intent_key="intent-abandoned-1",
        occurred_at=datetime.now(UTC) - timedelta(hours=2),
    )
    alerts: list[dict[str, Any]] = []

    async def fake_list_refunds(**_: Any) -> list[Any]:
        """Report no provider refunds: the attempt died before the call."""
        return []

    monkeypatch.setattr(refund_intents.stripe, "list_refunds", fake_list_refunds)
    monkeypatch.setattr(
        refund_intents,
        "notify_admins_review_pending",
        lambda **kwargs: alerts.append(kwargs),
    )

    result = financials_beat.reconcile_refund_intents_task.apply().get()
    second = financials_beat.reconcile_refund_intents_task.apply().get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        closed = session.execute(
            select(FinancialEvent).where(
                FinancialEvent.event_type == "refund_intent_closed"
            )
        ).scalar_one_or_none()
    sync_engine.dispose()

    assert result == {"checked": 1, "closed": 1, "flagged": 0, "unresolved": 0}
    assert second == {"checked": 0, "closed": 0, "flagged": 0, "unresolved": 0}
    assert alerts == []
    assert closed is not None


def test_refund_intent_sweep_skips_intents_with_recorded_outcomes(
    migrated_database: None,
    reconciliation_context: None,
) -> None:
    """An intent whose refund_requested event landed is never probed."""
    del migrated_database, reconciliation_context
    _seed_refund_intent(
        intent_key="intent-resolved-1",
        occurred_at=datetime.now(UTC) - timedelta(hours=2),
        resolved=True,
    )

    result = financials_beat.reconcile_refund_intents_task.apply().get()

    assert result == {"checked": 0, "closed": 0, "flagged": 0, "unresolved": 0}


def test_refund_intent_sweep_is_registered_on_the_beat_schedule() -> None:
    """The sweep must be scheduled, or crash-orphaned refunds stay invisible."""
    entry = BEAT_SCHEDULE["reconcile-refund-intents-hourly"]

    assert entry["task"] == (
        "app.workers.tasks.financials_beat.reconcile_refund_intents_task"
    )
    assert entry["schedule"] == 3600.0


def _seed_webhook_event(*, received_at: datetime) -> UUID:
    """Insert one processed webhook event row with the given receipt time."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        event = WebhookEvent(
            provider="stripe",
            provider_event_id=f"evt_prune_{uuid4().hex}",
            event_type="payment_intent.succeeded",
            status="processed",
            payload_hash="0" * 64,
            received_at=received_at,
        )
        session.add(event)
        session.commit()
        event_id = event.id
    sync_engine.dispose()
    return event_id


def test_webhook_event_pruning_removes_only_aged_rows(
    migrated_database: None,
    reconciliation_context: None,
) -> None:
    """Pruning drops events past retention and keeps everything younger.

    The rows exist for replay dedupe and short-term forensics; providers stop
    retrying within days, so rows older than the retention window only grow
    the table. The durable money record lives in audit_logs and the ledger.
    """
    del migrated_database, reconciliation_context
    old_id = _seed_webhook_event(
        received_at=datetime.now(UTC) - timedelta(days=120)
    )
    fresh_id = _seed_webhook_event(received_at=datetime.now(UTC) - timedelta(days=5))

    result = financials_beat.prune_webhook_events_task.apply().get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=sync_engine)
    with session_factory() as session:
        old_row = session.get(WebhookEvent, old_id)
        fresh_row = session.get(WebhookEvent, fresh_id)
    sync_engine.dispose()

    assert result == {"pruned": 1}
    assert old_row is None
    assert fresh_row is not None


def test_webhook_event_pruning_is_registered_on_the_beat_schedule() -> None:
    """The pruning task must be scheduled, or the table grows without bound."""
    entry = BEAT_SCHEDULE["prune-webhook-events-daily"]

    assert entry["task"] == (
        "app.workers.tasks.financials_beat.prune_webhook_events_task"
    )
    assert entry["schedule"] == 86400.0


def test_balance_floor_is_registered_on_the_beat_schedule() -> None:
    """The floor check must be scheduled, or the commingling risk goes unwatched."""
    entry = BEAT_SCHEDULE["check-platform-balance-floor-hourly"]

    assert entry["task"] == (
        "app.workers.tasks.financials_beat.check_platform_balance_floor_task"
    )
    assert entry["schedule"] == 3600.0
