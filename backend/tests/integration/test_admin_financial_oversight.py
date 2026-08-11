"""Integration tests for the admin financial oversight endpoints.

Read-only surface making money movement visible: the transaction directory, a
per-payment timeline reconstructed from the financial ledger, escrow holdings,
webhook delivery (including the errors nobody could previously read), and the
financial slice of the audit log.

All of it is admin-only, and none of it may expose payment credentials.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, FinancialEvent, Transaction
from app.modules.webhooks.models import WebhookEvent
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


async def reset_oversight_state() -> None:
    """Remove financial oversight test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(FinancialEvent))
        await session.execute(delete(WebhookEvent))
        await session.execute(delete(Escrow))
        await session.execute(delete(Transaction))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for admin oversight tests."""
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
async def oversight_context() -> AsyncIterator[None]:
    """Reset auth and financial state around each test."""
    await engine.dispose()
    await reset_oversight_state()
    try:
        yield
    finally:
        await reset_oversight_state()
        await engine.dispose()


async def _create_user(*, role: str) -> UUID:
    """Create a verified user holding one role."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{role}-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name=role.title(),
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC))
            )
        return user.id


async def _create_transaction(
    *,
    payer_id: UUID,
    status: str,
    provider_ref: str,
    transaction_type: str = "purchase",
) -> UUID:
    """Create one transaction row for the directory to return."""
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=payer_id,
                amount=Decimal("500.00"),
                currency="NGN",
                platform_commission=Decimal("50.00"),
                net_amount=Decimal("450.00"),
                transaction_type=transaction_type,
                status=status,
                provider="paystack",
                provider_ref=provider_ref,
            )
            session.add(transaction)
            await session.flush()
            return transaction.id


