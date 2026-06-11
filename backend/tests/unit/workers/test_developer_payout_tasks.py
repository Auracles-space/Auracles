"""Tests for Developer Partner payout Celery tasks."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import (
    encrypt_payout_provider_account_id,
    hash_password,
    hash_payout_provider_account_id,
)
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    DeveloperAccount,
    DeveloperApplication,
    PartnerPayout,
)
from app.modules.financials.models import PayoutAccount
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import developer_payouts


class FakeStripeTransfer:
    """Small stand-in for a Stripe transfer result."""

    def __init__(self, transfer_id: str) -> None:
        """Store the provider transfer id and status."""
        self.id = transfer_id
        self.status = "pending"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Partner payout tables exist for task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def developer_payout_task_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[dict[str, Any]]]:
    """Reset task rows and replace Stripe transfer calls."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    transfer_calls: list[dict[str, Any]] = []

    def cleanup() -> None:
        """Delete task rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(PartnerPayout))
            session.execute(delete(PayoutAccount))
            session.execute(delete(DeveloperAccount))
            session.execute(delete(DeveloperApplication))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    async def fake_create_transfer(
        *,
        amount: Decimal,
        currency: str,
        destination_account_id: str,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> FakeStripeTransfer:
        """Record Stripe transfer creation for Partner payout processing."""
        transfer_calls.append(
            {
                "amount": amount,
                "currency": currency,
                "destination_account_id": destination_account_id,
                "metadata": metadata,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeTransfer("tr_partner_payout_123")

    cleanup()
    monkeypatch.setattr(
        developer_payouts.stripe,
        "create_transfer",
        fake_create_transfer,
    )
    try:
        yield transfer_calls
    finally:
        cleanup()
        sync_engine.dispose()


def create_pending_partner_payout() -> UUID:
    """Create a pending Partner payout request for transfer processing."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        developer = User(
            email=f"task-partner-developer-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Task Partner Developer",
            email_verified=True,
            kyc_status="verified",
        )
        session.add(developer)
        session.flush()
        session.add(
            UserRole(
                user_id=developer.id,
                role="developer",
                approved_at=datetime.now(UTC),
            )
        )
        application = DeveloperApplication(
            user_id=developer.id,
            company_name="Task Partner",
            website="https://task-partner.example.com",
            use_case="Process Partner payout transfers.",
            status="approved",
            reviewed_at=datetime.now(UTC),
        )
        session.add(application)
        session.flush()
        account = DeveloperAccount(
            user_id=developer.id,
            application_id=application.id,
            company_name=application.company_name,
        )
        payout_account = PayoutAccount(
            user_id=developer.id,
            provider="stripe",
            provider_account_id=encrypt_payout_provider_account_id(
                "acct_partner_task_123"
            ),
            provider_account_lookup_hash=hash_payout_provider_account_id(
                "acct_partner_task_123"
            ),
            account_type="express",
            is_default=True,
            verified_at=datetime.now(UTC),
        )
        session.add_all([account, payout_account])
        session.flush()
        payout = PartnerPayout(
            developer_account_id=account.id,
            payout_account_id=payout_account.id,
            amount=Decimal("55.00"),
            currency="USD",
            status="pending",
        )
        session.add(payout)
        session.flush()
        payout_id = payout.id
        session.commit()
    sync_engine.dispose()
    return payout_id


def test_process_partner_payout_creates_transfer_and_marks_processing(
    migrated_database: None,
    developer_payout_task_context: list[dict[str, Any]],
) -> None:
    """Partner payout task creates a provider transfer and stores its reference."""
    del migrated_database
    payout_id = create_pending_partner_payout()

    result = developer_payouts.process_partner_payout.apply(args=[str(payout_id)]).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        payout = session.get(PartnerPayout, payout_id)
        audit = (
            session.query(AuditLog)
            .filter_by(action="partner_payout_processing")
            .one()
        )
    sync_engine.dispose()

    assert result == {
        "payout_id": str(payout_id),
        "provider_ref": "tr_partner_payout_123",
        "status": "processing",
    }
    assert developer_payout_task_context == [
        {
            "amount": Decimal("55.00"),
            "currency": "USD",
            "destination_account_id": "acct_partner_task_123",
            "metadata": {
                "partner_payout_id": str(payout_id),
                "developer_account_id": str(payout.developer_account_id),
            },
            "idempotency_key": f"partner_payout:{payout_id}",
        }
    ]
    assert payout.status == "processing"
    assert payout.provider_ref == "tr_partner_payout_123"
    assert audit.target_id == payout_id
