"""Integration tests for the platform bank account used by treasury withdrawals.

The platform bank account is where the platform's own money goes, so changing
it is the single most valuable thing an attacker could do. Only the
super-admin may set it, only with step-up, every change is audited and
announced to every admin, and a new account waits 24 hours before it can
receive a withdrawal so a hijacked change can be caught first.

Maps to: platform treasury design, decision 3.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, decrypt_payout_provider_account_id
from app.integrations.paystack import (
    PaystackBank,
    PaystackProviderError,
    PaystackTransferRecipient,
)
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials import platform_bank_account
from app.modules.financials.models import PlatformBankAccount
from app.shared.models.audit_log import AuditLog
from tests.conftest import open_step_up_window
from tests.integration.test_admin_config import FakeRedis
from tests.support.db_cleanup import clear_identity_state_async

PATH = "/v1/admin/treasury/bank-account"
PAYLOAD = {"account_number": "0123456789", "bank_code": "058"}


async def _reset() -> None:
    """Remove bank account test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(PlatformBankAccount))
        await clear_identity_state_async(session)
        await session.commit()


@pytest.fixture
async def bank_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state, fake Redis, and install Paystack and notification doubles."""
    await engine.dispose()
    await _reset()
    fake_redis = FakeRedis()
    context: dict[str, Any] = {
        "redis": fake_redis,
        "recipient_error": False,
        "recipients": [],
        "notifications": [],
    }

    async def override_redis() -> FakeRedis:
        """Return the Redis test double."""
        return fake_redis

    async def fake_list_banks(**_: Any) -> list[PaystackBank]:
        """Return a fixed bank list."""
        return [PaystackBank(name="Guaranty Trust Bank", code="058")]

    async def fake_create_transfer_recipient(
        **kwargs: Any,
    ) -> PaystackTransferRecipient:
        """Record the call and return a recipient, or fail on demand."""
        if context["recipient_error"]:
            raise PaystackProviderError("Could not resolve account name")
        context["recipients"].append(kwargs)
        return PaystackTransferRecipient(
            recipient_code=f"RCP_{uuid4().hex[:10]}",
            account_name="AURACLES TECHNOLOGIES LTD",
        )

    def fake_notify(**kwargs: Any) -> None:
        """Capture admin notifications instead of queueing them."""
        context["notifications"].append(kwargs)

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(platform_bank_account.paystack, "list_banks", fake_list_banks)
    monkeypatch.setattr(
        platform_bank_account.paystack,
        "create_transfer_recipient",
        fake_create_transfer_recipient,
    )
    monkeypatch.setattr(
        platform_bank_account, "notify_admins_review_pending", fake_notify
    )
    try:
        yield context
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await _reset()
        await engine.dispose()


async def _admin(*, superadmin: bool) -> UUID:
    """Create an admin with 2FA enabled, optionally the super-admin."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"treasury-admin-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Treasury Admin",
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


def _headers(user_id: UUID, roles: tuple[str, ...] = ("admin",)) -> dict[str, str]:
    """Build bearer auth headers."""
    token = create_access_token(user_id=user_id, roles=list(roles))
    return {"Authorization": f"Bearer {token}"}


async def _accounts() -> list[PlatformBankAccount]:
    """Return every platform bank account row, oldest first."""
    async with async_session_factory() as session:
        return list(
            (
                await session.execute(
                    select(PlatformBankAccount).order_by(PlatformBankAccount.created_at)
                )
            )
            .scalars()
            .all()
        )


async def test_superadmin_sets_the_account_behind_a_24_hour_hold(
    client: AsyncClient,
    bank_context: dict[str, Any],
) -> None:
    """Setting the account stores only safe fields and holds it for 24 hours."""
    superadmin_id = await _admin(superadmin=True)
    await open_step_up_window(bank_context["redis"], superadmin_id)

    response = await client.put(PATH, headers=_headers(superadmin_id), json=PAYLOAD)

    assert response.status_code == 200
    body = response.json()["bank_account"]
    assert body["bank_name"] == "Guaranty Trust Bank"
    assert body["account_last4"] == "6789"
    assert body["account_name"] == "AURACLES TECHNOLOGIES LTD"
    assert "recipient_code" not in body
    assert "account_number" not in body
    usable_from = datetime.fromisoformat(body["usable_from"])
    expected = datetime.now(UTC) + timedelta(hours=24)
    assert abs((usable_from - expected).total_seconds()) < 60

    accounts = await _accounts()
    assert len(accounts) == 1
    stored = accounts[0]
    assert stored.created_by == superadmin_id
    assert stored.replaced_at is None
    assert "0123456789" not in stored.recipient_code_encrypted
    assert decrypt_payout_provider_account_id(
        stored.recipient_code_encrypted
    ).startswith("RCP_")
    assert bank_context["recipients"][0]["account_number"] == "0123456789"

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "platform_bank_account_changed")
        )
    assert audit is not None
    assert audit.actor_id == superadmin_id
    assert audit.metadata_["new_last4"] == "6789"
    assert audit.metadata_["previous_last4"] is None
    assert len(bank_context["notifications"]) == 1
    assert bank_context["notifications"][0]["domain"] == "platform_bank_account"
    assert "6789" in bank_context["notifications"][0]["body"]


