"""Unit tests for the public contributor-organization directory service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.organizations import contributor_directory_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgContributorProfile,
    OrgMember,
)
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for contributor directory tests."""
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
async def contributor_directory_state() -> AsyncIterator[None]:
    """Reset contributor directory rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete contributor directory rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(Framework))
            await session.execute(delete(OrgContributorProfile))
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
    """Create and return one verified user for contributor directory tests."""
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


async def _seed_contributor_org(
    *,
    owner: User,
    member: User,
    slug: str,
    name: str,
    capability_status: str = "active",
    verification_level: int = 2,
    reputation_score: Decimal | None = Decimal("81.25"),
    suspended: bool = False,
    published_frameworks: int = 1,
) -> UUID:
    """Create one org contributor profile and its published Framework rows."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                id=uuid4(),
                slug=slug,
                name=name,
                country="US",
                created_by=owner.id,
                suspended_at=datetime.now(UTC) if suspended else None,
            )
            session.add(organization)
            await session.flush()
            owner_member = OrgMember(
                org_id=organization.id,
                user_id=owner.id,
                role="owner",
            )
            plain_member = OrgMember(
                org_id=organization.id,
                user_id=member.id,
                role="member",
            )
            session.add_all([owner_member, plain_member])
            await session.flush()
            session.add(
                OrgCapability(
                    org_id=organization.id,
                    capability="contributor",
                    status=capability_status,
                    activated_at=datetime.now(UTC),
                )
            )
            session.add(
                OrgContributorProfile(
                    org_id=organization.id,
                    active=True,
                    verification_level=verification_level,
                    activated_at=datetime.now(UTC),
                    reputation_score=reputation_score,
                )
            )
            for index in range(published_frameworks):
                session.add(
                    Framework(
                        contributor_id=None,
                        contributor_org_id=organization.id,
                        authoring_member_id=owner_member.id,
                        title=f"{name} Framework {index}",
                        description="Public org contributor framework.",
                        version="1.0.0",
                        status="published",
                        category="framework",
                        sector="financial_services",
                        industry="fund_management",
                        business_function="risk_management",
                        tags=["risk"],
                        tags_text="risk",
                        jurisdiction="US",
                        complexity=3,
                        org_size="mid_market",
                        lifecycle_stage="scale",
                        price=Decimal("499.00"),
                        currency="USD",
                        license_types=["single_user"],
                        published_at=datetime.now(UTC),
                    )
                )
            return organization.id


@pytest.mark.asyncio
async def test_list_contributor_orgs_returns_public_counts_for_active_orgs(
    migrated_database: None,
    contributor_directory_state: None,
) -> None:
    """The public contributor directory lists only active contributor orgs."""
    del migrated_database, contributor_directory_state
    owner = await _create_user("directory-owner")
    member = await _create_user("directory-member")
    await _seed_contributor_org(
        owner=owner,
        member=member,
        slug="listed-org",
        name="Listed Org",
        verification_level=3,
        reputation_score=Decimal("88.40"),
        published_frameworks=2,
    )
    hidden_owner = await _create_user("hidden-owner")
    hidden_member = await _create_user("hidden-member")
    await _seed_contributor_org(
        owner=hidden_owner,
        member=hidden_member,
        slug="hidden-org",
        name="Hidden Org",
        capability_status="suspended",
    )

    async with async_session_factory() as session:
        entries = await contributor_directory_service.list_contributor_orgs(session)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.slug == "listed-org"
    assert entry.name == "Listed Org"
    assert entry.verification_level == 3
    assert entry.published_framework_count == 2
    assert entry.member_count == 2
    assert entry.reputation == Decimal("88.40")


@pytest.mark.asyncio
async def test_get_contributor_org_unknown_slug_raises_404(
    migrated_database: None,
    contributor_directory_state: None,
) -> None:
    """Looking up an unknown contributor org slug returns 404."""
    del migrated_database, contributor_directory_state

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await contributor_directory_service.get_contributor_org(
                session,
                org_slug="missing-org",
            )

    assert exc_info.value.status_code == 404
