"""Integration tests for organization payment-method management routes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations import billing_service
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.shared.models.audit_log import AuditLog
from tests.integration.test_financials_payment_methods import (
    FakeRedis,
    FakeStripeCustomer,
    FakeStripePaymentMethod,
    FakeStripeSetupIntent,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist for org payment-method integration tests."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def org_payment_method_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset org/payment rows and replace Stripe calls with test doubles."""
    fake_redis = FakeRedis()
    calls: dict[str, list[Any]] = {
        "customers": [],
        "setup_intents": [],
        "list_methods": [],
        "detached": [],
    }

    await engine.dispose()

    async def cleanup() -> None:
        """Delete auth, org, and audit rows used by org payment-method tests."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()

    async def fake_create_customer(
        *,
        email: str,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> FakeStripeCustomer:
        """Record customer creation and return a stable provider id."""
        calls["customers"].append(
            {"email": email, "name": name, "idempotency_key": idempotency_key}
        )
        return FakeStripeCustomer("cus_org_test_123")

    async def fake_create_setup_intent(
        *,
        customer_id: str,
    ) -> FakeStripeSetupIntent:
        """Record SetupIntent creation and return a client secret."""
        calls["setup_intents"].append(customer_id)
        return FakeStripeSetupIntent("seti_org_test_123", "seti_org_secret_123")

    async def fake_list_payment_methods(
        *,
        customer_id: str,
    ) -> list[FakeStripePaymentMethod]:
        """Record list calls and return one provider-held card."""
        calls["list_methods"].append(customer_id)
        return [FakeStripePaymentMethod("pm_org_test_123")]

    async def fake_detach_payment_method(
        *,
        payment_method_id: str,
    ) -> str:
        """Record detach calls and return the removed provider id."""
        calls["detached"].append(payment_method_id)
        return payment_method_id

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(
        billing_service.stripe,
        "create_customer",
        fake_create_customer,
    )
    monkeypatch.setattr(
        billing_service.stripe,
        "create_setup_intent",
        fake_create_setup_intent,
    )
    monkeypatch.setattr(
        billing_service.stripe,
        "list_payment_methods",
        fake_list_payment_methods,
    )
    monkeypatch.setattr(
        billing_service.stripe,
        "detach_payment_method",
        fake_detach_payment_method,
    )
    try:
        yield {"redis": fake_redis, "calls": calls}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str, *, enable_totp: bool = True) -> tuple[UUID, str]:
    """Create one verified user and return its id with a plaintext TOTP secret."""
    secret = pyotp.random_base32()
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
                totp_enabled=enable_totp,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            return user.id, secret


def _auth_headers(user_id: UUID) -> dict[str, str]:
    """Return bearer auth headers for one user."""
    token = create_access_token(user_id, [])
    return {"Authorization": f"Bearer {token}"}


async def _create_org(
    client: AsyncClient,
    owner_id: UUID,
    prefix: str,
) -> dict[str, str]:
    """Create one organization through the public org-create route."""
    response = await client.post(
        "/v1/orgs",
        json={"slug": f"{prefix}-{uuid4().hex[:6]}", "name": prefix, "country": "US"},
        headers=_auth_headers(owner_id),
    )
    assert response.status_code == 201
    return response.json()


async def _add_member(org_id: UUID, user_id: UUID, *, role: str = "member") -> UUID:
    """Insert one org membership row directly and return its member id."""
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            return member.id


async def test_org_payment_method_setup_route_enforces_admin_auth_and_totp(
    client: AsyncClient,
    migrated_database: None,
    org_payment_method_context: dict[str, Any],
) -> None:
    """Only org admins can start org payment-method setup, and 2FA is required."""
    del migrated_database
    owner_id, owner_totp_secret = await _create_user("org-payments-owner")
    member_user_id, _member_secret = await _create_user("org-payments-member")
    no_totp_owner_id, _unused_secret = await _create_user(
        "org-payments-no-totp",
        enable_totp=False,
    )
    org = await _create_org(client, owner_id, "org-payments")
    no_totp_org = await _create_org(client, no_totp_owner_id, "org-payments-no-totp")
    await _add_member(UUID(org["id"]), member_user_id)

    unauthenticated = await client.post(
        f"/v1/orgs/{org['id']}/financials/payment-methods/setup",
        json={"totp_code": pyotp.TOTP(owner_totp_secret).now()},
    )
    forbidden = await client.post(
        f"/v1/orgs/{org['id']}/financials/payment-methods/setup",
        headers=_auth_headers(member_user_id),
        json={"totp_code": pyotp.TOTP(owner_totp_secret).now()},
    )
    no_totp = await client.post(
        f"/v1/orgs/{no_totp_org['id']}/financials/payment-methods/setup",
        headers=_auth_headers(no_totp_owner_id),
        json={"totp_code": "123456"},
    )
    allowed = await client.post(
        f"/v1/orgs/{org['id']}/financials/payment-methods/setup",
        headers=_auth_headers(owner_id),
        json={"totp_code": pyotp.TOTP(owner_totp_secret).now()},
    )

    async with async_session_factory() as session:
        stored_org = await session.get(Organization, UUID(org["id"]))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "org_payment_method_added")
        )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert no_totp.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json() == {
        "provider": "stripe",
        "setup_intent_id": "seti_org_test_123",
        "client_secret": "seti_org_secret_123",
    }
    assert stored_org is not None
    assert stored_org.stripe_customer_id == "cus_org_test_123"
    customer_calls = org_payment_method_context["calls"]["customers"]
    assert len(customer_calls) == 1
    assert customer_calls[0]["email"].startswith("org-payments-owner-")
    assert customer_calls[0]["name"] == "org-payments"
    assert customer_calls[0]["idempotency_key"] == f"stripe_customer:org:{org['id']}"
    assert org_payment_method_context["calls"]["setup_intents"] == ["cus_org_test_123"]
    assert audit is not None
    assert audit.target_type == "organization"
    assert audit.metadata_["provider"] == "stripe"


async def test_org_payment_method_list_and_delete_routes_enforce_org_scope(
    client: AsyncClient,
    migrated_database: None,
    org_payment_method_context: dict[str, Any],
) -> None:
    """Org admins can list/delete their methods; members cannot and unknown ids 404."""
    del migrated_database
    owner_id, owner_totp_secret = await _create_user("org-payments-owner")
    member_user_id, _member_secret = await _create_user("org-payments-member")
    org = await _create_org(client, owner_id, "org-payments")
    await _add_member(UUID(org["id"]), member_user_id)
    async with async_session_factory() as session:
        async with session.begin():
            stored_org = await session.get(Organization, UUID(org["id"]))
            assert stored_org is not None
            stored_org.stripe_customer_id = "cus_org_existing_123"

    listed = await client.get(
        f"/v1/orgs/{org['id']}/financials/payment-methods",
        headers=_auth_headers(owner_id),
    )
    forbidden_list = await client.get(
        f"/v1/orgs/{org['id']}/financials/payment-methods",
        headers=_auth_headers(member_user_id),
    )
    missing = await client.request(
        "DELETE",
        f"/v1/orgs/{org['id']}/financials/payment-methods/pm_missing_123",
        headers=_auth_headers(owner_id),
        json={"totp_code": pyotp.TOTP(owner_totp_secret).now()},
    )
    removed = await client.request(
        "DELETE",
        f"/v1/orgs/{org['id']}/financials/payment-methods/pm_org_test_123",
        headers=_auth_headers(owner_id),
        # Fresh code from the next step: the prior delete consumed the current
        # one, and TOTP codes are single-use now (M4).
        json={
            "totp_code": pyotp.TOTP(owner_totp_secret).at(
                datetime.now(UTC) + timedelta(seconds=30)
            )
        },
    )
    forbidden_delete = await client.request(
        "DELETE",
        f"/v1/orgs/{org['id']}/financials/payment-methods/pm_org_test_123",
        headers=_auth_headers(member_user_id),
        json={"totp_code": pyotp.TOTP(owner_totp_secret).now()},
    )

    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "org_payment_method_removed")
        )

    assert listed.status_code == 200
    assert listed.json() == {
        "payment_methods": [
            {
                "id": "pm_org_test_123",
                "provider": "stripe",
                "type": "card",
                "brand": "visa",
                "last4": "4242",
                "exp_month": 8,
                "exp_year": 2028,
            }
        ]
    }
    assert forbidden_list.status_code == 403
    assert missing.status_code == 404
    assert removed.status_code == 200
    assert removed.json() == {
        "provider": "stripe",
        "payment_method_id": "pm_org_test_123",
        "removed": True,
    }
    assert forbidden_delete.status_code == 403
    assert org_payment_method_context["calls"]["list_methods"] == [
        "cus_org_existing_123",
        "cus_org_existing_123",
        "cus_org_existing_123",
    ]
    assert org_payment_method_context["calls"]["detached"] == ["pm_org_test_123"]
    assert audit is not None
    assert audit.metadata_["payment_method_ref"] == "****_123"
