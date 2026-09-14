"""Integration tests for attestation invoice and statement endpoints (Module 6d)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.integrations import s3
from app.modules.attestation.models import Attestation
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, Transaction
from app.modules.invoicing.models import Invoice, InvoiceCounter
from app.modules.notifications.models import Notification, NotificationDeliveryMarker
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import invoicing as invoicing_tasks

pytestmark = pytest.mark.asyncio


class FakeDocumentStorage:
    """S3 storage double for lazy invoice generation + redirects."""

    def __init__(self) -> None:
        """Create empty object and presign state."""
        self.existing_keys: set[str] = set()
        self.presigned_get_requests: list[tuple[str, str, int]] = []
        self.uploads: dict[str, bytes] = {}

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return whether a document already exists in the fake bucket."""
        return key in self.existing_keys

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Return a deterministic fake presigned GET URL."""
        self.presigned_get_requests.append((bucket, key, expires_in))
        return f"https://s3.test/{bucket}/{key}?expires={expires_in}"

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Persist uploaded PDF bytes and mark the key as ready."""
        self.uploads[f"{bucket}/{key}/{mime_type}"] = body
        self.existing_keys.add(key)


async def _reset_state() -> None:
    """Clear attestation/invoice rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(NotificationDeliveryMarker))
            await session.execute(delete(Notification))
            await session.execute(delete(Invoice))
            await session.execute(delete(InvoiceCounter))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the integration database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Reset invoice-endpoint state before and after each test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


@pytest.fixture
def fake_document_storage(monkeypatch: pytest.MonkeyPatch) -> FakeDocumentStorage:
    """Replace S3 storage with a deterministic in-memory document store."""
    fake = FakeDocumentStorage()
    monkeypatch.setattr(s3, "storage", fake)
    monkeypatch.setattr(
        invoicing_tasks,
        "render_invoice_pdf",
        lambda invoice, *, line_item_label: b"%PDF-ATTESTATION-INVOICE%",
    )
    return fake


def _auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for one authenticated test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def _make_user(role: str, prefix: str) -> User:
    """Create one verified user with one approved role."""
    async with async_session_factory() as session:
        user = User(
            email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name=prefix,
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC)))
        await session.commit()
        await session.refresh(user)
    return user


async def _seed_attestation(status: str) -> dict[str, UUID]:
    """Create one attestation, fee transaction, and released escrow."""
    requestor = await _make_user("operator", "requestor")
    attestor = await _make_user("attestor", "attestor")

    async with async_session_factory() as session:
        org = Organization(
            slug=f"inv-org-{uuid4().hex[:6]}",
            name="Invoice Org LLP",
            country="US",
            created_by=attestor.id,
        )
        session.add(org)
        await session.flush()
        member = OrgMember(org_id=org.id, user_id=attestor.id, role="owner")
        session.add(member)
        session.add(
            OrgAttestorProfile(
                org_id=org.id,
                specializations=[],
                jurisdictions=[],
                active=True,
            )
        )
        await session.flush()
        attestation = Attestation(
            target_type="framework",
            target_id=uuid4(),
            requestor_id=requestor.id,
            attestor_org_id=org.id,
            reviewing_member_id=member.id,
            status=status,
            outcome="approved" if status == "closed" else None,
            review_type="expert",
            requested_specializations=[],
            requested_jurisdictions=[],
            fee_amount=Decimal("500.00"),
            currency="USD",
            report_published_eligible=status == "closed",
            closed_at=datetime.now(UTC) if status == "closed" else None,
        )
        session.add(attestation)
        await session.flush()
        transaction = Transaction(
            payer_id=requestor.id,
            payee_id=None,
            amount=Decimal("500.00"),
            currency="USD",
            platform_commission=Decimal("0.00"),
            net_amount=Decimal("500.00"),
            transaction_type="attestation_fee",
            status="completed",
            provider="stripe",
            provider_ref=f"pi_attestation_{uuid4().hex[:8]}",
            ref_id=attestation.id,
            ref_type="attestation",
        )
        session.add(transaction)
        await session.flush()
        escrow = Escrow(
            ref_id=attestation.id,
            ref_type="attestation",
            amount=Decimal("500.00"),
            currency="USD",
            status="released",
            release_conditions={},
            transaction_id=transaction.id,
            released_at=datetime.now(UTC),
        )
        session.add(escrow)
        await session.flush()
        attestation.escrow_id = escrow.id
        await session.commit()

    return {
        "attestation_id": attestation.id,
        "requestor_id": requestor.id,
        "attestor_id": attestor.id,
    }


async def test_requestor_gets_tax_invoice(
    client: AsyncClient,
    clean_state,
    fake_document_storage: FakeDocumentStorage,
) -> None:
    """Requestor GET on a settled attestation returns 202 then 302."""
    del clean_state
    seeded = await _seed_attestation("closed")
    requestor_headers = _auth_headers(seeded["requestor_id"], ["operator"])

    first = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/invoice",
        headers=requestor_headers,
    )

    assert first.status_code == 202
    async with async_session_factory() as session:
        invoice = await session.scalar(
            select(Invoice).where(
                Invoice.source_ref_type == "attestation",
                Invoice.source_ref_id == seeded["attestation_id"],
                Invoice.doc_type == "sales_invoice",
            )
        )

    assert invoice is not None
    invoice_key, pdf_bytes = await invoicing_tasks._generate_invoice_document(
        str(invoice.id)
    )
    fake_document_storage.upload_bytes(
        "auracles-reports-dev",
        invoice_key,
        pdf_bytes,
        "application/pdf",
    )

    second = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/invoice",
        headers=requestor_headers,
    )

    assert second.status_code == 302
    assert second.headers["location"] == (
        f"https://s3.test/auracles-reports-dev/{invoice.s3_key}?expires=900"
    )
    assert fake_document_storage.presigned_get_requests == [
        ("auracles-reports-dev", invoice.s3_key, 900)
    ]


async def test_unsettled_attestation_invoice_409(
    client: AsyncClient,
    clean_state,
    fake_document_storage: FakeDocumentStorage,
) -> None:
    """An attestation whose fee is not yet released returns 409."""
    del clean_state, fake_document_storage
    seeded = await _seed_attestation("report_submitted")

    response = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/invoice",
        headers=_auth_headers(seeded["requestor_id"], ["operator"]),
    )

    assert response.status_code == 409


async def test_attestor_cannot_fetch_tax_invoice(
    client: AsyncClient,
    clean_state,
    fake_document_storage: FakeDocumentStorage,
) -> None:
    """The attestor is not allowed to fetch the buyer tax invoice."""
    del clean_state, fake_document_storage
    seeded = await _seed_attestation("closed")

    response = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/invoice",
        headers=_auth_headers(seeded["attestor_id"], ["attestor"]),
    )

    assert response.status_code == 403


async def test_admin_tax_invoice_access_is_audited(
    client: AsyncClient,
    clean_state,
    fake_document_storage: FakeDocumentStorage,
) -> None:
    """Admin cross-party tax-invoice access persists a committed audit row."""
    del fake_document_storage
    seeded = await _seed_attestation("closed")
    admin = await _make_user("admin", "admin")

    response = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/invoice",
        headers=_auth_headers(admin.id, ["admin"]),
    )

    assert response.status_code == 202
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == admin.id,
                AuditLog.action == "attestation_invoice_admin_accessed",
                AuditLog.target_id == seeded["attestation_id"],
            )
        )

    assert audit is not None


async def test_attestor_gets_earnings_statement(
    client: AsyncClient,
    clean_state,
    fake_document_storage: FakeDocumentStorage,
) -> None:
    """Attestor GET returns 202 then 302 with a netted earnings statement."""
    del clean_state
    seeded = await _seed_attestation("closed")
    attestor_headers = _auth_headers(seeded["attestor_id"], ["attestor"])

    first = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/earnings-statement",
        headers=attestor_headers,
    )

    assert first.status_code == 202
    async with async_session_factory() as session:
        invoice = await session.scalar(
            select(Invoice).where(
                Invoice.source_ref_type == "attestation",
                Invoice.source_ref_id == seeded["attestation_id"],
                Invoice.doc_type == "earnings_statement",
            )
        )

    assert invoice is not None
    assert invoice.series == "AUR-ERN"
    assert invoice.commission_rate == Decimal("0.1000")
    assert invoice.net_amount == Decimal("450.00")

    invoice_key, pdf_bytes = await invoicing_tasks._generate_invoice_document(
        str(invoice.id)
    )
    fake_document_storage.upload_bytes(
        "auracles-reports-dev",
        invoice_key,
        pdf_bytes,
        "application/pdf",
    )

    second = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/earnings-statement",
        headers=attestor_headers,
    )

    assert second.status_code == 302
    assert second.headers["location"] == (
        f"https://s3.test/auracles-reports-dev/{invoice.s3_key}?expires=900"
    )


async def test_requestor_cannot_fetch_earnings_statement(
    client: AsyncClient,
    clean_state,
    fake_document_storage: FakeDocumentStorage,
) -> None:
    """The requestor cannot fetch the attestor-only earnings statement."""
    del clean_state, fake_document_storage
    seeded = await _seed_attestation("closed")

    response = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/earnings-statement",
        headers=_auth_headers(seeded["requestor_id"], ["operator"]),
    )

    assert response.status_code == 403


async def test_admin_earnings_statement_access_is_audited(
    client: AsyncClient,
    clean_state,
    fake_document_storage: FakeDocumentStorage,
) -> None:
    """Admin cross-party earnings-statement access persists a committed audit row."""
    del fake_document_storage
    seeded = await _seed_attestation("closed")
    admin = await _make_user("admin", "admin")

    response = await client.get(
        f"/v1/attestations/{seeded['attestation_id']}/earnings-statement",
        headers=_auth_headers(admin.id, ["admin"]),
    )

    assert response.status_code == 202
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == admin.id,
                AuditLog.action == "attestation_earnings_statement_admin_accessed",
                AuditLog.target_id == seeded["attestation_id"],
            )
        )

    assert audit is not None
