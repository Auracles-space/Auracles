"""Framework-version capture on Attestation request submission (Module 6c).

A framework-target request records the version the attestor is contracted to
review; non-framework targets record no version.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import service as attestation_service
from app.modules.attestation.models import Attestation
from app.modules.attestation.schemas import (
    AttestationBrief,
    AttestationRequestCreateRequest,
)
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework, FrameworkVersion
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Remove attestation/framework/user rows touched by these tests."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(Attestation))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Framework))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Start each test from a clean attestation/framework/user state."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


@pytest.fixture
async def db_session(clean_state) -> AsyncIterator[AsyncSession]:
    """Provide an async session for service calls and assertions."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _create_user(*, email: str, roles: list[str]) -> User:
    """Create one verified user with approved role rows."""
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
        await session.refresh(user)
        return user


async def _create_published_framework(
    *,
    contributor_id: UUID,
    version: str,
) -> Framework:
    """Create a published framework plus its matching immutable version row."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Framework Under Review",
                description="Published for version-capture tests.",
                version=version,
                status="published",
                category="compliance",
                tags=["versioned"],
                price=Decimal("199.00"),
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            session.add(
                FrameworkVersion(
                    framework_id=framework.id,
                    version=version,
                    change_type="improvement",
                    change_log="Initial publish snapshot.",
                    published_at=datetime.now(UTC),
                )
            )
        await session.refresh(framework)
        return framework


def _framework_brief() -> AttestationBrief:
    """Return a minimal valid framework attestation brief."""
    return AttestationBrief(
        what_it_does="Maps control ownership.",
        use_case="Internal control review.",
        jurisdiction="US",
        focus_areas="Design quality and evidence traceability.",
        desired_outcome="Quality sign-off badge.",
    )


async def test_framework_target_captures_current_version(
    db_session: AsyncSession,
) -> None:
    """A framework-target request stamps the current published version row."""
    requestor = await _create_user(
        email="framework-owner@auracles.space",
        roles=["contributor"],
    )
    framework = await _create_published_framework(
        contributor_id=requestor.id,
        version="1.2",
    )
    payload = AttestationRequestCreateRequest(
        target_type="framework",
        target_id=framework.id,
        review_type="quality",
        brief=_framework_brief(),
        requested_specializations=["governance"],
        requested_jurisdictions=["US"],
    )

    attestation_id = await attestation_service._create_attestation(
        db_session,
        requestor_id=requestor.id,
        payload=payload,
        amount=attestation_service.Decimal("500.00"),
        initiator_is_owner=True,
        status_value="pending_fee",
    )

    attestation = await db_session.scalar(
        select(Attestation).where(Attestation.id == attestation_id)
    )
    assert attestation is not None
    assert attestation.framework_version_id is not None


async def test_non_framework_target_captures_no_version(
    db_session: AsyncSession,
) -> None:
    """A non-framework target leaves framework_version_id NULL."""
    requestor = await _create_user(
        email="operator-self-attest@auracles.space",
        roles=["operator"],
    )
    payload = AttestationRequestCreateRequest(
        target_type="operator",
        target_id=requestor.id,
        review_type="expert",
        requested_specializations=["operations"],
        requested_jurisdictions=["NG"],
    )

    attestation_id = await attestation_service._create_attestation(
        db_session,
        requestor_id=requestor.id,
        payload=payload,
        amount=attestation_service.Decimal("300.00"),
        initiator_is_owner=True,
        status_value="pending_fee",
    )

    attestation = await db_session.scalar(
        select(Attestation).where(Attestation.id == attestation_id)
    )
    assert attestation is not None
    assert attestation.framework_version_id is None
