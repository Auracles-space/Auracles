"""Integration tests for Operator framework purchase initiation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.integrations.stripe import StripeProviderError
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.collections import service as collections_service
from app.modules.collections.models import (
    CollectionFramework,
    CollectionPurchaseSnapshot,
    FrameworkCollection,
)
from app.modules.financials import service as financials_service
from app.modules.financials.models import Transaction
from app.modules.financials.schemas import PurchaseRequest
from app.modules.frameworks.models import Framework, License
from app.shared.models.audit_log import AuditLog


class FakeStripeCustomer:
    """Small stand-in for a Stripe Customer result."""

    def __init__(self, customer_id: str) -> None:
        """Store the provider customer id."""
        self.id = customer_id


class FakeStripePaymentIntent:
    """Small stand-in for a Stripe PaymentIntent result."""

    def __init__(self, payment_intent_id: str, client_secret: str) -> None:
        """Store the provider intent id and browser client secret."""
        self.id = payment_intent_id
        self.client_secret = client_secret


async def reset_purchase_state() -> None:
    """Remove purchase-flow rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(CollectionPurchaseSnapshot))
        await session.execute(delete(License))
        await session.execute(delete(Transaction))
        await session.execute(delete(CollectionFramework))
        await session.execute(delete(FrameworkCollection))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for purchase-flow tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def purchase_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, list[Any]]]:
    """Reset marketplace state and replace Stripe calls with test doubles."""
    calls: dict[str, list[Any]] = {
        "customers": [],
        "payment_intents": [],
    }

    await engine.dispose()
    await reset_purchase_state()

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Record Customer creation and return a stable provider id."""
        calls["customers"].append(
            {"email": email, "name": name, "idempotency_key": idempotency_key}
        )
        return FakeStripeCustomer("cus_purchase_123")

    async def fake_create_payment_intent(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
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
        return FakeStripePaymentIntent("pi_purchase_123", "pi_secret_123")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_customer",
        fake_create_customer,
    )
    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )
    try:
        yield calls
    finally:
        await reset_purchase_state()
        await engine.dispose()


async def create_user_with_roles(
    email: str,
    roles: list[str],
    *,
    kyc_status: str = "verified",
) -> UUID:
    """Create a verified user with approved roles and the given KYC status."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status=kyc_status,
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


async def suspend_user(user_id: UUID) -> None:
    """Mark one user suspended for purchase visibility tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.suspended_at = datetime.now(UTC)


async def create_published_framework(
    contributor_id: UUID,
    *,
    price: Decimal = Decimal("149.00"),
    currency: str = "USD",
    license_types: list[str] | None = None,
) -> UUID:
    """Create a published Framework available in checkout."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Revenue Operations Playbook",
                description="A practical operating system for revenue teams.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["revenue", "operations"],
                price=price,
                currency=currency,
                license_types=license_types or ["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            return framework.id


async def create_published_collection(
    contributor_id: UUID,
    *,
    framework_ids: list[UUID],
    bundle_price: Decimal = Decimal("600.00"),
) -> UUID:
    """Create a published Collection with the supplied member Frameworks."""
    async with async_session_factory() as session:
        async with session.begin():
            collection = FrameworkCollection(
                contributor_id=contributor_id,
                title="Risk Operations Bundle",
                description="A discounted set of risk operations Frameworks.",
                bundle_price=bundle_price,
                currency="USD",
                status="published",
            )
            session.add(collection)
            await session.flush()
            for framework_id in framework_ids:
                session.add(
                    CollectionFramework(
                        collection_id=collection.id,
                        framework_id=framework_id,
                    )
                )
            return collection.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_operator_can_start_stripe_purchase_without_license_grant(
    client: AsyncClient,
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
) -> None:
    """Checkout creates a pending transaction, not a License grant."""
    contributor_id = await create_user_with_roles(
        "purchase-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "purchase-operator@auracles.space",
        ["operator"],
    )
    framework_id = await create_published_framework(
        contributor_id,
        license_types=["single_user", "team", "organizational"],
    )

    response = await client.post(
        f"/v1/financials/purchase/{framework_id}",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "team"},
    )

    async with async_session_factory() as session:
        operator = await session.get(User, operator_id)
        transaction = await session.scalar(select(Transaction))
        license_row = await session.scalar(select(License))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_initiated")
        )

    body = response.json()
    assert response.status_code == 200
    assert body["provider"] == "stripe"
    assert body["client_secret"] == "pi_secret_123"
    assert UUID(body["transaction_id"])
    assert operator is not None
    assert operator.stripe_customer_id == "cus_purchase_123"
    assert transaction is not None
    assert transaction.payer_id == operator_id
    assert transaction.payee_id == contributor_id
    assert transaction.amount == Decimal("149.00")
    assert transaction.currency == "USD"
    assert transaction.transaction_type == "purchase"
    assert transaction.status == "pending"
    assert transaction.provider == "stripe"
    assert transaction.provider_ref == "pi_purchase_123"
    assert transaction.ref_id == framework_id
    assert transaction.ref_type == "framework"
    assert license_row is None
    assert audit is not None
    assert audit.target_id == transaction.id
    assert audit.metadata_["license_type"] == "team"
    assert purchase_context["customers"] == [
        {
            "email": "purchase-operator@auracles.space",
            "name": "purchase-operator",
            "idempotency_key": f"stripe_customer:{operator_id}",
        }
    ]
    assert purchase_context["payment_intents"] == [
        {
            "customer_id": "cus_purchase_123",
            "amount": Decimal("149.00"),
            "currency": "USD",
            "metadata": {
                "transaction_id": str(transaction.id),
                "kind": "purchase",
                "framework_id": str(framework_id),
                "license_type": "team",
            },
            "idempotency_key": f"purchase:{transaction.id}",
        }
    ]


