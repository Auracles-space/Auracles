"""Integration tests scoping query-parameter token auth to download endpoints.

The `?token=` fallback exists only so browser-navigated redirect downloads
(GDPR export bundle, purchase invoice PDF) can authenticate without headers.
Every other endpoint must require the Authorization header, so a leaked URL
never carries a usable credential for general API access.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.gdpr.models import DataExportRequest
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import gdpr_beat


class FakeS3Storage:
    """S3 test double returning deterministic presigned URLs."""

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Return a deterministic fake presigned GET URL."""
        return f"https://s3.test/{bucket}/{key}?expires={expires_in}"


class FakeRedis:
    """Redis test double satisfying the download rate limiter."""

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        store = self.__dict__.setdefault("values", {})
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.__dict__.setdefault("values", {})[key] = value

    async def incr(self, key: str) -> int:
        """Return a count under any rate limit."""
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        """Accept a TTL without storing it."""

    async def ttl(self, key: str) -> int:
        """Return Redis' no-expiry sentinel."""
        return -1


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure application tables exist."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state() -> AsyncIterator[None]:
    """Reset export and audit state around each test."""
    from app.core.redis import get_redis

    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(DataExportRequest))
        await session.execute(delete(AuditLog))
        await session.commit()
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_user(prefix: str, role: str) -> UUID:
    """Create a verified user with one approved role and a unique email."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
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
                    role=role,
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id


async def test_general_endpoint_rejects_query_param_token(
    client: AsyncClient,
    migrated_database: None,
    clean_state: None,
) -> None:
    """A general API endpoint must not authenticate via ?token= query parameter.

    Only the redirect-download endpoints may accept the query fallback; a URL
    carrying the token must be useless against the rest of the API.
    """
    del migrated_database, clean_state
    user_id = await create_user("query-scope-general", "operator")
    token = create_access_token(user_id, ["operator"])

    header_response = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    query_response = await client.get("/v1/auth/me", params={"token": token})

    assert header_response.status_code == 200
    assert query_response.status_code == 401


async def test_role_gated_endpoint_rejects_query_param_token(
    client: AsyncClient,
    migrated_database: None,
    clean_state: None,
) -> None:
    """Role-gated endpoints must not authenticate via ?token= query parameter."""
    del migrated_database, clean_state
    user_id = await create_user("query-scope-role", "operator")
    token = create_access_token(user_id, ["operator"])

    response = await client.get(
        "/v1/financials/purchases",
        params={"token": token},
    )

    assert response.status_code == 401


async def test_gdpr_export_download_accepts_query_param_token(
    client: AsyncClient,
    migrated_database: None,
    clean_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The GDPR export download keeps accepting ?token= for browser navigation."""
    del migrated_database, clean_state
    monkeypatch.setattr(gdpr_beat.s3, "storage", FakeS3Storage())
    user_id = await create_user("query-scope-gdpr", "operator")
    token = create_access_token(user_id, ["operator"])
    async with async_session_factory() as session:
        async with session.begin():
            request = DataExportRequest(
                user_id=user_id,
                status="ready",
                bundle_key="gdpr-exports/test/query-scope.json",
                completed_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            session.add(request)
            await session.flush()
            request_id = request.id

    response = await client.get(
        f"/v1/gdpr/exports/{request_id}/download",
        params={"token": token},
        follow_redirects=False,
    )

    assert response.status_code == 302


async def test_purchase_invoice_accepts_query_param_token(
    client: AsyncClient,
    migrated_database: None,
    clean_state: None,
) -> None:
    """The purchase invoice download keeps accepting ?token= for navigation.

    An unknown transaction id must reach the service (404), proving the query
    token authenticated and passed the operator role gate rather than 401ing.
    """
    del migrated_database, clean_state
    user_id = await create_user("query-scope-invoice", "operator")
    token = create_access_token(user_id, ["operator"])

    response = await client.get(
        f"/v1/financials/purchases/{uuid4()}/invoice",
        params={"token": token},
        follow_redirects=False,
    )

    assert response.status_code == 404
