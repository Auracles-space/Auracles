"""Integration tests for Contributor earnings and payout requests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_payout_provider_account_id,
    encrypt_totp_secret,
    hash_payout_provider_account_id,
)
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import service as financials_service
from app.modules.financials.models import Escrow, Payout, PayoutAccount, Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
    ProposalAmendment,
)
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for TOTP-sensitive payout routes."""

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored value or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        """Delete stored values and counters."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


class FakePayoutTask:
    """Celery task double that records payout processing dispatches."""

    def __init__(self) -> None:
        """Initialise the in-memory dispatch log."""
        self.dispatched: list[str] = []

    def delay(self, payout_id: str) -> None:
        """Record the payout id that would be sent to Celery."""
        self.dispatched.append(payout_id)


async def reset_payout_state() -> None:
    """Remove payout test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(License))
        await session.execute(delete(Payout))
        await session.execute(delete(PayoutAccount))
        await session.execute(delete(Escrow))
        await session.execute(delete(Transaction))
        await session.execute(delete(Dispute))
        await session.execute(delete(Deliverable))
        await session.execute(delete(Milestone))
        await session.execute(delete(ProposalAmendment))
        await session.execute(delete(Project))
        await session.execute(delete(Proposal))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure financial tables exist for payout tests."""
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
async def payout_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install Redis/task doubles."""
    fake_redis = FakeRedis()
    fake_task = FakePayoutTask()
    await engine.dispose()
    await reset_payout_state()

    async def override_redis() -> FakeRedis:
        """Return the Redis test double for dependency injection."""
        return fake_redis

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(
        financials_service,
        "process_payout",
        fake_task,
        raising=False,
    )
    try:
        yield {"redis": fake_redis, "payout_task": fake_task}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_payout_state()
        await engine.dispose()


async def create_user_with_roles(
    email: str,
    roles: list[str],
    *,
    kyc_status: str = "verified",
    enable_totp: bool = True,
) -> tuple[UUID, str | None]:
    """Create a verified user with roles, KYC state, and optional TOTP."""
    secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash="not-used",
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status=kyc_status,
                totp_enabled=enable_totp,
                totp_secret=encrypt_totp_secret(secret) if secret else None,
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
        return user.id, secret


async def create_sale(
    contributor_id: UUID,
    *,
    amount: Decimal,
    created_at: datetime,
    status: str = "completed",
) -> UUID:
    """Create a framework purchase transaction payable to the contributor."""
    operator_id, _ = await create_user_with_roles(
        f"operator-{uuid4()}@auracles.space",
        ["operator"],
        enable_totp=False,
    )
    async with async_session_factory() as session:
        async with session.begin():
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
                provider_ref=f"pi_sale_{uuid4()}",
                ref_id=uuid4(),
                ref_type="framework",
                created_at=created_at,
            )
            session.add(transaction)
            await session.flush()
            return transaction.id


async def create_released_milestone_earning(
    contributor_id: UUID,
    *,
    amount: Decimal,
    created_at: datetime,
    escrow_status: str = "released",
) -> UUID:
    """Create a Project Milestone transaction with its escrow release state."""
    operator_id, _ = await create_user_with_roles(
        f"milestone-operator-{uuid4()}@auracles.space",
        ["operator"],
        enable_totp=False,
    )
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=amount,
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=amount,
                transaction_type="milestone",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_milestone_{uuid4()}",
                ref_id=uuid4(),
                ref_type="project_milestone",
                created_at=created_at,
            )
            session.add(transaction)
            await session.flush()
            session.add(
                Escrow(
                    ref_id=transaction.ref_id,
                    ref_type="project_milestone",
                    amount=amount,
                    currency="USD",
                    status=escrow_status,
                    release_conditions={
                        "kind": "project_milestone",
                    },
                    transaction_id=transaction.id,
                    released_at=(
                        datetime.now(UTC) if escrow_status == "released" else None
                    ),
                )
            )
            return transaction.id


async def create_released_attestation_fee_earning(
    contributor_id: UUID,
    *,
    amount: Decimal,
    created_at: datetime,
    escrow_status: str = "released",
) -> UUID:
    """Create an Attestation fee transaction with its escrow release state."""
    operator_id, _ = await create_user_with_roles(
        f"attestation-operator-{uuid4()}@auracles.space",
        ["operator"],
        enable_totp=False,
    )
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=amount,
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=amount,
                transaction_type="attestation_fee",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_attestation_{uuid4()}",
                ref_id=uuid4(),
                ref_type="attestation",
                created_at=created_at,
            )
            session.add(transaction)
            await session.flush()
            session.add(
                Escrow(
                    ref_id=transaction.ref_id,
                    ref_type="attestation",
                    amount=amount,
                    currency="USD",
                    status=escrow_status,
                    release_conditions={"kind": "attestation"},
                    transaction_id=transaction.id,
                    released_at=(
                        datetime.now(UTC) if escrow_status == "released" else None
                    ),
                )
            )
            return transaction.id


