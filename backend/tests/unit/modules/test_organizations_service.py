"""Unit tests for Organizations Core service behaviors."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations import service
from app.modules.organizations.dependencies import OrgContext
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current database schema exists for org service tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def org_service_state() -> AsyncIterator[None]:
    """Reset organization and identity rows around each unit test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-linked rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> User:
    """Create and return a verified user row for service tests."""
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
            await session.refresh(user)
            return user


async def _seed_organization(owner: User, *, slug: str = "org-service") -> Organization:
    """Create and return one organization with an owner membership."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=slug,
                name="Org Service",
                country="GB",
                created_by=owner.id,
            )
            session.add(organization)
            await session.flush()
            session.add(
                OrgMember(org_id=organization.id, user_id=owner.id, role="owner")
            )
            await session.refresh(organization)
            return organization


@pytest.mark.asyncio
async def test_get_public_org_only_returns_active_capabilities(
    migrated_database: None,
    org_service_state: None,
) -> None:
    """Public org profile exposes only active capabilities and member count."""
    del migrated_database, org_service_state
    owner = await _create_user("org-public-unit")
    organization = await _seed_organization(owner, slug="public-unit")
    async with async_session_factory() as session:
        async with session.begin():
            session.add_all(
                [
                    OrgCapability(
                        org_id=organization.id,
                        capability="attestor",
                        status="active",
                    ),
                    OrgCapability(
                        org_id=organization.id,
                        capability="operator",
                        status="pending",
                    ),
                ]
            )

    async with async_session_factory() as session:
        profile = await service.get_public_org(db=session, slug="PUBLIC-UNIT")

    assert profile.slug == "public-unit"
    assert profile.member_count == 1
    assert profile.active_capabilities == ["attestor"]


@pytest.mark.asyncio
async def test_deactivate_organization_blocks_active_capabilities(
    migrated_database: None,
    org_service_state: None,
) -> None:
    """Deactivation is rejected while the organization has an active capability."""
    del migrated_database, org_service_state
    owner = await _create_user("org-deactivate-unit")
    organization = await _seed_organization(owner, slug="deactivate-unit")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=organization.id,
                    capability="attestor",
                    status="active",
                )
            )

    async with async_session_factory() as session:
        context = OrgContext(
            org=organization,
            member=OrgMember(
                org_id=organization.id,
                user_id=owner.id,
                role="owner",
                joined_at=datetime.now(UTC),
            ),
            user=owner,
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.deactivate_organization(db=session, context=context)

    assert exc_info.value.status_code == 409
