"""Integration tests for requesting a platform withdrawal.

A withdrawal moves the platform's own money out of the Paystack balance that
also holds users' money, so every guard is pinned: super-admin with step-up,
a usable bank account past its 24-hour hold, one withdrawal in flight, the
configured minimum, and never more than Treasury says is withdrawable.

Maps to: platform treasury design, decisions 2, 4, 8 and 10.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    encrypt_payout_provider_account_id,
)
from app.integrations.paystack import PaystackProviderError
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import platform_withdrawals, treasury
from app.modules.financials.models import PlatformBankAccount, PlatformWithdrawal
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.integration.test_admin_config import FakeRedis
from tests.integration.test_admin_treasury_summary import _reset, _seed_ledger

PATH = "/v1/admin/treasury/withdrawals"
SUMMARY_PATH = "/v1/admin/treasury/summary"


class FakeTask:
    """Capture Celery dispatches instead of queueing them."""

    def __init__(self) -> None:
        """Start with no dispatched ids."""
        self.calls: list[str] = []

    def delay(self, withdrawal_id: str) -> None:
        """Record one dispatch."""
        self.calls.append(withdrawal_id)


@pytest.fixture
async def withdrawal_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install Redis, Paystack, task and notification doubles."""
    await engine.dispose()
    await _reset()
    fake_redis = FakeRedis()
    task = FakeTask()
    context: dict[str, Any] = {
        "redis": fake_redis,
        "balances": {"NGN": 25_900_000},
        "balance_error": False,
        "task": task,
        "notifications": [],
    }

    async def override_redis() -> FakeRedis:
        """Return the Redis test double."""
        return fake_redis

    async def fake_fetch_balance(**_: Any) -> dict[str, int]:
        """Return the configured balance or fail on demand."""
        if context["balance_error"]:
            raise PaystackProviderError("Paystack is down")
        return dict(context["balances"])

    def fake_notify(**kwargs: Any) -> None:
        """Capture admin notifications."""
        context["notifications"].append(kwargs)

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(treasury.paystack, "fetch_balance", fake_fetch_balance)
    monkeypatch.setattr(platform_withdrawals, "process_platform_withdrawal", task)
    monkeypatch.setattr(
        platform_withdrawals, "notify_admins_review_pending", fake_notify
    )
    try:
        yield context
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await _reset()
        await engine.dispose()


async def _admin(*, superadmin: bool = True) -> UUID:
    """Create an admin with 2FA enabled."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"withdraw-admin-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Withdrawal Admin",
                email_verified=True,
                totp_enabled=True,
                is_superadmin=superadmin,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(user_id=user.id, role="admin", approved_at=datetime.now(UTC))
            )
        return user.id


def _headers(user_id: UUID) -> dict[str, str]:
    """Build admin bearer headers."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def _bank_account(created_by: UUID, *, usable: bool = True) -> UUID:
    """Insert an active platform bank account, past or inside its hold."""
    offset = timedelta(hours=-1) if usable else timedelta(hours=23)
    async with async_session_factory() as session:
        async with session.begin():
            account = PlatformBankAccount(
                provider="paystack",
                bank_code="058",
                bank_name="Guaranty Trust Bank",
                account_last4="6789",
                account_name="AURACLES TECHNOLOGIES LTD",
                recipient_code_encrypted=encrypt_payout_provider_account_id(
                    "RCP_platform"
                ),
                usable_from=datetime.now(UTC) + offset,
                created_by=created_by,
            )
            session.add(account)
            await session.flush()
            return account.id


async def _ready_superadmin(context: dict[str, Any]) -> UUID:
    """Seed the ledger, a usable bank account and a step-up super-admin."""
    await _seed_ledger()
    superadmin_id = await _admin()
    await _bank_account(superadmin_id)
    await open_step_up_window(context["redis"], superadmin_id)
    return superadmin_id


async def _withdrawals() -> list[PlatformWithdrawal]:
    """Return every withdrawal row."""
    async with async_session_factory() as session:
        return list((await session.execute(select(PlatformWithdrawal))).scalars())


async def test_superadmin_requests_a_withdrawal(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """A valid request records a pending withdrawal and queues the transfer."""
    superadmin_id = await _ready_superadmin(withdrawal_context)

    response = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "10000.00"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["amount"] == "10000.00"
    assert body["currency"] == "NGN"
    assert body["account_last4"] == "6789"
    rows = await _withdrawals()
    assert len(rows) == 1
    assert rows[0].provider_ref == f"platform-withdrawal-{rows[0].id}"
    assert rows[0].requested_by == superadmin_id
    assert withdrawal_context["task"].calls == [str(rows[0].id)]
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "platform_withdrawal_requested")
        )
    assert audit is not None
    assert audit.metadata_["amount"] == "10000.00"
    assert withdrawal_context["notifications"][0]["domain"] == (
        "platform_withdrawal_requested"
    )


