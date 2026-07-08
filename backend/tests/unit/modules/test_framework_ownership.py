"""Unit tests for org-capable Framework ownership.

These tests lock the additive XOR ownership model for Framework sellers before
later org-authoring tasks build on top of it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.ownership import resolve_framework_seller
from app.modules.organizations.models import Organization, OrgMember
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for framework ownership tests."""
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
async def framework_ownership_state() -> AsyncIterator[None]:
    """Reset framework and identity state around each ownership test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete Framework rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(Framework))
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
    """Create and return one verified user for framework ownership tests."""
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


async def _create_organization(owner: User, *, slug: str) -> Organization:
    """Create and return one organization with an owner membership."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=slug,
                name="Framework Seller Org",
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


def _framework_kwargs() -> dict[str, object]:
    """Return minimal valid Framework fields for ownership model tests."""
    return {
        "title": "Risk Operating System",
        "description": "A governance Framework.",
        "category": "framework",
        "price": Decimal("199.00"),
        "currency": "USD",
        "license_types": ["single_user"],
    }


@pytest.mark.asyncio
async def test_framework_seller_xor_rejects_both_and_neither(
    migrated_database: None,
    framework_ownership_state: None,
) -> None:
    """Framework persistence must reject both-seller and no-seller rows."""
    del migrated_database, framework_ownership_state
    user = await _create_user("framework-owner")
    organization = await _create_organization(user, slug="framework-owner-org")

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Framework(
                        contributor_id=user.id,
                        contributor_org_id=organization.id,
                        **_framework_kwargs(),
                    )
                )
                await session.flush()

    async with async_session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Framework(
                        contributor_id=None,
                        contributor_org_id=None,
                        **_framework_kwargs(),
                    )
                )
                await session.flush()


def test_resolve_framework_seller_prefers_org_when_org_owner_is_set() -> None:
    """Seller resolution returns the org branch when org ownership is stamped."""
    org_id = uuid4()
    framework = Framework(
        contributor_id=None,
        contributor_org_id=org_id,
        **_framework_kwargs(),
    )

    seller = resolve_framework_seller(framework)

    assert seller.kind == "org"
    assert seller.org_id == org_id
    assert seller.user_id is None


def test_resolve_framework_seller_returns_user_when_user_owner_is_set() -> None:
    """Seller resolution returns the user branch for individual Frameworks."""
    user_id = uuid4()
    framework = Framework(
        contributor_id=user_id,
        contributor_org_id=None,
        **_framework_kwargs(),
    )

    seller = resolve_framework_seller(framework)

    assert seller.kind == "user"
    assert seller.user_id == user_id
    assert seller.org_id is None
