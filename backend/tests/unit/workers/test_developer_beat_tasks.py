"""Tests for Developer platform scheduled Celery tasks."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
)
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import developer_beat


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Developer and financial tables exist for Beat task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def developer_beat_context() -> Iterator[None]:
    """Reset Developer Beat rows before and after each task test."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)

    def cleanup() -> None:
        """Delete rows in foreign-key-safe order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(PartnerCommission))
            session.execute(delete(ApiKey))
            session.execute(delete(DeveloperAccount))
            session.execute(delete(DeveloperApplication))
            session.execute(delete(Transaction))
            session.execute(delete(Framework))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    try:
        yield
    finally:
        cleanup()
        sync_engine.dispose()


def create_partner_commission_set() -> tuple[UUID, UUID, UUID]:
    """Create eligible, refunded, and still-recent partner commissions."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    now = datetime.now(UTC)
    with session_factory() as session:
        contributor = User(
            email=f"beat-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Beat Contributor",
            email_verified=True,
        )
        operator = User(
            email=f"beat-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Beat Operator",
            email_verified=True,
        )
        developer = User(
            email=f"beat-developer-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Beat Developer",
            email_verified=True,
        )
        session.add_all([contributor, operator, developer])
        session.flush()
        session.add_all(
            [
                UserRole(
                    user_id=contributor.id,
                    role="contributor",
                    approved_at=now,
                ),
                UserRole(user_id=operator.id, role="operator", approved_at=now),
                UserRole(user_id=developer.id, role="developer", approved_at=now),
            ]
        )
        application = DeveloperApplication(
            user_id=developer.id,
            company_name="Beat Partner",
            website="https://beat-partner.example.com",
            use_case="Verify scheduled partner commission clearing.",
            status="approved",
            reviewed_at=now,
        )
        session.add(application)
        session.flush()
        account = DeveloperAccount(
            user_id=developer.id,
            application_id=application.id,
            company_name=application.company_name,
            commission_tier=1,
            tier_rate=Decimal("0.0500"),
        )
        session.add(account)
        session.flush()
        api_key = ApiKey(
            developer_account_id=account.id,
            name="Beat key",
            key_prefix="ak_beat",
            key_hash=f"beat-hash-{uuid4()}",
            scopes=["purchase:write"],
        )
        session.add(api_key)
        framework = Framework(
            contributor_id=contributor.id,
            title="Beat Framework",
            description="Framework used by commission clearing task tests.",
            status="published",
            category="operations",
            tags=["beat"],
            tags_text="beat",
            price=Decimal("200.00"),
            currency="USD",
            license_types=["team"],
        )
        session.add(framework)
        session.flush()

        def add_transaction(status: str) -> Transaction:
            """Create one transaction for a partner commission fixture."""
            transaction = Transaction(
                payer_id=operator.id,
                payee_id=contributor.id,
                amount=Decimal("200.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("200.00"),
                transaction_type="purchase",
                status=status,
                provider="stripe",
                provider_ref=f"pi_beat_{uuid4()}",
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            session.flush()
            return transaction

        eligible_transaction = add_transaction("completed")
        refunded_transaction = add_transaction("refunded")
        recent_transaction = add_transaction("completed")

        def add_commission(
            transaction: Transaction,
            created_at: datetime,
        ) -> PartnerCommission:
            """Create one pending commission row for the task to inspect."""
            commission = PartnerCommission(
                api_key_id=api_key.id,
                developer_account_id=account.id,
                transaction_id=transaction.id,
                framework_id=framework.id,
                sale_amount=Decimal("200.00"),
                currency="USD",
                tier_at_sale=1,
                tier_rate=Decimal("0.0500"),
                commission_amount=Decimal("10.00"),
                status="pending",
                created_at=created_at,
            )
            session.add(commission)
            session.flush()
            return commission

        eligible = add_commission(eligible_transaction, now - timedelta(hours=49))
        refunded = add_commission(refunded_transaction, now - timedelta(hours=49))
        recent = add_commission(recent_transaction, now - timedelta(hours=47))
        ids = (eligible.id, refunded.id, recent.id)
        session.commit()
    sync_engine.dispose()
    return ids


def test_clear_partner_commissions_clears_old_sales_and_voids_refunds(
    migrated_database: None,
    developer_beat_context: None,
) -> None:
    """Developer Beat clears mature commissions and voids refunded sales once."""
    del migrated_database, developer_beat_context
    eligible_id, refunded_id, recent_id = create_partner_commission_set()

    first = developer_beat.clear_partner_commissions.apply().get()
    second = developer_beat.clear_partner_commissions.apply().get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        eligible = session.get(PartnerCommission, eligible_id)
        refunded = session.get(PartnerCommission, refunded_id)
        recent = session.get(PartnerCommission, recent_id)
        cleared_audits = (
            session.query(AuditLog)
            .filter_by(action="partner_commission_cleared")
            .count()
        )
        voided_audits = (
            session.query(AuditLog)
            .filter_by(action="partner_commission_voided")
            .count()
        )
    sync_engine.dispose()

    assert first == {"cleared_count": 1, "voided_count": 1}
    assert second == {"cleared_count": 0, "voided_count": 0}
    assert eligible.status == "cleared"
    assert eligible.cleared_at is not None
    assert refunded.status == "voided"
    assert refunded.cleared_at is None
    assert recent.status == "pending"
    assert cleared_audits == 1
    assert voided_audits == 1