async def test_unverified_operator_cannot_start_purchase(
    client: AsyncClient,
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
) -> None:
    """Purchasing requires verified KYC; an unverified Operator is blocked (403)."""
    contributor_id = await create_user_with_roles(
        "kyc-gate-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "kyc-gate-operator@auracles.space",
        ["operator"],
        kyc_status="unverified",
    )
    framework_id = await create_published_framework(
        contributor_id,
        license_types=["single_user", "team", "organizational"],
    )

    response = await client.post(
        f"/v1/financials/purchase/{framework_id}",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "team"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "kyc_required"


async def test_operator_cannot_purchase_framework_from_suspended_contributor(
    client: AsyncClient,
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
) -> None:
    """Direct purchase routes treat suspended contributors as not found."""
    del migrated_database, purchase_context
    contributor_id = await create_user_with_roles(
        "suspended-purchase-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "suspended-purchase-operator@auracles.space",
        ["operator"],
    )
    framework_id = await create_published_framework(contributor_id)
    await suspend_user(contributor_id)

    response = await client.post(
        f"/v1/financials/purchase/{framework_id}",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "single_user"},
    )

    assert response.status_code == 404


async def test_operator_cannot_purchase_collection_from_suspended_contributor(
    client: AsyncClient,
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
) -> None:
    """Collection checkout treats suspended contributors as not found."""
    del migrated_database, purchase_context
    contributor_id = await create_user_with_roles(
        "suspended-collection-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "suspended-collection-operator@auracles.space",
        ["operator"],
    )
    first_framework_id = await create_published_framework(contributor_id)
    second_framework_id = await create_published_framework(
        contributor_id,
        price=Decimal("199.00"),
    )
    collection_id = await create_published_collection(
        contributor_id,
        framework_ids=[first_framework_id, second_framework_id],
        bundle_price=Decimal("250.00"),
    )
    await suspend_user(contributor_id)

    response = await client.post(
        f"/v1/financials/collections/{collection_id}/purchase",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "single_user"},
    )

    assert response.status_code == 404