async def test_a_requested_withdrawal_reduces_our_money(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """Treasury counts an in-flight withdrawal as already gone."""
    superadmin_id = await _ready_superadmin(withdrawal_context)

    await client.post(PATH, headers=_headers(superadmin_id), json={"amount": "10000"})
    summary = await client.get(SUMMARY_PATH, headers=_headers(superadmin_id))

    ngn = next(i for i in summary.json()["currencies"] if i["currency"] == "NGN")
    assert ngn["our_money"]["platform_withdrawals"] == "10000.00"
    assert ngn["our_money"]["total"] == "5750.00"


async def test_amount_above_withdrawable_is_refused_and_audited(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """Asking for more than Treasury allows is 402 and leaves an audit trail."""
    superadmin_id = await _ready_superadmin(withdrawal_context)

    response = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "16000.00"}
    )

    assert response.status_code == 402
    assert response.json()["detail"]["error_code"] == "insufficient_withdrawable"
    assert await _withdrawals() == []
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "platform_withdrawal_insufficient_funds"
            )
        )
    assert audit is not None
    assert withdrawal_context["task"].calls == []


async def test_below_minimum_is_refused(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """The configured minimum (₦10,000 by default) applies."""
    superadmin_id = await _ready_superadmin(withdrawal_context)

    response = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "9999.99"}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "below_minimum_withdrawal"


async def test_only_one_withdrawal_can_be_in_flight(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """A second request while one is pending is a conflict."""
    superadmin_id = await _ready_superadmin(withdrawal_context)
    withdrawal_context["balances"] = {"NGN": 50_000_000}

    first = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "10000"}
    )
    second = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "10000"}
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"]["error_code"] == "platform_withdrawal_in_progress"


async def test_the_database_refuses_a_second_in_flight_withdrawal(
    withdrawal_context: dict[str, Any],
) -> None:
    """The one-in-flight rule holds even if two requests race past the service."""
    superadmin_id = await _admin()
    account_id = await _bank_account(superadmin_id)

    with pytest.raises(IntegrityError):
        async with async_session_factory() as session:
            async with session.begin():
                for _ in range(2):
                    withdrawal_id = uuid4()
                    session.add(
                        PlatformWithdrawal(
                            id=withdrawal_id,
                            bank_account_id=account_id,
                            amount=Decimal("10000.00"),
                            currency="NGN",
                            status="pending",
                            provider_ref=f"platform-withdrawal-{withdrawal_id}",
                            requested_by=superadmin_id,
                        )
                    )
                    await session.flush()


async def test_bank_account_must_exist_and_be_past_its_hold(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """No account is 422; an account still inside its 24-hour hold is 422."""
    await _seed_ledger()
    superadmin_id = await _admin()
    await open_step_up_window(withdrawal_context["redis"], superadmin_id)

    missing = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "10000"}
    )
    await _bank_account(superadmin_id, usable=False)
    on_hold = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "10000"}
    )

    assert missing.status_code == 422
    assert missing.json()["detail"]["error_code"] == "platform_bank_account_missing"
    assert on_hold.status_code == 422
    assert on_hold.json()["detail"]["error_code"] == "platform_bank_account_on_hold"


async def test_balance_outage_refuses_the_withdrawal(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """Without a live balance the withdrawable amount is unknown, so nothing moves."""
    superadmin_id = await _ready_superadmin(withdrawal_context)
    withdrawal_context["balance_error"] = True

    response = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "10000"}
    )

    assert response.status_code == 502
    assert await _withdrawals() == []


async def test_only_the_superadmin_with_step_up_can_withdraw(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """Admins are refused, and so is a super-admin without a step-up window."""
    await _seed_ledger()
    admin_id = await _admin(superadmin=False)
    superadmin_id = await _admin()
    await _bank_account(superadmin_id)
    await open_step_up_window(withdrawal_context["redis"], admin_id)

    admin = await client.post(
        PATH, headers=_headers(admin_id), json={"amount": "10000"}
    )
    no_step_up = await client.post(
        PATH, headers=_headers(superadmin_id), json={"amount": "10000"}
    )

    assert admin.status_code == 403
    assert no_step_up.status_code == 403
    assert no_step_up.json()["detail"]["error_code"] == "step_up_required"
    assert await _withdrawals() == []


async def test_every_admin_can_list_withdrawals(
    client: AsyncClient,
    withdrawal_context: dict[str, Any],
) -> None:
    """History is visible to any admin, newest first."""
    superadmin_id = await _ready_superadmin(withdrawal_context)
    admin_id = await _admin(superadmin=False)
    await client.post(PATH, headers=_headers(superadmin_id), json={"amount": "10000"})

    response = await client.get(PATH, headers=_headers(admin_id))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["withdrawals"][0]
    assert item["status"] == "pending"
    assert item["bank_name"] == "Guaranty Trust Bank"
    assert item["account_last4"] == "6789"
    assert item["awaiting_otp"] is False
    assert "recipient_code" not in item
