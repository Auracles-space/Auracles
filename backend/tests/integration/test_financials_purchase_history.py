"""Integration tests for Operator purchase history and invoices."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import Artifact, ArtifactDownload
from app.modules.invoicing.models import Invoice, InvoiceCounter
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog


class FakeInvoiceStorage:
    """S3 test double for invoice readiness and redirects."""

    def __init__(self) -> None:
        """Create empty fake object state."""
        self.existing_keys: set[str] = set()
        self.presigned_get_requests: list[tuple[str, str, int]] = []

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return whether an invoice object exists."""
        return key in self.existing_keys

    def presigned_get(self, bucket: str, key: str, expires_in: int) -> str:
        """Return a deterministic fake presigned invoice URL."""
        self.presigned_get_requests.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}?expires={expires_in}"


class FakeInvoiceTask:
    """Celery task double for invoice generation dispatch."""

    def __init__(self) -> None:
        """Create empty dispatch history."""
        self.dispatched: list[str] = []

    def delay(self, transaction_id: str) -> None:
        """Record the invoice generation request."""
        self.dispatched.append(transaction_id)


async def reset_purchase_history_state() -> None:
    """Remove purchase-history rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(WebhookEvent))
        await session.execute(delete(AuditLog))
        await session.execute(delete(ArtifactDownload))
        await session.execute(delete(Artifact))
        await session.execute(delete(License))
        await session.execute(delete(Invoice))
        await session.execute(delete(InvoiceCounter))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def purchase_history_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install invoice storage/task doubles."""
    await engine.dispose()
    await reset_purchase_history_state()
    fake_storage = FakeInvoiceStorage()
    fake_task = FakeInvoiceTask()
    monkeypatch.setattr(financials_service.s3, "storage", fake_storage)
    monkeypatch.setattr(
        financials_service,
        "generate_invoice_pdf",
        fake_task,
        raising=False,
    )
    try:
        yield {"storage": fake_storage, "invoice_task": fake_task}
    finally:
        await reset_purchase_history_state()
        await engine.dispose()


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