async def test_operator_can_start_collection_purchase_with_member_snapshot(
    client: AsyncClient,
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
) -> None:
    """Collection checkout snapshots all members and mints no new Licenses."""
    contributor_id = await create_user_with_roles(
        "collection-purchase-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "collection-purchase-operator@auracles.space",
        ["operator"],
    )
    first_framework_id = await create_published_framework(
        contributor_id,
        price=Decimal("400.00"),
        license_types=["single_user", "team"],
    )
    second_framework_id = await create_published_framework(
        contributor_id,
        price=Decimal("500.00"),
        license_types=["single_user", "team"],
    )
    collection_id = await create_published_collection(
        contributor_id,
        framework_ids=[first_framework_id, second_framework_id],
        bundle_price=Decimal("700.00"),
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                License(
                    framework_id=first_framework_id,
                    operator_id=operator_id,
                    license_type="team",
                    status="active",
                    version_at_grant="1.0.0",
                )
            )

    response = await client.post(
        f"/v1/financials/collections/{collection_id}/purchase",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "team"},
    )

    async with async_session_factory() as session:
        operator = await session.get(User, operator_id)
        transaction = await session.scalar(
            select(Transaction).where(Transaction.ref_type == "collection")
        )
        snapshots = (
            (
                await session.execute(
                    select(CollectionPurchaseSnapshot).order_by(
                        CollectionPurchaseSnapshot.framework_id
                    )
                )
            )
            .scalars()
            .all()
        )
        licenses = (
            (
                await session.execute(
                    select(License).where(License.operator_id == operator_id)
                )
            )
            .scalars()
            .all()
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "collection_purchase_initiated")
        )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "stripe"
    assert body["client_secret"] == "pi_secret_123"
    assert UUID(body["transaction_id"])
    assert operator is not None
    assert operator.stripe_customer_id == "cus_purchase_123"
    assert transaction is not None
    assert transaction.id == UUID(body["transaction_id"])
    assert transaction.payer_id == operator_id
    assert transaction.payee_id == contributor_id
    assert transaction.amount == Decimal("700.00")
    assert transaction.transaction_type == "purchase"
    assert transaction.status == "pending"
    assert transaction.provider == "stripe"
    assert transaction.provider_ref == "pi_purchase_123"
    assert transaction.ref_id == collection_id
    assert transaction.ref_type == "collection"
    assert len(snapshots) == 2
    assert {snapshot.framework_id for snapshot in snapshots} == {
        first_framework_id,
        second_framework_id,
    }
    assert {
        snapshot.framework_id: snapshot.already_owned for snapshot in snapshots
    } == {first_framework_id: True, second_framework_id: False}
    assert {license_row.framework_id for license_row in licenses} == {
        first_framework_id
    }
    assert audit is not None
    assert audit.target_id == transaction.id
    assert audit.metadata_["collection_id"] == str(collection_id)
    assert audit.metadata_["missing_member_count"] == 1
    assert purchase_context["payment_intents"] == [
        {
            "customer_id": "cus_purchase_123",
            "amount": Decimal("700.00"),
            "currency": "USD",
            "metadata": {
                "kind": "collection",
                "transaction_id": str(transaction.id),
                "collection_id": str(collection_id),
            },
            "idempotency_key": f"collection_purchase:{transaction.id}",
        }
    ]


async def test_collection_purchase_service_directly_snapshots_only_missing_members(
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
) -> None:
    """Collection checkout service snapshots owned members before charging."""
    contributor_id = await create_user_with_roles(
        "collection-direct-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "collection-direct-operator@auracles.space",
        ["operator"],
    )
    first_framework_id = await create_published_framework(
        contributor_id,
        price=Decimal("401.00"),
        license_types=["single_user", "team"],
    )
    second_framework_id = await create_published_framework(
        contributor_id,
        price=Decimal("599.00"),
        license_types=["single_user", "team"],
    )
    collection_id = await create_published_collection(
        contributor_id,
        framework_ids=[first_framework_id, second_framework_id],
        bundle_price=Decimal("700.00"),
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                License(
                    framework_id=first_framework_id,
                    operator_id=operator_id,
                    license_type="team",
                    status="active",
                    version_at_grant="1.0.0",
                )
            )

    operator = cast(
        User,
        SimpleNamespace(
            id=operator_id,
            email="collection-direct-operator@auracles.space",
            display_name="collection-direct-operator",
            stripe_customer_id=None,
        ),
    )
    async with async_session_factory() as session:
        response = await collections_service.create_collection_purchase(
            db=session,
            operator=operator,
            collection_id=collection_id,
            payload=PurchaseRequest(license_type="team"),
        )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, response.transaction_id)
        snapshots = (
            (
                await session.execute(
                    select(CollectionPurchaseSnapshot).order_by(
                        CollectionPurchaseSnapshot.list_price_at_purchase
                    )
                )
            )
            .scalars()
            .all()
        )

    assert response.provider == "stripe"
    assert response.client_secret == "pi_secret_123"
    assert transaction is not None
    assert transaction.ref_type == "collection"
    assert transaction.provider_ref == "pi_purchase_123"
    assert [snapshot.already_owned for snapshot in snapshots] == [True, False]
    assert purchase_context["customers"] == [
        {
            "email": "collection-direct-operator@auracles.space",
            "name": "collection-direct-operator",
            "idempotency_key": f"stripe_customer:{operator_id}",
        }
    ]
    assert purchase_context["payment_intents"][0]["metadata"] == {
        "kind": "collection",
        "transaction_id": str(response.transaction_id),
        "collection_id": str(collection_id),
    }