def _auth_headers(user_id: UUID, *, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a user with the given roles."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_lists_transactions_with_failure_cause(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """The directory surfaces why a failed payment failed, not just that it did.

    `transactions.status` alone reads `failed` with no cause; the directory
    joins the newest ledger reason so a failure is triageable from the list.
    """
    del migrated_database, oversight_context
    admin_id = await _create_user(role="admin")
    payer_id = await _create_user(role="operator")
    transaction_id = await _create_transaction(
        payer_id=payer_id,
        status="failed",
        provider_ref="ref_failed_1",
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                FinancialEvent(
                    entity_type="transaction",
                    entity_id=transaction_id,
                    event_type="purchase_failed",
                    from_status="pending",
                    to_status="failed",
                    reason_code="insufficient_funds",
                    reason_message="Declined by issuing bank.",
                )
            )

    response = await client.get(
        "/v1/admin/transactions",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["transaction_id"] == str(transaction_id)
    assert item["status"] == "failed"
    assert item["provider"] == "paystack"
    assert item["amount"] == "500.00"
    assert item["currency"] == "NGN"
    assert item["failure_reason_code"] == "insufficient_funds"


async def test_admin_filters_transactions_by_status_and_provider_ref(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """Filters narrow the directory to one payment for reconciliation."""
    del migrated_database, oversight_context
    admin_id = await _create_user(role="admin")
    payer_id = await _create_user(role="operator")
    await _create_transaction(
        payer_id=payer_id,
        status="failed",
        provider_ref="ref_failed_2",
    )
    completed_id = await _create_transaction(
        payer_id=payer_id,
        status="completed",
        provider_ref="ref_done_2",
    )

    by_status = await client.get(
        "/v1/admin/transactions",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"status": "completed"},
    )
    by_ref = await client.get(
        "/v1/admin/transactions",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"provider_ref": "ref_done_2"},
    )

    assert by_status.status_code == 200
    assert by_status.json()["total"] == 1
    assert by_status.json()["items"][0]["transaction_id"] == str(completed_id)
    assert by_ref.status_code == 200
    assert by_ref.json()["total"] == 1
    assert by_ref.json()["items"][0]["transaction_id"] == str(completed_id)


async def test_admin_reads_transaction_timeline_in_order(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """The detail view reconstructs one payment's history from the ledger.

    This is the trace the ledger exists for: the status column keeps only the
    final value, so the retry that preceded a failure is visible only here.
    """
    del migrated_database, oversight_context
    admin_id = await _create_user(role="admin")
    payer_id = await _create_user(role="operator")
    transaction_id = await _create_transaction(
        payer_id=payer_id,
        status="failed",
        provider_ref="ref_traced",
    )
    async with async_session_factory() as session:
        async with session.begin():
            for event_type, from_status, to_status in (
                ("purchase_initiated", None, "pending"),
                ("purchase_failed", "pending", "failed"),
            ):
                session.add(
                    FinancialEvent(
                        entity_type="transaction",
                        entity_id=transaction_id,
                        event_type=event_type,
                        from_status=from_status,
                        to_status=to_status,
                    )
                )
                await session.flush()

    response = await client.get(
        f"/v1/admin/transactions/{transaction_id}",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transaction"]["transaction_id"] == str(transaction_id)
    assert [event["event_type"] for event in body["timeline"]] == [
        "purchase_initiated",
        "purchase_failed",
    ]


async def test_admin_transaction_detail_404s_for_unknown_payment(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """An unknown transaction id is a 404, never an empty timeline."""
    del migrated_database, oversight_context
    admin_id = await _create_user(role="admin")

    response = await client.get(
        f"/v1/admin/transactions/{uuid4()}",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    assert response.status_code == 404


async def test_admin_financial_event_feed_filters_by_reason(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """Admins can pull every failure sharing one normalized cause.

    Provider-neutral by construction: a Paystack decline and a Stripe decline
    answer the same filter, which is the point of the shared vocabulary.
    """
    del migrated_database, oversight_context
    admin_id = await _create_user(role="admin")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                FinancialEvent(
                    entity_type="transaction",
                    entity_id=uuid4(),
                    event_type="purchase_failed",
                    provider="paystack",
                    reason_code="insufficient_funds",
                )
            )
            await session.flush()
            session.add(
                FinancialEvent(
                    entity_type="transaction",
                    entity_id=uuid4(),
                    event_type="purchase_failed",
                    provider="stripe",
                    reason_code="expired_card",
                )
            )

    response = await client.get(
        "/v1/admin/financial-events",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"reason_code": "insufficient_funds"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["reason_code"] == "insufficient_funds"
    assert body["items"][0]["provider"] == "paystack"


async def test_admin_lists_escrows_with_holdings(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """Escrow oversight shows what the platform is currently holding."""
    del migrated_database, oversight_context
    admin_id = await _create_user(role="admin")
    payer_id = await _create_user(role="operator")
    transaction_id = await _create_transaction(
        payer_id=payer_id,
        status="completed",
        provider_ref="ref_escrow",
        transaction_type="milestone",
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Escrow(
                    ref_id=uuid4(),
                    ref_type="milestone",
                    amount=Decimal("450.00"),
                    currency="NGN",
                    status="held",
                    transaction_id=transaction_id,
                )
            )

    response = await client.get(
        "/v1/admin/escrows",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"status": "held"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["status"] == "held"
    assert item["amount"] == "450.00"
    assert item["transaction_id"] == str(transaction_id)


async def test_admin_reads_webhook_delivery_errors(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """The stored webhook `error` becomes readable for the first time.

    It has been written on every failed delivery and read by nobody, so a
    provider event that never applied left no trace an admin could find.
    """
    del migrated_database, oversight_context
    admin_id = await _create_user(role="admin")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                WebhookEvent(
                    provider="stripe",
                    provider_event_id="evt_broken_1",
                    event_type="payment_intent.succeeded",
                    status="failed",
                    payload_hash="0" * 64,
                    error="purchase event missing transaction_id",
                )
            )

    response = await client.get(
        "/v1/admin/webhook-events",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"status": "failed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["provider_event_id"] == "evt_broken_1"
    assert item["status"] == "failed"
    assert item["error"] == "purchase event missing transaction_id"
    # The raw provider payload is never stored or served — only its hash.
    assert "payload" not in item


async def test_admin_audit_log_view_filters_to_money_actions(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """The audit view can be narrowed to one money action across all actors."""
    del migrated_database, oversight_context
    admin_id = await _create_user(role="admin")
    contributor_id = await _create_user(role="contributor")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                AuditLog(
                    actor_id=contributor_id,
                    action="payout_failed",
                    target_type="payout",
                    target_id=uuid4(),
                    metadata_={"provider": "stripe"},
                )
            )
            session.add(
                AuditLog(
                    actor_id=contributor_id,
                    action="login_success",
                    target_type="user",
                    target_id=contributor_id,
                    metadata_={},
                )
            )

    response = await client.get(
        "/v1/admin/audit-logs",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"action": "payout_failed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["action"] == "payout_failed"
    assert item["target_type"] == "payout"
    assert item["actor_id"] == str(contributor_id)


@pytest.mark.parametrize(
    "path",
    [
        "/v1/admin/transactions",
        "/v1/admin/financial-events",
        "/v1/admin/escrows",
        "/v1/admin/webhook-events",
        "/v1/admin/audit-logs",
    ],
)
async def test_non_admin_cannot_read_financial_oversight(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
    path: str,
) -> None:
    """Every oversight endpoint is gated on the admin role, not just the index."""
    del migrated_database, oversight_context
    contributor_id = await _create_user(role="contributor")

    response = await client.get(
        path,
        headers=_auth_headers(contributor_id, roles=["contributor"]),
    )

    assert response.status_code == 403


async def test_financial_oversight_requires_authentication(
    client: AsyncClient,
    migrated_database: None,
    oversight_context: None,
) -> None:
    """An unauthenticated caller is rejected before any query runs."""
    del migrated_database, oversight_context

    response = await client.get("/v1/admin/transactions")

    assert response.status_code == 401