async def create_purchase(
    operator_id: UUID,
    *,
    title: str,
    status: str = "completed",
    amount: Decimal = Decimal("149.00"),
    created_at: datetime | None = None,
) -> tuple[UUID, UUID]:
    """Create a purchase transaction with its Framework and License."""
    contributor_id = await create_user_with_roles(
        f"history-contributor-{uuid4()}@auracles.space",
        ["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title=title,
                description=f"{title} description.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["purchase", "history"],
                price=amount,
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=amount,
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=amount,
                transaction_type="purchase",
                status=status,
                provider="stripe",
                provider_ref=f"pi_history_{uuid4().hex[:8]}",
                ref_id=framework.id,
                ref_type="framework",
            )
            if created_at is not None:
                transaction.created_at = created_at
            session.add(transaction)
            await session.flush()
            license_row = License(
                framework_id=framework.id,
                operator_id=operator_id,
                transaction_id=transaction.id,
                license_type="team",
                status="active" if status != "refunded" else "revoked",
                version_at_grant=framework.version,
                seats_used=1,
                seats_total=10,
            )
            session.add(license_row)
            await session.flush()
            return transaction.id, framework.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_operator_purchase_history_is_paginated_and_scoped(
    client: AsyncClient,
    purchase_history_context: dict[str, Any],
) -> None:
    """Operators see their own purchase transactions newest first."""
    del purchase_history_context
    operator_id = await create_user_with_roles(
        "history-operator@auracles.space",
        ["operator"],
    )
    other_operator_id = await create_user_with_roles(
        "history-other@auracles.space",
        ["operator"],
    )
    older_transaction_id, older_framework_id = await create_purchase(
        operator_id,
        title="Older Framework",
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    newer_transaction_id, newer_framework_id = await create_purchase(
        operator_id,
        title="Newer Framework",
        amount=Decimal("249.00"),
    )
    await create_purchase(other_operator_id, title="Other Operator Framework")

    first_page = await client.get(
        "/v1/financials/purchases?page=1&page_size=1",
        headers=auth_headers(operator_id, ["operator"]),
    )
    second_page = await client.get(
        "/v1/financials/purchases?page=2&page_size=1",
        headers=auth_headers(operator_id, ["operator"]),
    )

    first_body = first_page.json()
    second_body = second_page.json()
    assert first_page.status_code == 200
    assert first_body["total"] == 2
    assert first_body["page"] == 1
    assert first_body["page_size"] == 1
    assert first_body["items"][0]["transaction_id"] == str(newer_transaction_id)
    assert first_body["items"][0]["framework_id"] == str(newer_framework_id)
    assert first_body["items"][0]["framework_title"] == "Newer Framework"
    assert first_body["items"][0]["amount"] == "249.00"
    assert first_body["items"][0]["status"] == "completed"
    assert first_body["items"][0]["license_type"] == "team"
    assert second_page.status_code == 200
    assert second_body["items"][0]["transaction_id"] == str(older_transaction_id)
    assert second_body["items"][0]["framework_id"] == str(older_framework_id)


async def test_purchase_invoice_redirects_when_pdf_exists(
    client: AsyncClient,
    purchase_history_context: dict[str, Any],
) -> None:
    """Ready invoices redirect to a short-lived private S3 URL."""
    operator_id = await create_user_with_roles(
        "invoice-ready@auracles.space",
        ["operator"],
    )
    transaction_id, _ = await create_purchase(operator_id, title="Invoice Ready")
    storage: FakeInvoiceStorage = purchase_history_context["storage"]
    first_response = await client.get(
        f"/v1/financials/purchases/{transaction_id}/invoice",
        headers=auth_headers(operator_id, ["operator"]),
    )
    assert first_response.status_code == 202

    async with async_session_factory() as session:
        invoice = await session.scalar(
            select(Invoice).where(
                Invoice.source_ref_type == "transaction",
                Invoice.source_ref_id == transaction_id,
                Invoice.doc_type == "sales_invoice",
            )
        )

    assert invoice is not None
    storage.existing_keys.add(invoice.s3_key)

    response = await client.get(
        f"/v1/financials/purchases/{transaction_id}/invoice",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert response.status_code == 302
    assert response.headers["location"] == (
        f"https://s3.test/auracles-reports-dev/{invoice.s3_key}?expires=900"
    )
    assert storage.presigned_get_requests == [
        ("auracles-reports-dev", invoice.s3_key, 900)
    ]


async def test_purchase_invoice_dispatches_generation_when_missing(
    client: AsyncClient,
    purchase_history_context: dict[str, Any],
) -> None:
    """Missing invoices dispatch generation and return 202."""
    operator_id = await create_user_with_roles(
        "invoice-missing@auracles.space",
        ["operator"],
    )
    transaction_id, _ = await create_purchase(operator_id, title="Invoice Missing")
    invoice_task: FakeInvoiceTask = purchase_history_context["invoice_task"]

    response = await client.get(
        f"/v1/financials/purchases/{transaction_id}/invoice",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert response.status_code == 202
    assert response.json() == {
        "transaction_id": str(transaction_id),
        "status": "generating",
    }
    assert invoice_task.dispatched == [str(transaction_id)]


async def test_purchase_invoice_is_issued_and_numbered(
    client: AsyncClient,
    purchase_history_context: dict[str, Any],
) -> None:
    """A settled purchase GET issues a numbered shared-ledger invoice row."""
    operator_id = await create_user_with_roles(
        "invoice-issued@auracles.space",
        ["operator"],
    )
    transaction_id, _ = await create_purchase(operator_id, title="Invoice Issued")
    del purchase_history_context

    response = await client.get(
        f"/v1/financials/purchases/{transaction_id}/invoice",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert response.status_code == 202
    async with async_session_factory() as session:
        invoice = await session.scalar(
            select(Invoice).where(
                Invoice.source_ref_type == "transaction",
                Invoice.source_ref_id == transaction_id,
                Invoice.doc_type == "sales_invoice",
            )
        )

    assert invoice is not None
    assert invoice.series == "AUR-INV"
    assert invoice.invoice_number.startswith("AUR-INV-")


async def test_purchase_invoice_hides_other_operator_transaction(
    client: AsyncClient,
    purchase_history_context: dict[str, Any],
) -> None:
    """Operators cannot access another Operator's invoice."""
    del purchase_history_context
    owner_id = await create_user_with_roles(
        "invoice-owner@auracles.space",
        ["operator"],
    )
    other_id = await create_user_with_roles(
        "invoice-other@auracles.space",
        ["operator"],
    )
    transaction_id, _ = await create_purchase(owner_id, title="Owned Invoice")

    response = await client.get(
        f"/v1/financials/purchases/{transaction_id}/invoice",
        headers=auth_headers(other_id, ["operator"]),
    )

    assert response.status_code == 404