async def test_collection_purchase_rejects_invalid_or_fully_owned_bundle(
    client: AsyncClient,
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
) -> None:
    """Collection checkout revalidates bundle rules before charging."""
    del purchase_context
    contributor_id = await create_user_with_roles(
        "collection-reject-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "collection-reject-operator@auracles.space",
        ["operator"],
    )
    first_framework_id = await create_published_framework(
        contributor_id,
        price=Decimal("400.00"),
        license_types=["single_user"],
    )
    second_framework_id = await create_published_framework(
        contributor_id,
        price=Decimal("500.00"),
        license_types=["single_user"],
    )
    collection_id = await create_published_collection(
        contributor_id,
        framework_ids=[first_framework_id, second_framework_id],
        bundle_price=Decimal("700.00"),
    )

    self_purchase = await client.post(
        f"/v1/financials/collections/{collection_id}/purchase",
        headers=auth_headers(contributor_id, ["operator"]),
        json={"license_type": "single_user"},
    )
    unsupported_license = await client.post(
        f"/v1/financials/collections/{collection_id}/purchase",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "team"},
    )
    async with async_session_factory() as session:
        async with session.begin():
            for framework_id in [first_framework_id, second_framework_id]:
                session.add(
                    License(
                        framework_id=framework_id,
                        operator_id=operator_id,
                        license_type="single_user",
                        status="active",
                        version_at_grant="1.0.0",
                    )
                )
    fully_owned = await client.post(
        f"/v1/financials/collections/{collection_id}/purchase",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "single_user"},
    )

    assert self_purchase.status_code == 409
    assert unsupported_license.status_code == 422
    assert fully_owned.status_code == 409
    assert fully_owned.json()["detail"] == "Collection is already fully licensed."


async def test_purchase_rejects_non_self_serve_and_unavailable_frameworks(
    client: AsyncClient,
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
) -> None:
    """Purchase initiation blocks wrong roles and non-checkout license types."""
    del purchase_context
    contributor_id = await create_user_with_roles(
        "reject-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "reject-operator@auracles.space",
        ["operator"],
    )
    framework_id = await create_published_framework(
        contributor_id,
        license_types=["single_user"],
    )

    wrong_role = await client.post(
        f"/v1/financials/purchase/{framework_id}",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={"license_type": "single_user"},
    )
    enterprise = await client.post(
        f"/v1/financials/purchase/{framework_id}",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "enterprise"},
    )
    unsupported_type = await client.post(
        f"/v1/financials/purchase/{framework_id}",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "team"},
    )

    assert wrong_role.status_code == 403
    assert enterprise.status_code == 422
    assert unsupported_type.status_code == 422


async def test_failed_payment_provider_marks_purchase_transaction_failed(
    client: AsyncClient,
    migrated_database: None,
    purchase_context: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider failure leaves no License and marks the transaction failed."""
    contributor_id = await create_user_with_roles(
        "failed-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "failed-operator@auracles.space",
        ["operator"],
    )
    framework_id = await create_published_framework(contributor_id)

    async def fake_create_payment_intent_failure(
        *,
        customer_id: str,
        amount: Decimal,
        currency: str,
        metadata: Mapping[str, str],
        idempotency_key: str | None = None,
    ) -> FakeStripePaymentIntent:
        """Simulate a Stripe outage after the local transaction is created."""
        purchase_context["payment_intents"].append(
            {
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
                "metadata": dict(metadata),
                "idempotency_key": idempotency_key,
            }
        )
        raise StripeProviderError("Stripe unavailable.")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent_failure,
    )

    response = await client.post(
        f"/v1/financials/purchase/{framework_id}",
        headers=auth_headers(operator_id, ["operator"]),
        json={"license_type": "single_user"},
    )

    async with async_session_factory() as session:
        transaction = await session.scalar(select(Transaction))
        license_row = await session.scalar(select(License))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_failed")
        )

    assert response.status_code == 502
    assert transaction is not None
    assert transaction.status == "failed"
    assert transaction.provider_ref is None
    assert license_row is None
    assert audit is not None
    assert audit.target_id == transaction.id
