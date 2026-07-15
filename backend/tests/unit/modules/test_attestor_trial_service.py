"""Unit tests for the nominee/admin calibration-trial service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation.models import AttestorTrial
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.organizations import attestor_trial_service as svc
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgMember,
)

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class SeededTrialContext:
    """Minimal seeded state for nominee trial-service tests."""

    org_id: UUID
    other_member: OrgMember


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database is upgraded to the current head."""
    settings = get_settings()
    sync_engine = create_engine(
        settings.sync_database_url,
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
async def clean_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset calibration-trial rows between tests."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in dependency order."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AttestorTrial))
                await session.execute(delete(OrgAttestorApplication))
                await session.execute(delete(OrgMember))
                await session.execute(delete(Organization))
                await session.execute(delete(Framework))
                await session.execute(delete(User))

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(*, prefix: str) -> User:
    """Create one verified user row for trial-service tests."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return user


async def _seed_trial_context() -> SeededTrialContext:
    """Create an org application with a nominated member and assigned trial."""
    owner = await _create_user(prefix="trial-owner")
    other_user = await _create_user(prefix="trial-other")

    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"trial-org-{uuid4().hex[:8]}",
                name="Trial Org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            owner_member = OrgMember(org_id=org.id, user_id=owner.id, role="owner")
            other_member = OrgMember(
                org_id=org.id,
                user_id=other_user.id,
                role="member",
            )
            session.add_all([owner_member, other_member])
            await session.flush()

            application = OrgAttestorApplication(
                org_id=org.id,
                status="submitted",
                specializations=[],
                legal_name="Trial Org Ltd",
                registration_number="RC123456",
                incorporation_doc_keys=[],
                sectors=["private_equity"],
                functions=["compliance"],
                jurisdictions=["united_states"],
                credentials_summary="Two decades of PE compliance experience.",
                sample_work={},
                professional_references="Jane Roe, MD.",
                trial_member_id=owner_member.id,
            )
            session.add(application)
            await session.flush()

            framework = Framework(
                id=uuid4(),
                contributor_id=owner.id,
                title="Calibration Fixture",
                description="Calibration framework fixture.",
                version="1.0.0",
                status="published",
                is_calibration=True,
                calibration_review_type="quality",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk"],
                tags_text="risk",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
            )
            session.add(framework)
            await session.flush()

            session.add(
                AttestorTrial(
                    org_application_id=application.id,
                    org_id=org.id,
                    member_id=owner_member.id,
                    seeded_framework_id=framework.id,
                    status="assigned",
                    attempt=1,
                )
            )

            await session.refresh(other_member)
            return SeededTrialContext(org_id=org.id, other_member=other_member)


@pytest.fixture
async def seeded_trial(clean_state: None) -> SeededTrialContext:
    """Seed one active trial and return a non-nominee member context."""
    del clean_state
    return await _seed_trial_context()


async def test_load_nominee_trial_denies_non_nominee(
    seeded_trial: SeededTrialContext,
) -> None:
    """A member who is not the nominated trial member gets 403."""
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.load_nominee_trial(
                session,
                org_id=seeded_trial.org_id,
                member=seeded_trial.other_member,
            )
    assert exc.value.status_code == 403
