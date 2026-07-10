"""Unit tests for organization-payer Framework purchase and webhook grant.

Covers Task 5 of the "Organizations as Operators" sub-project: an org with
an active Operator capability and a Stripe customer on file can purchase a
Framework, and the Stripe webhook branch mints an org-owned License
(`licensee_org_id`) instead of an individual one. Maps to FR-FIN-* / FR-ORG-*
org-purchase behaviour described in task-5-brief.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.financials import service as financials_service
from app.modules.financials.models import Transaction
from app.modules.financials.schemas import PurchaseRequest
from app.modules.frameworks.models import Framework, License
from app.modules.organizations import operator_service
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.modules.webhooks import service as webhooks_service
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store the provider intent id and browser client secret."""
        self.id = payment_intent_id
        self.client_secret = client_secret


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org framework purchase tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def org_purchase_state() -> AsyncIterator[None]:
    """Reset purchase, framework, and organization rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete purchase-linked rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(License))
            await session.execute(delete(Transaction))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> User:
    """Create and return one verified user for org purchase tests."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
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
            await session.refresh(user)
            return user


async def _create_org(
    owner: User,
    *,
    stripe_customer_id: str | None = "cus_org_purchase_123",
) -> Organization:
    """Create one organization owned by `owner`, with an optional Stripe customer."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:8]}",
                name="Org Purchase Test Org",
                country="US",
                created_by=owner.id,
                stripe_customer_id=stripe_customer_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            await session.refresh(org)
            return org


async def _activate_operator_capability(org_id: UUID, owner_id: UUID) -> None:
    """Self-activate the org Operator capability."""
    async with async_session_factory() as session:
        await operator_service.activate_operator_capability(
            session,
            org_id=org_id,
            actor_id=owner_id,
        )


async def _suspend_operator_capability(org_id: UUID, admin_id: UUID) -> None:
    """Mark the org Operator capability suspended after activation."""
    async with async_session_factory() as session:
        await operator_service.admin_set_operator_capability_status(
            session,
            org_id=org_id,
            admin_id=admin_id,
            status_value="suspended",
        )


async def _create_framework(
    *,
    contributor_id: UUID | None,
    contributor_org_id: UUID | None,
    price: Decimal = Decimal("249.00"),
    license_types: list[str] | None = None,
) -> Framework:
    """Create and return one published Framework row for purchase tests."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                contributor_org_id=contributor_org_id,
                title="Org Purchase Framework",
                description="A framework row for org purchase tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["org-purchase"],
                price=price,
                currency="USD",
                license_types=license_types or ["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            await session.refresh(framework)
            return framework


def _patch_payment_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[Any]]:
    """Install a Stripe PaymentIntent test double and return its call log."""
    calls: dict[str, list[Any]] = {"payment_intents": []}

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: dict[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        """Record PaymentIntent creation and return a browser client secret."""
        calls["payment_intents"].append(
            {
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripePaymentIntent("pi_org_purchase_123", "pi_org_secret_123")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )
    return calls


@pytest.mark.asyncio
async def test_org_purchase_creates_pending_transaction_with_org_payer(
    migrated_database: None,
    org_purchase_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Org checkout stamps `payer_org_id` and leaves `payer_id` NULL."""
    del migrated_database, org_purchase_state
    contributor = await _create_user("org-purchase-contributor")
    owner = await _create_user("org-purchase-owner")
    org = await _create_org(owner)
    await _activate_operator_capability(org.id, owner.id)
    framework = await _create_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
        license_types=["single_user", "team"],
    )
    calls = _patch_payment_intent(monkeypatch)

    async with async_session_factory() as session:
        response = await financials_service.create_org_framework_purchase(
            session,
            org_id=org.id,
            actor=owner,
            framework_id=framework.id,
            payload=PurchaseRequest(license_type="team"),
        )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, response.transaction_id)

    assert response.provider == "stripe"
    assert response.client_secret == "pi_org_secret_123"
    assert transaction is not None
    assert transaction.payer_org_id == org.id
    assert transaction.payer_id is None
    assert transaction.payee_id == contributor.id
    assert transaction.status == "pending"
    assert calls["payment_intents"] == [
        {
            "customer_id": "cus_org_purchase_123",
            "amount": Decimal("249.00"),
            "currency": "USD",
            "metadata": {
                "transaction_id": str(transaction.id),
                "kind": "purchase",
                "framework_id": str(framework.id),
                "license_type": "team",
                "payer_org_id": str(org.id),
            },
            "idempotency_key": f"purchase:{transaction.id}",
        }
    ]


@pytest.mark.asyncio
async def test_org_purchase_self_deal_blocks_before_any_charge(
    migrated_database: None,
    org_purchase_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Buying a Framework the org itself sells is rejected before any Stripe call."""
    del migrated_database, org_purchase_state
    owner = await _create_user("org-purchase-owner")
    org = await _create_org(owner)
    await _activate_operator_capability(org.id, owner.id)
    framework = await _create_framework(
        contributor_id=None,
        contributor_org_id=org.id,
    )
    calls = _patch_payment_intent(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        async with async_session_factory() as session:
            await financials_service.create_org_framework_purchase(
                session,
                org_id=org.id,
                actor=owner,
                framework_id=framework.id,
                payload=PurchaseRequest(license_type="single_user"),
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "self_deal_conflict"
    assert calls["payment_intents"] == []
    async with async_session_factory() as session:
        transaction = await session.scalar(select(Transaction))
    assert transaction is None


@pytest.mark.asyncio
async def test_org_purchase_requires_payment_method_on_file(
    migrated_database: None,
    org_purchase_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org with no Stripe customer on file cannot start checkout."""
    del migrated_database, org_purchase_state
    contributor = await _create_user("org-purchase-contributor")
    owner = await _create_user("org-purchase-owner")
    org = await _create_org(owner, stripe_customer_id=None)
    await _activate_operator_capability(org.id, owner.id)
    framework = await _create_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
    )
    _patch_payment_intent(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        async with async_session_factory() as session:
            await financials_service.create_org_framework_purchase(
                session,
                org_id=org.id,
                actor=owner,
                framework_id=framework.id,
                payload=PurchaseRequest(license_type="single_user"),
            )

    assert exc_info.value.status_code == 402


@pytest.mark.asyncio
async def test_org_purchase_blocks_when_capability_suspended(
    migrated_database: None,
    org_purchase_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A suspended Operator capability blocks checkout with a specific error code."""
    del migrated_database, org_purchase_state
    contributor = await _create_user("org-purchase-contributor")
    owner = await _create_user("org-purchase-owner")
    admin = await _create_user("platform-admin")
    org = await _create_org(owner)
    await _activate_operator_capability(org.id, owner.id)
    await _suspend_operator_capability(org.id, admin.id)
    framework = await _create_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
    )
    _patch_payment_intent(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        async with async_session_factory() as session:
            await financials_service.create_org_framework_purchase(
                session,
                org_id=org.id,
                actor=owner,
                framework_id=framework.id,
                payload=PurchaseRequest(license_type="single_user"),
            )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "capability_suspended"


@pytest.mark.asyncio
async def test_org_purchase_rejects_second_license_on_same_framework(
    migrated_database: None,
    org_purchase_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second purchase attempt on an already-licensed Framework is a 409."""
    del migrated_database, org_purchase_state
    contributor = await _create_user("org-purchase-contributor")
    owner = await _create_user("org-purchase-owner")
    org = await _create_org(owner)
    await _activate_operator_capability(org.id, owner.id)
    framework = await _create_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                License(
                    framework_id=framework.id,
                    operator_id=None,
                    licensee_org_id=org.id,
                    license_type="team",
                    status="active",
                    version_at_grant="1.0.0",
                    seats_used=1,
                    seats_total=10,
                )
            )
    _patch_payment_intent(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        async with async_session_factory() as session:
            await financials_service.create_org_framework_purchase(
                session,
                org_id=org.id,
                actor=owner,
                framework_id=framework.id,
                payload=PurchaseRequest(license_type="single_user"),
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_webhook_org_branch_grants_org_license_and_completes_transaction(
    migrated_database: None,
    org_purchase_state: None,
) -> None:
    """The webhook org branch mints an org License, not an `operator_id` one."""
    del migrated_database, org_purchase_state
    contributor = await _create_user("org-purchase-contributor")
    owner = await _create_user("org-purchase-owner")
    org = await _create_org(owner)
    framework = await _create_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
    )
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=None,
                payer_org_id=org.id,
                payee_id=contributor.id,
                amount=Decimal("249.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("249.00"),
                transaction_type="purchase",
                status="pending",
                provider="stripe",
                provider_ref="pi_org_webhook_123",
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            transaction_id = transaction.id

    event = {
        "id": "evt_org_purchase_success",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_org_webhook_123",
                "metadata": {
                    "transaction_id": str(transaction_id),
                    "kind": "purchase",
                    "framework_id": str(framework.id),
                    "license_type": "team",
                    "payer_org_id": str(org.id),
                },
            }
        },
    }

    async with async_session_factory() as session:
        async with session.begin():
            returned_transaction_id, after_commit_work = (
                await webhooks_service._handle_purchase_succeeded(session, event)
            )

    assert returned_transaction_id == transaction_id
    assert after_commit_work == []
    async with async_session_factory() as session:
        stored_transaction = await session.get(Transaction, transaction_id)
        license_row = await session.scalar(
            select(License).where(License.framework_id == framework.id)
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_completed")
        )
    assert stored_transaction is not None
    assert stored_transaction.status == "completed"
    assert license_row is not None
    assert license_row.licensee_org_id == org.id
    assert license_row.operator_id is None
    assert license_row.transaction_id == transaction_id
    assert license_row.license_type == "team"
    assert license_row.seats_total == 10
    assert audit is not None
    assert audit.actor_id is None
    assert audit.target_type == "transaction"
    assert audit.metadata_["payer_org_id"] == str(org.id)


@pytest.mark.asyncio
async def test_individual_purchase_and_webhook_path_unchanged(
    migrated_database: None,
    org_purchase_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: individual checkout and webhook grant behavior is untouched."""
    del migrated_database, org_purchase_state
    contributor = await _create_user("org-purchase-contributor")
    operator = await _create_user("org-purchase-individual-operator")
    framework = await _create_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
    )
    calls = _patch_payment_intent(monkeypatch)

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Return a stable provider customer id for the individual operator."""
        del email, name, idempotency_key
        return SimpleNamespace(id="cus_individual_test")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_customer",
        fake_create_customer,
    )

    async with async_session_factory() as session:
        response = await financials_service.create_framework_purchase(
            session,
            operator,
            framework_id=framework.id,
            payload=PurchaseRequest(license_type="single_user"),
        )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, response.transaction_id)
    assert transaction is not None
    assert transaction.payer_id == operator.id
    assert transaction.payer_org_id is None
    assert calls["payment_intents"][0]["metadata"] == {
        "transaction_id": str(transaction.id),
        "kind": "purchase",
        "framework_id": str(framework.id),
        "license_type": "single_user",
    }

    event = {
        "id": "evt_individual_purchase_success",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": transaction.provider_ref,
                "metadata": {
                    "transaction_id": str(transaction.id),
                    "kind": "purchase",
                    "framework_id": str(framework.id),
                    "license_type": "single_user",
                },
            }
        },
    }
    async with async_session_factory() as session:
        async with session.begin():
            await webhooks_service._handle_purchase_succeeded(session, event)

    async with async_session_factory() as session:
        stored_transaction = await session.get(Transaction, transaction.id)
        license_row = await session.scalar(
            select(License).where(License.framework_id == framework.id)
        )
    assert stored_transaction is not None
    assert stored_transaction.status == "completed"
    assert license_row is not None
    assert license_row.operator_id == operator.id
    assert license_row.licensee_org_id is None
