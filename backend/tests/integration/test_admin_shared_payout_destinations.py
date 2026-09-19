"""Integration tests for the admin view of shared payout destinations.

One bank account backing several owners is legitimate — a sole trader's own
payout account and their company's are routinely the same NUBAN — so it is
allowed. What it must not be is invisible: one account collecting for many
separate identities is the shape of a payout funnel, and it is the only
signal of that the platform holds. This surface makes it readable, and lets
an admin deliberately allow a destination past the automatic ceiling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import (
    create_access_token,
    encrypt_payout_provider_account_id,
    hash_payout_provider_account_id,
)
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import (
    PayoutAccount,
    PayoutDestinationAllowance,
)
from app.modules.organizations.models import Organization
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async

SHARED_RECIPIENT = "RCP_shared_destination"


async def _reset_state() -> None:
    """Remove payout and identity rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(PayoutDestinationAllowance))
        await session.execute(delete(PayoutAccount))
        await session.execute(delete(Organization))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the payout tables exist."""
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
async def shared_destination_context(
    migrated_database: None,
) -> AsyncIterator[None]:
    """Reset payout state around each test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


def _auth_headers(user_id: UUID, *, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a user with the given roles."""
    return {
        "Authorization": f"Bearer {create_access_token(user_id=user_id, roles=roles)}"
    }


async def _create_user(*, role: str, display_name: str) -> UUID:
    """Create a verified user holding one role."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{role}-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name=display_name,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC))
            )
            return user.id


async def _payout_account(
    *,
    user_id: UUID | None = None,
    org_id: UUID | None = None,
    recipient_code: str = SHARED_RECIPIENT,
) -> UUID:
    """Register one payout account against the shared recipient code."""
    async with async_session_factory() as session:
        async with session.begin():
            account = PayoutAccount(
                user_id=user_id,
                org_id=org_id,
                provider="paystack",
                provider_account_id=encrypt_payout_provider_account_id(recipient_code),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    recipient_code
                ),
                account_type="nuban",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(account)
            await session.flush()
            return account.id


async def _organization(*, created_by: UUID, name: str) -> UUID:
    """Create an organization that can own a payout account."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:8]}",
                name=name,
                country="NG",
                created_by=created_by,
            )
            session.add(org)
            await session.flush()
            return org.id


async def test_admin_sees_who_shares_one_bank_account(
    client: AsyncClient,
    shared_destination_context: None,
) -> None:
    """A destination held by several owners is listed, naming each of them.

    Without this the sharing signal exists only as an audit line nobody reads.
    An admin deciding whether a shared account is a sole trader or a funnel
    needs to see who is actually behind it.
    """
    del shared_destination_context
    admin_id = await _create_user(role="admin", display_name="Admin")
    contributor_id = await _create_user(role="contributor", display_name="Ada Lovelace")
    org_id = await _organization(created_by=contributor_id, name="Lovelace Ltd")
    await _payout_account(user_id=contributor_id)
    await _payout_account(org_id=org_id)
    # A second, unshared account must not appear: one owner is not a signal.
    solo_id = await _create_user(role="contributor", display_name="Solo")
    await _payout_account(user_id=solo_id, recipient_code="RCP_solo")

    response = await client.get(
        "/v1/admin/payout-destinations/shared",
        headers=_auth_headers(admin_id, roles=["admin"]),
    )

    body = response.json()
    assert response.status_code == 200
    assert len(body["destinations"]) == 1
    destination = body["destinations"][0]
    assert destination["owner_count"] == 2
    assert destination["provider"] == "paystack"
    # Masked, never the recipient code itself: this is a payout address.
    assert destination["provider_account_ref"].startswith("****")
    assert sorted(owner["name"] for owner in destination["owners"]) == [
        "Ada Lovelace",
        "Lovelace Ltd",
    ]


async def test_shared_destination_view_is_admin_only(
    client: AsyncClient,
    shared_destination_context: None,
) -> None:
    """A contributor cannot read who shares a bank account.

    The listing names the people behind an account, so it is admin-only like
    the rest of the oversight surface.
    """
    del shared_destination_context
    contributor_id = await _create_user(role="contributor", display_name="Ada Lovelace")

    response = await client.get(
        "/v1/admin/payout-destinations/shared",
        headers=_auth_headers(contributor_id, roles=["contributor"]),
    )

    assert response.status_code == 403


async def test_admin_can_allow_a_destination_past_the_cap(
    client: AsyncClient,
    shared_destination_context: None,
) -> None:
    """An admin can deliberately let one bank account back more owners.

    The automatic ceiling is a prompt for a human to look, not a verdict, so
    there has to be a way to say yes — otherwise a legitimate group of related
    organizations is permanently stuck with no recourse.
    """
    del shared_destination_context
    admin_id = await _create_user(role="admin", display_name="Admin")
    contributor_id = await _create_user(role="contributor", display_name="Ada Lovelace")
    await _payout_account(user_id=contributor_id)

    response = await client.post(
        "/v1/admin/payout-destinations/allowance",
        headers=_auth_headers(admin_id, roles=["admin"]),
        json={
            "provider": "paystack",
            "lookup_hash": hash_payout_provider_account_id(SHARED_RECIPIENT),
            "max_owners": 6,
            "note": "Four related trading entities, one treasury account.",
        },
    )

    async with async_session_factory() as session:
        allowance = await session.scalar(select(PayoutDestinationAllowance))
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "payout_destination_allowance_set"
            )
        )

    assert response.status_code == 200
    assert allowance is not None
    assert allowance.max_owners == 6
    assert allowance.approved_by == admin_id
    # Raising the ceiling on a money path is an admin action worth auditing.
    assert audit is not None
