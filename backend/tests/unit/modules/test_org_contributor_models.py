"""Unit tests for org contributor foundation models.

Validates the additive organization-side contributor profile and shared legal
identity tables introduced for org-backed Contributor flows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations.models import (
    Organization,
    OrgContributorProfile,
    OrgLegalProfile,
    OrgMember,
)
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org contributor model tests."""
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
async def org_contributor_model_state() -> AsyncIterator[None]:
    """Reset organization contributor foundation tables around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete org-linked rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(OrgLegalProfile))
            await session.execute(delete(OrgContributorProfile))
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
    """Create and return one verified user for org contributor model tests."""
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


async def _seed_organization(owner: User, *, slug: str) -> Organization:
    """Create and return one organization with an owner membership."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=slug,
                name="Contributor Org",
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
async def test_org_contributor_profile_and_legal_profile_round_trip(
    migrated_database: None,
    org_contributor_model_state: None,
) -> None:
    """Org contributor foundation rows persist with the expected defaults."""
    del migrated_database, org_contributor_model_state
    owner = await _create_user("org-contributor-profile")
    organization = await _seed_organization(owner, slug="org-contributor-profile")

    async with async_session_factory() as session:
        async with session.begin():
            contributor_profile = OrgContributorProfile(org_id=organization.id)
            legal_profile = OrgLegalProfile(
                org_id=organization.id,
                legal_name="Auracles Labs Ltd",
                registration_number="RC-123456",
                address={"country": "GB", "city": "London"},
                tax_document_type="other",
                tax_document_key="tax-documents/orgs/test.pdf",
            )
            session.add_all([contributor_profile, legal_profile])

    async with async_session_factory() as session:
        contributor_profile = await session.scalar(
            select(OrgContributorProfile).where(
                OrgContributorProfile.org_id == organization.id
            )
        )
        legal_profile = await session.scalar(
            select(OrgLegalProfile).where(OrgLegalProfile.org_id == organization.id)
        )

    assert contributor_profile is not None
    assert contributor_profile.active is True
    assert contributor_profile.verification_level == 1
    assert legal_profile is not None
    assert legal_profile.legal_name == "Auracles Labs Ltd"
    assert legal_profile.address == {"country": "GB", "city": "London"}