async def test_changing_the_account_keeps_history_and_restarts_the_hold(
    client: AsyncClient,
    bank_context: dict[str, Any],
) -> None:
    """A change never edits the old row; it is stamped replaced and kept."""
    superadmin_id = await _admin(superadmin=True)
    await open_step_up_window(bank_context["redis"], superadmin_id)

    await client.put(PATH, headers=_headers(superadmin_id), json=PAYLOAD)
    second = await client.put(
        PATH,
        headers=_headers(superadmin_id),
        json={"account_number": "9876543210", "bank_code": "058"},
    )

    assert second.status_code == 200
    accounts = await _accounts()
    assert len(accounts) == 2
    assert accounts[0].replaced_at is not None
    assert accounts[1].replaced_at is None
    assert accounts[1].account_last4 == "3210"
    async with async_session_factory() as session:
        audits = (
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action == "platform_bank_account_changed")
                    .order_by(AuditLog.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert audits[-1].metadata_["previous_last4"] == "6789"
    assert audits[-1].metadata_["new_last4"] == "3210"


async def test_provider_rejection_stores_nothing(
    client: AsyncClient,
    bank_context: dict[str, Any],
) -> None:
    """If Paystack cannot resolve the account, no row, audit or notice is written."""
    superadmin_id = await _admin(superadmin=True)
    await open_step_up_window(bank_context["redis"], superadmin_id)
    bank_context["recipient_error"] = True

    response = await client.put(PATH, headers=_headers(superadmin_id), json=PAYLOAD)

    assert response.status_code == 502
    assert await _accounts() == []
    assert bank_context["notifications"] == []


async def test_unknown_bank_code_is_rejected(
    client: AsyncClient,
    bank_context: dict[str, Any],
) -> None:
    """A bank code Paystack does not list never reaches recipient creation."""
    superadmin_id = await _admin(superadmin=True)
    await open_step_up_window(bank_context["redis"], superadmin_id)

    response = await client.put(
        PATH,
        headers=_headers(superadmin_id),
        json={"account_number": "0123456789", "bank_code": "999"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "unknown_bank_code"
    assert bank_context["recipients"] == []


async def test_account_number_must_be_ten_digits(
    client: AsyncClient,
    bank_context: dict[str, Any],
) -> None:
    """A NUBAN is exactly ten digits."""
    superadmin_id = await _admin(superadmin=True)
    await open_step_up_window(bank_context["redis"], superadmin_id)

    response = await client.put(
        PATH,
        headers=_headers(superadmin_id),
        json={"account_number": "01234abcde", "bank_code": "058"},
    )

    assert response.status_code == 422


async def test_only_the_superadmin_with_step_up_can_set_it(
    client: AsyncClient,
    bank_context: dict[str, Any],
) -> None:
    """Admins, and a super-admin without a step-up window, are refused."""
    admin_id = await _admin(superadmin=False)
    superadmin_id = await _admin(superadmin=True)
    await open_step_up_window(bank_context["redis"], admin_id)

    anonymous = await client.put(PATH, json=PAYLOAD)
    admin = await client.put(PATH, headers=_headers(admin_id), json=PAYLOAD)
    no_step_up = await client.put(PATH, headers=_headers(superadmin_id), json=PAYLOAD)

    assert anonymous.status_code == 401
    assert admin.status_code == 403
    assert admin.json()["detail"]["error_code"] == "superadmin_required"
    assert no_step_up.status_code == 403
    assert no_step_up.json()["detail"]["error_code"] == "step_up_required"
    assert await _accounts() == []


async def test_every_admin_can_view_the_active_account(
    client: AsyncClient,
    bank_context: dict[str, Any],
) -> None:
    """Viewing needs only the admin role; before setup the account is null."""
    admin_id = await _admin(superadmin=False)
    superadmin_id = await _admin(superadmin=True)
    await open_step_up_window(bank_context["redis"], superadmin_id)

    before = await client.get(PATH, headers=_headers(admin_id))
    await client.put(PATH, headers=_headers(superadmin_id), json=PAYLOAD)
    after = await client.get(PATH, headers=_headers(admin_id))
    operator = await client.get(PATH, headers=_headers(admin_id, ("operator",)))

    assert before.status_code == 200
    assert before.json() == {"bank_account": None}
    assert after.json()["bank_account"]["account_last4"] == "6789"
    assert "recipient_code" not in after.json()["bank_account"]
    assert operator.status_code == 403


async def test_superadmin_lists_banks_without_a_contributor_role(
    client: AsyncClient,
    bank_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The super-admin picks the platform bank without being a Contributor.

    The Contributor bank list answered the admin-only super-admin with
    ``role_required``, which the app treats as unfinished onboarding.
    """

    async def fake_service_list_banks(**_: Any) -> list[PaystackBank]:
        """Return a fixed bank list."""
        return [PaystackBank(name="Guaranty Trust Bank", code="058")]

    monkeypatch.setattr(
        "app.modules.financials.service.paystack.list_banks", fake_service_list_banks
    )
    admin_id = await _admin(superadmin=False)
    superadmin_id = await _admin(superadmin=True)

    by_superadmin = await client.get(
        "/v1/admin/treasury/banks", headers=_headers(superadmin_id)
    )
    by_admin = await client.get("/v1/admin/treasury/banks", headers=_headers(admin_id))

    assert by_superadmin.status_code == 200
    assert by_superadmin.json() == {
        "banks": [{"name": "Guaranty Trust Bank", "code": "058"}]
    }
    assert by_admin.status_code == 403
