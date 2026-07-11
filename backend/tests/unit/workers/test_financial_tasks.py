"""Tests for financial Celery tasks."""

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
from app.core.security import (
    encrypt_payout_provider_account_id,
    hash_password,
    hash_payout_provider_account_id,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Payout, PayoutAccount, Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import Artifact, ArtifactDownload
from app.modules.invoicing.keys import invoice_pdf_key
from app.modules.invoicing.models import Invoice, InvoiceCounter
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import financials as financial_tasks
from app.workers.tasks import payouts as payout_tasks
from app.workers.tasks import scheduled as scheduled_tasks


class FakeInvoiceStorage:
    """S3 test double that records invoice uploads."""

    def __init__(self) -> None:
        """Create empty upload history."""
        self.uploads: dict[str, bytes] = {}

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Record uploaded PDF bytes."""
        self.uploads[f"{bucket}/{key}/{mime_type}"] = body


class FakeInvoiceRenderer:
    """Shared invoice renderer test double."""

    render_calls: list[dict[str, str]] = []

    @classmethod
    def reset(cls) -> None:
        """Clear captured render calls between tests."""
        cls.render_calls = []

    @classmethod
    def render(cls, invoice: Invoice, *, line_item_label: str) -> bytes:
        """Capture the invoice snapshot passed into the worker."""
        cls.render_calls.append(
            {
                "invoice_number": invoice.invoice_number,
                "line_item_label": line_item_label,
                "s3_key": invoice.s3_key,
            }
        )
        return b"%PDF-INVOICE%"


class FakeStripeTransfer:
    """Small stand-in for a Stripe transfer result."""

    def __init__(self, transfer_id: str) -> None:
        """Store the provider transfer id and status."""
        self.id = transfer_id
        self.status = "pending"


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for invoice task tests."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def financial_task_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Any]]:
    """Reset rows and install invoice rendering/storage doubles."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    fake_storage = FakeInvoiceStorage()
    transfer_calls: list[dict[str, Any]] = []

    def cleanup() -> None:
        """Delete task rows before users to satisfy foreign keys."""
        with session_factory() as session:
            session.execute(delete(WebhookEvent))
            session.execute(delete(AuditLog))
            session.execute(delete(ArtifactDownload))
            session.execute(delete(Artifact))
            session.execute(delete(License))
            session.execute(delete(Payout))
            session.execute(delete(PayoutAccount))
            session.execute(delete(Invoice))
            session.execute(delete(InvoiceCounter))
            session.execute(delete(Transaction))
            session.execute(delete(Framework))
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
        """Record provider transfer requests for payout task tests."""
        transfer_calls.append(
            {
                "amount": amount,
                "currency": currency,
                "destination_account_id": destination_account_id,
                "metadata": metadata,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeTransfer("tr_payout_123")

    cleanup()
    monkeypatch.setattr(financial_tasks.s3, "storage", fake_storage)
    FakeInvoiceRenderer.reset()
    monkeypatch.setattr(
        financial_tasks,
        "render_invoice_pdf",
        FakeInvoiceRenderer.render,
    )
    monkeypatch.setattr(payout_tasks.stripe, "create_transfer", fake_create_transfer)
    try:
        yield {
            "storage": fake_storage,
            "transfer_calls": transfer_calls,
            "render_calls": FakeInvoiceRenderer.render_calls,
        }
    finally:
        cleanup()
        sync_engine.dispose()


def create_completed_purchase() -> UUID:
    """Create a completed purchase transaction for invoice generation."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        contributor = User(
            email=f"invoice-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Invoice Contributor",
            email_verified=True,
        )
        operator = User(
            email=f"invoice-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Invoice Operator",
            email_verified=True,
        )
        session.add_all([contributor, operator])
        session.flush()
        session.add_all(
            [
                UserRole(
                    user_id=contributor.id,
                    role="contributor",
                    approved_at=datetime.now(UTC),
                ),
                UserRole(
                    user_id=operator.id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                ),
            ]
        )
        framework = Framework(
            contributor_id=contributor.id,
            title="Invoice Framework",
            description="Invoice Framework description.",
            status="published",
            category="operations",
            tags=["invoice"],
            tags_text="invoice",
            price=Decimal("199.00"),
            currency="USD",
            license_types=["team"],
        )
        session.add(framework)
        session.flush()
        transaction = Transaction(
            payer_id=operator.id,
            payee_id=contributor.id,
            amount=Decimal("199.00"),
            currency="USD",
            platform_commission=Decimal("0.00"),
            net_amount=Decimal("199.00"),
            transaction_type="purchase",
            status="completed",
            provider="stripe",
            provider_ref="pi_invoice_123",
            ref_id=framework.id,
            ref_type="framework",
        )
        session.add(transaction)
        session.flush()
        session.add(
            License(
                framework_id=framework.id,
                operator_id=operator.id,
                transaction_id=transaction.id,
                license_type="team",
                status="active",
                version_at_grant=framework.version,
                seats_used=1,
                seats_total=10,
            )
        )
        transaction_id = transaction.id
        session.commit()
    sync_engine.dispose()
    return transaction_id


def issue_purchase_invoice(transaction_id: UUID) -> Invoice:
    """Insert the issued shared-ledger invoice row for one purchase."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        transaction = session.get(Transaction, transaction_id)
        if transaction is None:
            raise AssertionError("Expected purchase transaction to exist.")
        operator = session.get(User, transaction.payer_id)
        if operator is None:
            raise AssertionError("Expected operator to exist.")
        invoice = Invoice(
            series="AUR-INV",
            sequence_year=2026,
            sequence_number=1,
            invoice_number="AUR-INV-2026-000001",
            doc_type="sales_invoice",
            currency=transaction.currency,
            subtotal=transaction.amount,
            tax_rate=Decimal("0.0000"),
            tax_amount=Decimal("0.00"),
            total=transaction.amount,
            seller_name="Auracles Ltd",
            seller_tax_id="TAX-1",
            seller_address="1 Ledger Street",
            buyer_name=operator.display_name,
            buyer_email=operator.email,
            source_ref_type="transaction",
            source_ref_id=transaction_id,
            s3_key="",
        )
        session.add(invoice)
        session.flush()
        invoice.s3_key = invoice_pdf_key(invoice.doc_type, invoice.id)
        session.commit()
        session.refresh(invoice)
    sync_engine.dispose()
    return invoice


def create_pending_payout() -> UUID:
    """Create a pending payout request for transfer processing."""
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
        provider_account_id = "acct_payout_123"
        payout_account = PayoutAccount(
            user_id=contributor.id,
            provider="stripe",
            provider_account_id=encrypt_payout_provider_account_id(provider_account_id),
            provider_account_lookup_hash=hash_payout_provider_account_id(
                provider_account_id
            ),
            account_type="express",
            is_default=True,
            verified_at=datetime.now(UTC),
        )
        session.add(payout_account)
        session.flush()
        payout = Payout(
            contributor_id=contributor.id,
            payout_account_id=payout_account.id,
            amount=Decimal("58.82"),
            currency="USD",
            commission_deducted=Decimal("8.82"),
            net_amount=Decimal("50.00"),
            status="pending",
        )
        session.add(payout)
        session.flush()
        payout_id = payout.id
        session.commit()
    sync_engine.dispose()
    return payout_id


def create_expirable_licenses() -> tuple[UUID, UUID]:
    """Create one expired and one still-active license."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        contributor = User(
            email=f"expiry-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Expiry Contributor",
            email_verified=True,
        )
        operator = User(
            email=f"expiry-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Expiry Operator",
            email_verified=True,
        )
        future_operator = User(
            email=f"future-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="Future Operator",
            email_verified=True,
        )
        session.add_all([contributor, operator, future_operator])
        session.flush()
        framework = Framework(
            contributor_id=contributor.id,
            title="Expiry Framework",
            description="Expiry Framework description.",
            status="published",
            category="operations",
            tags=["expiry"],
            tags_text="expiry",
            price=Decimal("99.00"),
            currency="USD",
            license_types=["single_user"],
        )
        session.add(framework)
        session.flush()
        expired_license = License(
            framework_id=framework.id,
            operator_id=operator.id,
            license_type="single_user",
            status="active",
            version_at_grant=framework.version,
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        future_license = License(
            framework_id=framework.id,
            operator_id=future_operator.id,
            license_type="single_user",
            status="active",
            version_at_grant=framework.version,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        session.add_all([expired_license, future_license])
        session.flush()
        expired_id = expired_license.id
        future_id = future_license.id
        session.commit()
    sync_engine.dispose()
    return expired_id, future_id


def test_generate_invoice_pdf_uploads_rendered_purchase_invoice(
    migrated_database: None,
    financial_task_context: dict[str, Any],
) -> None:
    """Invoice task renders HTML to PDF and stores it in the reports bucket."""
    transaction_id = create_completed_purchase()
    invoice = issue_purchase_invoice(transaction_id)

    result = financial_tasks.generate_invoice_pdf.apply(
        args=[str(transaction_id)]
    ).get()

    storage: FakeInvoiceStorage = financial_task_context["storage"]
    assert result == {
        "transaction_id": str(transaction_id),
        "invoice_key": invoice.s3_key,
        "status": "invoice_generated",
    }
    assert storage.uploads == {
        f"auracles-reports-dev/{invoice.s3_key}/application/pdf": b"%PDF-INVOICE%"
    }
    assert financial_task_context["render_calls"] == [
        {
            "invoice_number": "AUR-INV-2026-000001",
            "line_item_label": "Invoice Framework",
            "s3_key": invoice.s3_key,
        }
    ]


def test_process_payout_creates_transfer_and_marks_processing(
    migrated_database: None,
    financial_task_context: dict[str, Any],
) -> None:
    """Payout task creates a provider transfer and stores its reference."""
    del migrated_database
    payout_id = create_pending_payout()

    result = payout_tasks.process_payout.apply(args=[str(payout_id)]).get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        payout = session.get(Payout, payout_id)
        audit = session.query(AuditLog).filter_by(action="payout_processing").one()
    sync_engine.dispose()

    assert result == {
        "payout_id": str(payout_id),
        "provider_ref": "tr_payout_123",
        "status": "processing",
    }
    assert financial_task_context["transfer_calls"] == [
        {
            "amount": Decimal("50.00"),
            "currency": "USD",
            "destination_account_id": "acct_payout_123",
            "metadata": {
                "payout_id": str(payout_id),
                "contributor_id": str(payout.contributor_id),
            },
            "idempotency_key": f"payout:{payout_id}",
        }
    ]
    assert payout.status == "processing"
    assert payout.provider_ref == "tr_payout_123"
    assert audit.target_id == payout_id


def test_clear_expired_licenses_marks_only_past_due_active_licenses(
    migrated_database: None,
    financial_task_context: dict[str, Any],
) -> None:
    """Scheduled task expires active licenses whose expiry has passed."""
    del migrated_database, financial_task_context
    expired_id, future_id = create_expirable_licenses()

    result = scheduled_tasks.clear_expired_licenses.apply().get()

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    with session_factory() as session:
        expired_license = session.get(License, expired_id)
        future_license = session.get(License, future_id)
        audit_count = (
            session.query(AuditLog).filter_by(action="license_expired").count()
        )
    sync_engine.dispose()

    assert result == {"expired_count": 1}
    assert expired_license.status == "expired"
    assert future_license.status == "active"
    assert audit_count == 1
