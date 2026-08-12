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
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.integrations import paystack
from app.integrations.paystack import PaystackRefund
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import FinancialEvent, Transaction
from app.modules.frameworks.models import Framework, License
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
        session.execute(delete(AuditLog))
        session.execute(delete(FinancialEvent))
        session.execute(delete(License))
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
