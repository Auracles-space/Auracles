"""Integration tests for Phase 5a Developer application workflows."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
)
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for routes that need TOTP failure bookkeeping."""

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


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 5a developer tables exist for endpoint tests."""
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
async def developer_application_context() -> AsyncIterator[FakeRedis]:
    """Reset developer/auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(PartnerCommission))
            await session.execute(delete(ApiKey))
            await session.execute(delete(DeveloperAccount))
            await session.execute(delete(DeveloperApplication))
            await session.execute(delete(AuditLog))
            await session.execute(delete(Transaction))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))

    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(PartnerCommission))
                await session.execute(delete(ApiKey))
                await session.execute(delete(DeveloperAccount))
                await session.execute(delete(DeveloperApplication))
                await session.execute(delete(AuditLog))
                await session.execute(delete(Transaction))
                await session.execute(delete(Framework))
                await session.execute(delete(UserRole))
                await session.execute(delete(User))
        await engine.dispose()


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved role rows for auth tests."""
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


async def create_admin_user() -> tuple[UUID, str]:
    """Create an admin user with TOTP enabled for sensitive review routes."""
    secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="developer-review-admin@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Developer Review Admin",
                email_verified=True,
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="admin",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id, secret


async def create_developer_user(email: str) -> tuple[UUID, UUID]:
    """Create an approved Developer account for API key lifecycle tests."""
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
            session.add(
                UserRole(
                    user_id=user.id,
                    role="developer",
                    approved_at=datetime.now(UTC),
                )
            )
            application = DeveloperApplication(
                user_id=user.id,
                company_name="Developer Key Co.",
                website="https://developer-key.example.com",
                use_case="Embed Auracles catalog into a partner workflow.",
                status="approved",
                reviewed_at=datetime.now(UTC),
            )
            session.add(application)
            await session.flush()
            account = DeveloperAccount(
                user_id=user.id,
                application_id=application.id,
                company_name=application.company_name,
            )
            session.add(account)
            await session.flush()
            return user.id, account.id


async def create_recent_partner_sales(account_id: UUID, count: int) -> None:
    """Create recent non-voided Partner commission rows for tier progress."""
    contributor_id = await create_user(
        f"tier-progress-contributor-{uuid4()}@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user(
        f"tier-progress-operator-{uuid4()}@auracles.space",
        ["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            api_key = ApiKey(
                developer_account_id=account_id,
                name="Tier progress key",
                key_prefix="ak_tierprog",
                key_hash=f"tier-progress-hash-{uuid4()}",
                scopes=["purchase:write"],
            )
            session.add(api_key)
            framework = Framework(
                contributor_id=contributor_id,
                title="Tier Progress Framework",
                description="Framework used by Developer tier endpoint tests.",
                status="published",
                category="operations",
                tags=["tier"],
                tags_text="tier",
                price=Decimal("100.00"),
                currency="USD",
                license_types=["team"],
            )
            session.add(framework)
            await session.flush()
            for index in range(count):
                transaction = Transaction(
                    payer_id=operator_id,
                    payee_id=contributor_id,
                    amount=Decimal("100.00"),
                    currency="USD",
                    platform_commission=Decimal("0.00"),
                    net_amount=Decimal("100.00"),
                    transaction_type="purchase",
                    status="completed",
                    provider="stripe",
                    provider_ref=f"pi_tier_progress_{index}_{uuid4()}",
                    ref_id=framework.id,
                    ref_type="framework",
                )
                session.add(transaction)
                await session.flush()
                session.add(
                    PartnerCommission(
                        api_key_id=api_key.id,
                        developer_account_id=account_id,
                        transaction_id=transaction.id,
                        framework_id=framework.id,
                        sale_amount=Decimal("100.00"),
                        currency="USD",
                        tier_at_sale=1,
                        tier_rate=Decimal("0.0500"),
                        commission_amount=Decimal("5.00"),
                        status="cleared",
                        created_at=datetime.now(UTC) - timedelta(days=1),
                    )
                )


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


def application_payload() -> dict[str, str]:
    """Return a valid Developer application request payload."""
    return {
        "company_name": "Partner Systems Inc.",
        "website": "https://partners.example.com",
        "use_case": "We want to embed Auracles Framework discovery in our CRM.",
    }


def api_key_payload() -> dict[str, object]:
    """Return a valid API key creation request payload."""
    return {
        "name": "Production CRM integration",
        "scopes": ["catalog:read", "purchase:write"],
    }


async def test_user_submits_and_lists_own_developer_application(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """Authenticated users can submit and list Developer applications."""
    del migrated_database, developer_application_context
    user_id = await create_user("developer-candidate@auracles.space", ["operator"])

    submitted = await client.post(
        "/v1/developer/applications",
        headers=auth_headers(user_id, ["operator"]),
        json=application_payload(),
    )
    mine = await client.get(
        "/v1/developer/applications/mine",
        headers=auth_headers(user_id, ["operator"]),
    )

    assert submitted.status_code == 201
    assert submitted.json()["status"] == "pending"
    assert submitted.json()["user_id"] == str(user_id)
    assert submitted.json()["company_name"] == "Partner Systems Inc."
    assert mine.status_code == 200
    assert [item["id"] for item in mine.json()["applications"]] == [
        submitted.json()["id"]
    ]

    async with async_session_factory() as session:
        application = await session.get(
            DeveloperApplication,
            UUID(submitted.json()["id"]),
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "developer_application_submitted"
            )
        )

    assert application is not None
    assert application.status == "pending"
    assert audit is not None


async def test_pending_developer_application_can_be_withdrawn_and_reapplied(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """Users can withdraw a pending Developer application and submit another."""
    del migrated_database, developer_application_context
    user_id = await create_user("withdraw-developer@auracles.space", ["operator"])
    headers = auth_headers(user_id, ["operator"])

    first = await client.post(
        "/v1/developer/applications",
        headers=headers,
        json=application_payload(),
    )
    duplicate = await client.post(
        "/v1/developer/applications",
        headers=headers,
        json=application_payload(),
    )
    withdrawn = await client.patch(
        f"/v1/developer/applications/{first.json()['id']}/withdraw",
        headers=headers,
    )
    second = await client.post(
        "/v1/developer/applications",
        headers=headers,
        json=application_payload(),
    )

    async with async_session_factory() as session:
        withdrawn_row = await session.get(
            DeveloperApplication,
            UUID(first.json()["id"]),
        )
        withdrawal_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "developer_application_withdrawn"
            )
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    assert withdrawn_row is not None
    assert withdrawn_row.status == "withdrawn"
    assert withdrawal_audit is not None


async def test_admin_approves_developer_application_with_account_and_role(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """Admin approval creates the Developer account and approves role access."""
    del migrated_database, developer_application_context
    candidate_id = await create_user("approved-developer@auracles.space", ["operator"])
    admin_id, totp_secret = await create_admin_user()
    submitted = await client.post(
        "/v1/developer/applications",
        headers=auth_headers(candidate_id, ["operator"]),
        json=application_payload(),
    )

    listed = await client.get(
        "/v1/admin/developer/applications?status=pending",
        headers=auth_headers(admin_id, ["admin"]),
    )
    approved = await client.post(
        f"/v1/admin/developer/applications/{submitted.json()['id']}/review",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "decision": "approved",
            "feedback": "Partner API use case is clear.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )

    async with async_session_factory() as session:
        account = await session.scalar(
            select(DeveloperAccount).where(DeveloperAccount.user_id == candidate_id)
        )
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == candidate_id,
                UserRole.role == "developer",
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "developer_application_approved"
            )
        )

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["applications"]] == [
        submitted.json()["id"]
    ]
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewed_by"] == str(admin_id)
    assert account is not None
    assert account.status == "active"
    assert account.company_name == "Partner Systems Inc."
    assert account.commission_tier == 1
    assert role is not None
    assert role.approved_at is not None
    assert role.approved_by == admin_id
    assert audit is not None


async def test_admin_rejects_developer_application_with_feedback(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """Admin rejection stores feedback but does not approve Developer access."""
    del migrated_database, developer_application_context
    candidate_id = await create_user("rejected-developer@auracles.space", ["operator"])
    admin_id, totp_secret = await create_admin_user()
    submitted = await client.post(
        "/v1/developer/applications",
        headers=auth_headers(candidate_id, ["operator"]),
        json=application_payload(),
    )

    missing_feedback = await client.post(
        f"/v1/admin/developer/applications/{submitted.json()['id']}/review",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "decision": "rejected",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )
    rejected = await client.post(
        f"/v1/admin/developer/applications/{submitted.json()['id']}/review",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "decision": "rejected",
            "feedback": "Please provide a production integration plan.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )

    async with async_session_factory() as session:
        account = await session.scalar(
            select(DeveloperAccount).where(DeveloperAccount.user_id == candidate_id)
        )
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == candidate_id,
                UserRole.role == "developer",
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "developer_application_rejected"
            )
        )

    assert missing_feedback.status_code == 422
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert (
        rejected.json()["admin_feedback"]
        == "Please provide a production integration plan."
    )
    assert rejected.json()["reviewed_by"] == str(admin_id)
    assert account is None
    assert role is None
    assert audit is not None


async def test_developer_generates_key_raw_once_and_lists_masked_metadata(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """Approved Developers can create API keys and only see the raw key once."""
    del migrated_database, developer_application_context
    user_id, account_id = await create_developer_user("keys@auracles.space")
    headers = auth_headers(user_id, ["developer"])

    created = await client.post(
        "/v1/developer/api-keys",
        headers=headers,
        json=api_key_payload(),
    )
    listed = await client.get("/v1/developer/api-keys", headers=headers)

    assert created.status_code == 201
    created_body = created.json()
    raw_key = created_body["raw_key"]
    assert raw_key.startswith("ak_")
    assert created_body["key_prefix"] == raw_key[:12]
    assert created_body["scopes"] == ["catalog:read", "purchase:write"]
    assert listed.status_code == 200
    assert listed.json()["api_keys"] == [
        {
            "id": created_body["id"],
            "name": "Production CRM integration",
            "key_prefix": raw_key[:12],
            "scopes": ["catalog:read", "purchase:write"],
            "status": "active",
            "expires_at": None,
            "revoked_at": None,
            "last_used_at": None,
            "created_at": created_body["created_at"],
        }
    ]
    assert "raw_key" not in listed.text

    async with async_session_factory() as session:
        api_key = await session.get(ApiKey, UUID(created_body["id"]))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "api_key_created")
        )

    assert api_key is not None
    assert api_key.developer_account_id == account_id
    assert api_key.key_hash == hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    assert raw_key not in api_key.key_hash
    assert audit is not None


async def test_developer_api_key_rejects_unknown_scopes(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """API key creation rejects scopes outside the known Partner API set."""
    del migrated_database, developer_application_context
    user_id, account_id = await create_developer_user("bad-scope@auracles.space")

    rejected = await client.post(
        "/v1/developer/api-keys",
        headers=auth_headers(user_id, ["developer"]),
        json={
            "name": "Bad key",
            "scopes": ["catalog:read", "admin:write"],
        },
    )

    async with async_session_factory() as session:
        key_count = len(
            (
                await session.execute(
                    select(ApiKey).where(ApiKey.developer_account_id == account_id)
                )
            )
            .scalars()
            .all()
        )

    assert rejected.status_code == 422
    assert key_count == 0


async def test_developer_updates_and_revokes_own_api_key(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """Developers can relabel and revoke API keys they own."""
    del migrated_database, developer_application_context
    user_id, _account_id = await create_developer_user("revoke-key@auracles.space")
    headers = auth_headers(user_id, ["developer"])
    created = await client.post(
        "/v1/developer/api-keys",
        headers=headers,
        json=api_key_payload(),
    )
    key_id = created.json()["id"]

    updated = await client.patch(
        f"/v1/developer/api-keys/{key_id}",
        headers=headers,
        json={"name": "Renamed production integration"},
    )
    revoked = await client.delete(
        f"/v1/developer/api-keys/{key_id}",
        headers=headers,
    )
    listed = await client.get("/v1/developer/api-keys", headers=headers)

    async with async_session_factory() as session:
        api_key = await session.get(ApiKey, UUID(key_id))
        update_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "api_key_updated")
        )
        revoke_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "api_key_revoked")
        )

    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed production integration"
    assert updated.json()["status"] == "active"
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["revoked_at"] is not None
    assert listed.status_code == 200
    assert listed.json()["api_keys"][0]["name"] == "Renamed production integration"
    assert listed.json()["api_keys"][0]["status"] == "revoked"
    assert "raw_key" not in listed.text
    assert api_key is not None
    assert api_key.status == "revoked"
    assert api_key.revoked_at is not None
    assert update_audit is not None
    assert revoke_audit is not None


async def test_developer_cannot_manage_another_developers_api_key(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """Developer API key mutation is scoped to the owning Developer account."""
    del migrated_database, developer_application_context
    owner_id, _owner_account_id = await create_developer_user(
        "key-owner@auracles.space"
    )
    other_id, _other_account_id = await create_developer_user(
        "key-outsider@auracles.space"
    )
    created = await client.post(
        "/v1/developer/api-keys",
        headers=auth_headers(owner_id, ["developer"]),
        json=api_key_payload(),
    )
    key_id = created.json()["id"]

    update_denied = await client.patch(
        f"/v1/developer/api-keys/{key_id}",
        headers=auth_headers(other_id, ["developer"]),
        json={"name": "Stolen label"},
    )
    revoke_denied = await client.delete(
        f"/v1/developer/api-keys/{key_id}",
        headers=auth_headers(other_id, ["developer"]),
    )

    async with async_session_factory() as session:
        api_key = await session.get(ApiKey, UUID(key_id))

    assert update_denied.status_code == 404
    assert revoke_denied.status_code == 404
    assert api_key is not None
    assert api_key.name == "Production CRM integration"
    assert api_key.status == "active"


async def test_developer_reads_tier_progress(
    client: AsyncClient,
    migrated_database: None,
    developer_application_context: FakeRedis,
) -> None:
    """Developers can read current commission tier and next-tier progress."""
    del migrated_database, developer_application_context
    user_id, account_id = await create_developer_user("tier-progress@auracles.space")
    await create_recent_partner_sales(account_id, 99)

    response = await client.get(
        "/v1/developer/tier",
        headers=auth_headers(user_id, ["developer"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_tier"] == 1
    assert body["current_rate"] == "0.0500"
    assert body["prior_30d_sales_count"] == 99
    assert body["next_tier"] == 2
    assert body["next_tier_sales_required"] == 1
    assert body["tier_recalculated_at"] is None
    assert body["tiers"] == [
        {"tier": 1, "min_sales": 0, "max_sales": 99, "rate": "0.0500"},
        {"tier": 2, "min_sales": 100, "max_sales": 499, "rate": "0.0800"},
        {"tier": 3, "min_sales": 500, "max_sales": None, "rate": "0.1200"},
    ]
