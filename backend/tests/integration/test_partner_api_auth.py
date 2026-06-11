"""Integration tests for Phase 5a Partner API key authentication."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole
from app.modules.developer.auth import (
    PartnerApiContext,
    PartnerApiRequestLoggingMiddleware,
    require_api_key_scope,
)
from app.modules.developer.models import (
    ApiKey,
    ApiRequestLog,
    DeveloperAccount,
    DeveloperApplication,
)
from app.modules.notifications.models import Notification
from app.shared.models.audit_log import AuditLog

CatalogReadContext = Annotated[
    PartnerApiContext,
    Depends(require_api_key_scope("catalog:read")),
]
PurchaseWriteContext = Annotated[
    PartnerApiContext,
    Depends(require_api_key_scope("purchase:write")),
]


class FakeRedis:
    """Redis test double for API key rate-limit and notification throttles."""

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string value."""
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        """Set a string value, respecting the NX flag."""
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL request without simulating time passage."""
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        """Delete string and sorted-set keys."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.sorted_sets)
            self.values.pop(key, None)
            self.sorted_sets.pop(key, None)
            self.ttls.pop(key, None)
        return removed

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        key: str,
        now_ms: int,
        window_ms: int,
        limit: int,
    ) -> list[int]:
        """Emulate the sliding-window Lua script used by production Redis."""
        bucket = self.sorted_sets.setdefault(key, {})
        cutoff = now_ms - window_ms
        for member, score in list(bucket.items()):
            if score < cutoff:
                bucket.pop(member, None)
        if len(bucket) >= limit:
            return [0, len(bucket)]
        bucket[f"{now_ms}:{len(bucket)}"] = float(now_ms)
        return [1, len(bucket)]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 5a developer tables exist for endpoint tests."""
    settings = get_settings()
    sync_engine = create_engine(
        settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def partner_auth_context() -> AsyncIterator[FakeRedis]:
    """Reset partner auth state and install a Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(ApiRequestLog))
            await session.execute(delete(Notification))
            await session.execute(delete(ApiKey))
            await session.execute(delete(DeveloperAccount))
            await session.execute(delete(DeveloperApplication))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))

    try:
        yield fake_redis
    finally:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(ApiRequestLog))
                await session.execute(delete(Notification))
                await session.execute(delete(ApiKey))
                await session.execute(delete(DeveloperAccount))
                await session.execute(delete(DeveloperApplication))
                await session.execute(delete(AuditLog))
                await session.execute(delete(UserRole))
                await session.execute(delete(User))
        await engine.dispose()


