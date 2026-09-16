"""Integration tests for the admin payout oversight endpoint.

Read-only surface: admins list and filter payouts for financial oversight.
Payout-account destination details must never appear in the response, and only
admins may call it.
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
from app.modules.financials.models import Payout, PayoutAccount
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


async def reset_admin_payout_state() -> None:
    """Remove payout test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(Payout))
        await session.execute(delete(PayoutAccount))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for admin payout tests."""
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
async def admin_payout_context() -> AsyncIterator[None]:
    """Reset auth/payout state around each test."""
    await engine.dispose()
    await reset_admin_payout_state()
    try:
        yield
    finally:
        await reset_admin_payout_state()
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


async def _create_payout(
    *,
    contributor_id: UUID,
    provider: str,
    status: str,
    provider_ref: str | None,
) -> UUID:
    """Create a contributor payout with its own payout account."""
    async with async_session_factory() as session:
        async with session.begin():
            account = PayoutAccount(
                user_id=contributor_id,
                provider=provider,
                provider_account_id="acct_secret_destination",
                provider_account_lookup_hash=uuid4().hex,
                account_type="express",
                verified_at=datetime.now(UTC),
            )
            session.add(account)
            await session.flush()
            payout = Payout(
                contributor_id=contributor_id,
                payout_account_id=account.id,
                amount=Decimal("300.00"),
                currency="USD",
                commission_deducted=Decimal("30.00"),
                net_amount=Decimal("270.00"),
                status=status,
                provider_ref=provider_ref,
            )
            session.add(payout)
            await session.flush()
            return payout.id


def _auth_headers(user_id: UUID, *, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a user with the given roles."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_admin_lists_payouts_without_account_details(
    client: AsyncClient,
    migrated_database: None,
    admin_payout_context: None,
) -> None:
    """Admin sees payouts but never the payout-account destination id."""
    del migrated_database, admin_payout_context
    admin_id = await _create_user(role="admin")
    contributor_id = await _create_user(role="contributor")
    payout_id = await _create_payout(
        contributor_id=contributor_id,
        provider="stripe",
        status="failed",
        provider_ref="tr_failed_123",
    )

    response = await client.get(
        "/v1/admin/payouts",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["payout_id"] == str(payout_id)
    assert item["beneficiary_type"] == "contributor"
    assert item["beneficiary_id"] == str(contributor_id)
    assert item["provider"] == "stripe"
    assert item["status"] == "failed"
    assert item["net_amount"] == "270.00"
    assert item["provider_ref"] == "tr_failed_123"
    assert item["awaiting_otp"] is False
    # PII guard: the payout-account destination must never leak.
    assert "acct_secret_destination" not in response.text
    assert "provider_account_id" not in item


async def test_admin_filters_payouts_by_status(
    client: AsyncClient,
    migrated_database: None,
    admin_payout_context: None,
) -> None:
    """The status filter narrows the directory to matching payouts only."""
    del migrated_database, admin_payout_context
    admin_id = await _create_user(role="admin")
    contributor_id = await _create_user(role="contributor")
    await _create_payout(
        contributor_id=contributor_id,
        provider="stripe",
        status="failed",
        provider_ref="tr_failed",
    )
    await _create_payout(
        contributor_id=contributor_id,
        provider="stripe",
        status="completed",
        provider_ref="tr_done",
    )

    response = await client.get(
        "/v1/admin/payouts",
        headers=_auth_headers(admin_id, roles=["admin"]),
        params={"status": "failed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"


async def test_non_admin_cannot_list_payouts(
    client: AsyncClient,
    migrated_database: None,
    admin_payout_context: None,
) -> None:
    """A contributor token is rejected from the admin payout directory."""
    del migrated_database, admin_payout_context
    contributor_id = await _create_user(role="contributor")

    response = await client.get(
        "/v1/admin/payouts",
        headers=_auth_headers(contributor_id, roles=["contributor"]),
    )

    assert response.status_code == 403
