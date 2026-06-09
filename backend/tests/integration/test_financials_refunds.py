"""Integration tests for Operator self-serve purchase refunds."""

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
from app.integrations.stripe import StripeProviderError
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import Artifact, ArtifactDownload
from app.shared.models.audit_log import AuditLog


class FakeStripeRefund:
    """Small stand-in for a Stripe refund result."""

    def __init__(self, refund_id: str, refund_status: str = "succeeded") -> None:
        """Store provider refund fields returned by the adapter."""
        self.id = refund_id
        self.status = refund_status


async def reset_refund_state() -> None:
    """Remove refund-flow rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(ArtifactDownload))
        await session.execute(delete(Artifact))
        await session.execute(delete(License))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def refund_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, list[Any]]]:
    """Reset state and replace Stripe refund calls with a test double."""
    await engine.dispose()
    await reset_refund_state()
    calls: dict[str, list[Any]] = {"refunds": []}

    async def fake_create_refund(
        *,
        payment_intent_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> FakeStripeRefund:
        """Record Stripe refund creation and return a provider id."""
        calls["refunds"].append(
            {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeRefund("re_refund_123")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_refund",
        fake_create_refund,
    )
    try:
        yield calls
    finally:
        await reset_refund_state()
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


async def create_completed_purchase(
    operator_id: UUID,
    *,
    created_at: datetime | None = None,
    with_download: bool = False,
) -> tuple[UUID, UUID]:
    """Create a completed purchase transaction and active license."""
    contributor_token = uuid4()
    contributor_id = await create_user_with_roles(
        f"refund-contributor-{contributor_token}@auracles.space",
        ["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Refundable Framework",
                description="Framework used by refund tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["refund"],
                price=Decimal("149.00"),
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("149.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("149.00"),
                transaction_type="purchase",
                status="completed",
                provider="stripe",
                provider_ref="pi_refund_123",
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
                status="active",
                version_at_grant=framework.version,
                seats_used=1,
                seats_total=10,
            )
            session.add(license_row)
            await session.flush()
            if with_download:
                artifact = Artifact(
                    framework_id=framework.id,
                    name="downloaded.pdf",
                    file_key=f"frameworks/{framework.id}/artifacts/downloaded.pdf",
                    file_size=1024,
                    mime_type="application/pdf",
                    scan_status="clean",
                    processing_status="processed",
                    current_for_framework=True,
                )
                session.add(artifact)
                await session.flush()
                session.add(
                    ArtifactDownload(
                        license_id=license_row.id,
                        artifact_id=artifact.id,
                        user_id=operator_id,
                        ip_address="127.0.0.1",
                    )
                )
            return transaction.id, license_row.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_operator_can_refund_completed_purchase_before_download(
    client: AsyncClient,
    refund_context: dict[str, list[Any]],
) -> None:
    """Eligible refunds call Stripe, mark the purchase refunded, and revoke access."""
    operator_id = await create_user_with_roles(
        "refund-operator@auracles.space",
        ["operator"],
    )
    transaction_id, license_id = await create_completed_purchase(operator_id)

    response = await client.post(
        f"/v1/financials/purchases/{transaction_id}/refund",
        headers=auth_headers(operator_id, ["operator"]),
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.get(License, license_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_refunded")
        )

    assert response.status_code == 200
    assert response.json() == {
        "transaction_id": str(transaction_id),
        "provider": "stripe",
        "refund_id": "re_refund_123",
        "status": "refunded",
    }
    assert refund_context["refunds"] == [
        {
            "payment_intent_id": "pi_refund_123",
            "amount": Decimal("149.00"),
            "currency": "USD",
            "idempotency_key": f"refund:{transaction_id}",
        }
    ]
    assert transaction is not None
    assert transaction.status == "refunded"
    assert license_row is not None
    assert license_row.status == "revoked"
    assert audit is not None
    assert audit.target_id == transaction_id
    assert audit.metadata_["refund_ref"] == "****_123"


async def test_refund_rejects_downloaded_or_expired_purchases(
    client: AsyncClient,
    refund_context: dict[str, list[Any]],
) -> None:
    """Refunds are unavailable after artifact download or after the 48h window."""
    operator_id = await create_user_with_roles(
        "refund-blocked@auracles.space",
        ["operator"],
    )
    downloaded_transaction_id, _ = await create_completed_purchase(
        operator_id,
        with_download=True,
    )
    expired_transaction_id, _ = await create_completed_purchase(
        operator_id,
        created_at=datetime.now(UTC) - timedelta(hours=49),
    )

    downloaded = await client.post(
        f"/v1/financials/purchases/{downloaded_transaction_id}/refund",
        headers=auth_headers(operator_id, ["operator"]),
    )
    expired = await client.post(
        f"/v1/financials/purchases/{expired_transaction_id}/refund",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert downloaded.status_code == 422
    assert expired.status_code == 422
    assert refund_context["refunds"] == []


async def test_refund_hides_other_operator_purchase(
    client: AsyncClient,
    refund_context: dict[str, list[Any]],
) -> None:
    """Operators cannot refund purchases they do not own."""
    owner_id = await create_user_with_roles("refund-owner@auracles.space", ["operator"])
    other_id = await create_user_with_roles("refund-other@auracles.space", ["operator"])
    transaction_id, _ = await create_completed_purchase(owner_id)

    response = await client.post(
        f"/v1/financials/purchases/{transaction_id}/refund",
        headers=auth_headers(other_id, ["operator"]),
    )

    assert response.status_code == 404
    assert refund_context["refunds"] == []


async def test_refund_provider_failure_preserves_local_purchase_state(
    client: AsyncClient,
    refund_context: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stripe failure returns 502 without revoking the local license."""
    operator_id = await create_user_with_roles(
        "refund-failure@auracles.space",
        ["operator"],
    )
    transaction_id, license_id = await create_completed_purchase(operator_id)

    async def fake_create_refund_failure(
        *,
        payment_intent_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> FakeStripeRefund:
        """Simulate Stripe failing before local state changes."""
        refund_context["refunds"].append(
            {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        raise StripeProviderError("Stripe unavailable.")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_refund",
        fake_create_refund_failure,
    )

    response = await client.post(
        f"/v1/financials/purchases/{transaction_id}/refund",
        headers=auth_headers(operator_id, ["operator"]),
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.get(License, license_id)

    assert response.status_code == 502
    assert transaction is not None
    assert transaction.status == "completed"
    assert license_row is not None
    assert license_row.status == "active"