async def create_partner_api_key(
    raw_key: str,
    scopes: list[str],
    rate_limit_per_min: int = 60,
    status: str = "active",
) -> tuple[UUID, UUID]:
    """Create an approved Developer account and API key for auth tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{raw_key}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=raw_key,
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
                company_name="Partner Auth Co.",
                website="https://partner-auth.example.com",
                use_case="Exercise Partner API authentication.",
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
            api_key = ApiKey(
                developer_account_id=account.id,
                name="Partner test key",
                key_prefix=raw_key[:12],
                key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
                scopes=scopes,
                rate_limit_per_min=rate_limit_per_min,
                status=status,
            )
            session.add(api_key)
            await session.flush()
            return api_key.id, account.id


def build_test_app(fake_redis: FakeRedis) -> FastAPI:
    """Build a test-only app that uses the production Partner API dependency."""
    test_app = FastAPI()
    test_app.add_middleware(PartnerApiRequestLoggingMiddleware)
    test_app.dependency_overrides[get_redis] = lambda: fake_redis

    @test_app.get("/partner/protected")
    async def protected(context: CatalogReadContext) -> dict[str, str]:
        """Return the authenticated API key id for dependency verification."""
        return {"api_key_id": str(context.api_key.id)}

    @test_app.post("/partner/purchase")
    async def purchase(context: PurchaseWriteContext) -> dict[str, str]:
        """Return the authenticated API key id for scope verification."""
        return {"api_key_id": str(context.api_key.id)}

    return test_app


@pytest.fixture
async def partner_client(
    partner_auth_context: FakeRedis,
) -> AsyncIterator[AsyncClient]:
    """Provide an HTTP client for the test-only Partner API app."""
    test_app = build_test_app(partner_auth_context)
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as client:
        yield client


async def test_partner_api_key_authenticates_logs_and_notifies_at_threshold(
    partner_client: AsyncClient,
    migrated_database: None,
    partner_auth_context: FakeRedis,
) -> None:
    """Valid X-API-Key auth enforces scope, logs usage, and notifies at 80%."""
    del migrated_database, partner_auth_context
    raw_key = "ak_valid_partner_key"
    api_key_id, _account_id = await create_partner_api_key(
        raw_key=raw_key,
        scopes=["catalog:read"],
        rate_limit_per_min=5,
    )

    responses = [
        await partner_client.get(
            "/partner/protected",
            headers={"X-API-Key": raw_key},
        )
        for _ in range(4)
    ]

    async with async_session_factory() as session:
        logs = (
            (
                await session.execute(
                    select(ApiRequestLog)
                    .where(ApiRequestLog.api_key_id == api_key_id)
                    .order_by(ApiRequestLog.created_at)
                )
            )
            .scalars()
            .all()
        )
        notification = await session.scalar(
            select(Notification).where(
                Notification.notification_type == "api_rate_limit_threshold"
            )
        )

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert responses[0].json() == {"api_key_id": str(api_key_id)}
    assert len(logs) == 4
    assert logs[-1].endpoint == "/partner/protected"
    assert logs[-1].method == "GET"
    assert logs[-1].status_code == 200
    assert notification is not None
    assert notification.dedupe_key is not None
    assert notification.dedupe_key.startswith(f"api-rate-threshold:{api_key_id}:")


async def test_partner_api_key_rejects_wrong_scope_and_revoked_key(
    partner_client: AsyncClient,
    migrated_database: None,
    partner_auth_context: FakeRedis,
) -> None:
    """Partner auth returns 403 for wrong scope and 401 for revoked keys."""
    del migrated_database, partner_auth_context
    scoped_key = "ak_scoped_partner_key"
    revoked_key = "ak_revoked_partner_key"
    await create_partner_api_key(raw_key=scoped_key, scopes=["catalog:read"])
    await create_partner_api_key(
        raw_key=revoked_key,
        scopes=["catalog:read", "purchase:write"],
        status="revoked",
    )

    wrong_scope = await partner_client.post(
        "/partner/purchase",
        headers={"X-API-Key": scoped_key},
    )
    revoked = await partner_client.get(
        "/partner/protected",
        headers={"X-API-Key": revoked_key},
    )

    async with async_session_factory() as session:
        wrong_scope_log = await session.scalar(
            select(ApiRequestLog).where(ApiRequestLog.status_code == 403)
        )

    assert wrong_scope.status_code == 403
    assert revoked.status_code == 401
    assert wrong_scope_log is not None


async def test_partner_api_key_rate_limit_blocks_after_limit(
    partner_client: AsyncClient,
    migrated_database: None,
    partner_auth_context: FakeRedis,
) -> None:
    """Partner API key requests are blocked with 429 after the per-key limit."""
    del migrated_database, partner_auth_context
    raw_key = "ak_limited_partner_key"
    api_key_id, _account_id = await create_partner_api_key(
        raw_key=raw_key,
        scopes=["catalog:read"],
        rate_limit_per_min=2,
    )

    first = await partner_client.get(
        "/partner/protected",
        headers={"X-API-Key": raw_key},
    )
    second = await partner_client.get(
        "/partner/protected",
        headers={"X-API-Key": raw_key},
    )
    limited = await partner_client.get(
        "/partner/protected",
        headers={"X-API-Key": raw_key},
    )

    async with async_session_factory() as session:
        rate_limit_log = await session.scalar(
            select(ApiRequestLog).where(
                ApiRequestLog.api_key_id == api_key_id,
                ApiRequestLog.status_code == 429,
            )
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert rate_limit_log is not None


async def test_invalid_partner_api_key_audits_without_usage_log(
    partner_client: AsyncClient,
    migrated_database: None,
    partner_auth_context: FakeRedis,
) -> None:
    """Invalid API keys return 401 and are audited without API usage rows."""
    del migrated_database, partner_auth_context

    response = await partner_client.get(
        "/partner/protected",
        headers={"X-API-Key": "ak_invalid_partner_key"},
    )

    async with async_session_factory() as session:
        usage_log = await session.scalar(select(ApiRequestLog))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "partner_api_key_invalid")
        )

    assert response.status_code == 401
    assert usage_log is None
    assert audit is not None
