"""Tests for financial Celery tasks."""

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
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import Artifact, ArtifactDownload
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import financials as financial_tasks


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


class FakeHTML:
    """WeasyPrint HTML test double."""

    rendered_html: str = ""

    def __init__(self, *, string: str) -> None:
        """Capture the HTML sent to the renderer."""
        self.rendered_html = string
        FakeHTML.rendered_html = string

    def write_pdf(self) -> bytes:
        """Return deterministic PDF bytes."""
        return b"%PDF-INVOICE%"


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

    def cleanup() -> None:
        """Delete task rows before users to satisfy foreign keys."""
        with session_factory() as session:
            session.execute(delete(WebhookEvent))
            session.execute(delete(AuditLog))
            session.execute(delete(ArtifactDownload))
            session.execute(delete(Artifact))
            session.execute(delete(License))
            session.execute(delete(Transaction))
            session.execute(delete(Framework))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    cleanup()
    monkeypatch.setattr(financial_tasks.s3, "storage", fake_storage)
    monkeypatch.setattr(financial_tasks, "HTML", FakeHTML)
    try:
        yield {"storage": fake_storage}
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


def test_generate_invoice_pdf_uploads_rendered_purchase_invoice(
    migrated_database: None,
    financial_task_context: dict[str, Any],
) -> None:
    """Invoice task renders HTML to PDF and stores it in the reports bucket."""
    transaction_id = create_completed_purchase()

    result = financial_tasks.generate_invoice_pdf.apply(
        args=[str(transaction_id)]
    ).get()

    storage: FakeInvoiceStorage = financial_task_context["storage"]
    invoice_key = f"invoices/purchases/{transaction_id}.pdf"
    assert result == {
        "transaction_id": str(transaction_id),
        "invoice_key": invoice_key,
        "status": "invoice_generated",
    }
    assert storage.uploads == {
        f"auracles-reports-dev/{invoice_key}/application/pdf": b"%PDF-INVOICE%"
    }
    assert "Invoice Framework" in FakeHTML.rendered_html
    assert "199.00 USD" in FakeHTML.rendered_html
