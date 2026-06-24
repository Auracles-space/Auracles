"""Integration tests for the admin user directory endpoint.

These tests exercise the public admin HTTP contract for listing user accounts
that administrators can inspect and suspend or unsuspend from the frontend.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.shared.models.audit_log import AuditLog


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create bearer auth headers for an admin user."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    roles: list[str],
    created_at: datetime,
    suspended_at: datetime | None = None,
    kyc_status: str = "verified",
) -> User:
    """Create a verified user with approved roles for admin-directory tests."""
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorse9"),
        display_name=display_name,
        email_verified=True,
        kyc_status=kyc_status,
        suspended_at=suspended_at,
        suspension_reason=(
            "Policy review hold." if suspended_at is not None else None
        ),
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    await session.flush()
    for role in roles:
        session.add(
            UserRole(
                user_id=user.id,
                role=role,
                approved_at=created_at,
                created_at=created_at,
            )
        )
    await session.flush()
    return user


async def _cleanup_admin_user_directory_state() -> None:
    """Delete user-directory test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database schema is current for admin user directory tests."""
    backend_dir = Path(__file__).resolve().parents[2]
    sync_engine = create_engine(app.state.settings.sync_database_url)
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(config, "head")
    try:
        yield
    finally:
        command.upgrade(config, "head")
        sync_engine.dispose()


async def test_admin_user_directory_filters_pending_kyc(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """The kyc_pending filter returns only users awaiting KYC review.

    Backs the admin KYC approval flow: admins narrow the directory to pending
    submissions and see each user's kyc_status to act on.
    """
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup_admin_user_directory_state()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                admin = await _create_user(
                    session,
                    email=f"admin-kyc-{uuid4()}@auracles.space",
                    display_name="Admin Reviewer",
                    roles=["admin"],
                    created_at=now - timedelta(days=60),
                )
                pending = await _create_user(
                    session,
                    email=f"pending-kyc-{uuid4()}@auracles.space",
                    display_name="Pending Person",
                    roles=["contributor"],
                    created_at=now - timedelta(days=2),
                    kyc_status="pending",
                )
                await _create_user(
                    session,
                    email=f"verified-kyc-{uuid4()}@auracles.space",
                    display_name="Verified Person",
                    roles=["contributor"],
                    created_at=now - timedelta(days=1),
                    kyc_status="verified",
                )

        response = await client.get(
            "/v1/admin/users",
            headers=auth_headers(admin.id),
            params={"status": "kyc_pending", "page": 1, "page_size": 10},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["user_id"] == str(pending.id)
        assert body["items"][0]["kyc_status"] == "pending"
    finally:
        await _cleanup_admin_user_directory_state()
        await engine.dispose()


async def test_admin_can_search_and_filter_user_directory(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """Admin user directory must support query, suspension filter, and paging."""
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup_admin_user_directory_state()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                admin = await _create_user(
                    session,
                    email=f"admin-users-{uuid4()}@auracles.space",
                    display_name="Admin Reviewer",
                    roles=["admin"],
                    created_at=now - timedelta(days=60),
                )
                await _create_user(
                    session,
                    email=f"ada-ops-{uuid4()}@auracles.space",
                    display_name="Ada Operations",
                    roles=["operator"],
                    created_at=now - timedelta(days=4),
                )
                suspended = await _create_user(
                    session,
                    email=f"ada-contrib-{uuid4()}@auracles.space",
                    display_name="Ada Contributor",
                    roles=["contributor", "developer"],
                    created_at=now - timedelta(days=3),
                    suspended_at=now - timedelta(hours=5),
                )
                await _create_user(
                    session,
                    email=f"bayo-attestor-{uuid4()}@auracles.space",
                    display_name="Bayo Attestor",
                    roles=["attestor"],
                    created_at=now - timedelta(days=2),
                )

        response = await client.get(
            "/v1/admin/users",
            headers=auth_headers(admin.id),
            params={"query": "ada", "status": "suspended", "page": 1, "page_size": 10},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["items"]) == 1
        assert body["items"][0] == {
            "created_at": suspended.created_at.isoformat().replace("+00:00", "Z"),
            "display_name": "Ada Contributor",
            "email": suspended.email,
            "roles": ["contributor", "developer"],
            "suspended": True,
            "suspended_at": suspended.suspended_at.isoformat().replace("+00:00", "Z"),
            "user_id": str(suspended.id),
            "is_superadmin": False,
            "kyc_status": "verified",
        }
    finally:
        await _cleanup_admin_user_directory_state()
        await engine.dispose()