async def create_verified_payout_account(contributor_id: UUID) -> UUID:
    """Create a default verified payout account for the contributor."""
    provider_account_id = f"acct_{uuid4()}"
    async with async_session_factory() as session:
        async with session.begin():
            payout_account = PayoutAccount(
                user_id=contributor_id,
                provider="stripe",
                provider_account_id=encrypt_payout_provider_account_id(
                    provider_account_id
                ),
                provider_account_lookup_hash=hash_payout_provider_account_id(
                    provider_account_id
                ),
                account_type="express",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)
            await session.flush()
            return payout_account.id


async def create_payout(
    contributor_id: UUID,
    payout_account_id: UUID,
    *,
    net_amount: Decimal,
    status: str = "completed",
) -> None:
    """Create an existing payout row that reduces available balance."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Payout(
                    contributor_id=contributor_id,
                    payout_account_id=payout_account_id,
                    amount=net_amount,
                    currency="USD",
                    commission_deducted=Decimal("0.00"),
                    net_amount=net_amount,
                    status=status,
                    provider_ref=f"tr_{uuid4()}",
                )
            )


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_contributor_earnings_are_refund_window_and_payout_aware(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """Earnings exclude refundable sales and subtract prior payout claims."""
    del migrated_database, payout_context
    contributor_id, _ = await create_user_with_roles(
        "earnings-contributor@auracles.space",
        ["contributor"],
    )
    payout_account_id = await create_verified_payout_account(contributor_id)
    await create_sale(
        contributor_id,
        amount=Decimal("100.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    await create_sale(
        contributor_id,
        amount=Decimal("80.00"),
        created_at=datetime.now(UTC),
    )
    await create_sale(
        contributor_id,
        amount=Decimal("40.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
        status="refunded",
    )
    await create_payout(
        contributor_id,
        payout_account_id,
        net_amount=Decimal("10.00"),
        status="completed",
    )

    response = await client.get(
        "/v1/financials/earnings",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "gross_revenue": "180.00",
        "pending_clearance": "80.00",
        "available_balance": "75.00",
        "commission_rate": "0.15",
        "minimum_payout": "50.00",
    }


async def test_released_project_milestones_are_withdrawable_earnings(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """Released Project Milestones count toward earnings and payout balance."""
    del migrated_database, payout_context
    contributor_id, _ = await create_user_with_roles(
        "milestone-earnings@auracles.space",
        ["contributor"],
    )
    await create_released_milestone_earning(
        contributor_id,
        amount=Decimal("900.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    await create_released_milestone_earning(
        contributor_id,
        amount=Decimal("300.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
        escrow_status="held",
    )

    response = await client.get(
        "/v1/financials/earnings",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "gross_revenue": "900.00",
        "pending_clearance": "0.00",
        "available_balance": "765.00",
        "commission_rate": "0.15",
        "minimum_payout": "50.00",
    }


async def test_released_attestation_fees_are_withdrawable_earnings(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """Released Attestation fees count toward Attestor payout balance."""
    del migrated_database, payout_context
    attestor_id, _ = await create_user_with_roles(
        "attestation-fee-earnings@auracles.space",
        ["contributor", "attestor"],
    )
    await create_released_attestation_fee_earning(
        attestor_id,
        amount=Decimal("600.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    await create_released_attestation_fee_earning(
        attestor_id,
        amount=Decimal("200.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
        escrow_status="held",
    )

    response = await client.get(
        "/v1/financials/earnings",
        headers=auth_headers(attestor_id, ["contributor", "attestor"]),
    )

    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "gross_revenue": "600.00",
        "pending_clearance": "0.00",
        "available_balance": "540.00",
        "commission_rate": "0.1",
        "minimum_payout": "50.00",
    }


async def test_attestation_earnings_clear_immediately(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """Released Attestation earnings withdraw at once with no refund-window wait.

    Enforces Module 6a design §4.2: attestation has already passed its
    dispute window before release, so earnings do not sit in pending
    clearance the way framework sales do.
    """
    del migrated_database, payout_context
    attestor_id, _ = await create_user_with_roles(
        "attestation-immediate@auracles.space",
        ["contributor", "attestor"],
    )
    await create_released_attestation_fee_earning(
        attestor_id,
        amount=Decimal("600.00"),
        created_at=datetime.now(UTC),
    )

    response = await client.get(
        "/v1/financials/earnings",
        headers=auth_headers(attestor_id, ["contributor", "attestor"]),
    )

    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "gross_revenue": "600.00",
        "pending_clearance": "0.00",
        "available_balance": "540.00",
        "commission_rate": "0.1",
        "minimum_payout": "50.00",
    }


async def test_mixed_marketplace_and_attestation_earnings_blend_commission(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """A user earning from both frameworks and attestations gets a blended rate.

    Framework earnings settle at 15%, attestation earnings at 10%; the
    reported commission_rate is the effective blend across cleared earnings
    (Module 6a design §6).
    """
    del migrated_database, payout_context
    user_id, _ = await create_user_with_roles(
        "mixed-earnings@auracles.space",
        ["contributor", "attestor"],
    )
    await create_sale(
        user_id,
        amount=Decimal("100.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    await create_released_attestation_fee_earning(
        user_id,
        amount=Decimal("200.00"),
        created_at=datetime.now(UTC),
    )

    response = await client.get(
        "/v1/financials/earnings",
        headers=auth_headers(user_id, ["contributor", "attestor"]),
    )

    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "gross_revenue": "300.00",
        "pending_clearance": "0.00",
        "available_balance": "265.00",
        "commission_rate": "0.1167",
        "minimum_payout": "50.00",
    }


async def test_attestor_withdraws_attestation_earnings_at_ten_percent_gross_up(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """An Attestor withdraws attestation earnings; gross-up uses the 10% rate.

    Enforces Module 6a design §9 tests 7-8: attestation earnings are
    withdrawable via the existing KYC/2FA/$50-minimum payout path, and the
    payout's commission bookkeeping reflects the 10% attestation rate.
    """
    del migrated_database
    attestor_id, totp_secret = await create_user_with_roles(
        "attestor-withdraw@auracles.space",
        ["contributor", "attestor"],
    )
    payout_account_id = await create_verified_payout_account(attestor_id)
    await create_released_attestation_fee_earning(
        attestor_id,
        amount=Decimal("600.00"),
        created_at=datetime.now(UTC),
    )
    assert totp_secret is not None
    code = pyotp.TOTP(totp_secret).now()

    response = await client.post(
        "/v1/financials/payouts",
        headers=auth_headers(attestor_id, ["contributor", "attestor"]),
        json={
            "amount": "100.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
            "totp_code": code,
        },
    )

    async with async_session_factory() as session:
        payout = await session.scalar(select(Payout))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["net_amount"] == "100.00"
    assert body["commission_deducted"] == "11.11"
    assert payout is not None
    assert payout.amount == Decimal("111.11")
    assert payout.net_amount == Decimal("100.00")
    assert payout_context["payout_task"].dispatched == [str(payout.id)]


async def test_contributor_requests_payout_with_kyc_totp_and_minimum(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """A verified Contributor can request an available payout once."""
    del migrated_database
    contributor_id, totp_secret = await create_user_with_roles(
        "request-payout@auracles.space",
        ["contributor"],
    )
    payout_account_id = await create_verified_payout_account(contributor_id)
    await create_sale(
        contributor_id,
        amount=Decimal("100.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    assert totp_secret is not None
    code = pyotp.TOTP(totp_secret).now()

    response = await client.post(
        "/v1/financials/payouts",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "amount": "50.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
            "totp_code": code,
        },
    )
    history = await client.get(
        "/v1/financials/payouts",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    async with async_session_factory() as session:
        payout = await session.scalar(select(Payout))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "payout_requested")
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["net_amount"] == "50.00"
    assert body["commission_deducted"] == "8.82"
    assert history.status_code == 200
    assert history.json()["payouts"][0]["id"] == body["id"]
    assert payout is not None
    assert payout.amount == Decimal("58.82")
    assert payout.net_amount == Decimal("50.00")
    assert payout.status == "pending"
    assert payout_context["payout_task"].dispatched == [str(payout.id)]
    assert audit is not None
    assert audit.target_id == payout.id


async def test_payout_request_rejects_below_minimum_and_unavailable_balance(
    client: AsyncClient,
    migrated_database: None,
    payout_context: dict[str, Any],
) -> None:
    """Payout requests enforce minimum and available-balance limits."""
    del migrated_database, payout_context
    contributor_id, totp_secret = await create_user_with_roles(
        "low-payout@auracles.space",
        ["contributor"],
    )
    payout_account_id = await create_verified_payout_account(contributor_id)
    await create_sale(
        contributor_id,
        amount=Decimal("100.00"),
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    assert totp_secret is not None
    code = pyotp.TOTP(totp_secret).now()

    too_small = await client.post(
        "/v1/financials/payouts",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "amount": "49.99",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
            "totp_code": code,
        },
    )
    too_large = await client.post(
        "/v1/financials/payouts",
        headers=auth_headers(contributor_id, ["contributor"]),
        json={
            "amount": "90.00",
            "currency": "USD",
            "payout_account_id": str(payout_account_id),
            "totp_code": code,
        },
    )

    assert too_small.status_code == 422
    assert too_small.json()["detail"] == "Minimum payout is $50.00."
    assert too_large.status_code == 422
    assert too_large.json()["detail"] == "Requested payout exceeds available balance."
