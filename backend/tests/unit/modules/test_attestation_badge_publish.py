"""Badge snapshot publish behavior (Module 6c).

publish_badge writes one immutable snapshot per closed+eligible framework
attestation, for all outcomes, idempotently; it writes nothing for
non-framework targets.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import badge_service
from app.modules.attestation.models import Attestation, AttestationBadge, Credential
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework, FrameworkVersion
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear badge-test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AttestationBadge))
            await session.execute(delete(Attestation))
            await session.execute(delete(Credential))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Reset state before and after each badge-publish test."""
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
    """Provide an async session for publish-badge tests."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _make_user(
    *,
    role: str,
    prefix: str,
    display_name: str | None = None,
) -> User:
    """Create a verified user with one approved role row."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=display_name or prefix,
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
        await session.refresh(user)
        return user


async def _make_verified_credential(*, user_id: UUID) -> None:
    """Create one public-safe verified credential for the attestor snapshot."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Credential(
                    user_id=user_id,
                    title="Certified Transformation Lead",
                    issuer="Global Institute",
                    issued_date=date(2024, 1, 1),
                    expires_date=date(2027, 1, 1),
                    verification_status="verified",
                    credential_type="professional",
                )
            )


async def _make_framework(
    *,
    contributor_id: UUID,
    version: str,
) -> tuple[Framework, FrameworkVersion]:
    """Create a published framework plus its immutable current version row."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Badge Test Framework",
                description="Published framework for badge snapshot tests.",
                version=version,
                status="published",
                category="compliance",
                tags=["badge"],
                price=Decimal("199.00"),
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            snapshot = FrameworkVersion(
                framework_id=framework.id,
                version=version,
                change_type="improvement",
                change_log="Published snapshot for badge tests.",
                published_at=datetime.now(UTC),
            )
            session.add(snapshot)
        await session.refresh(framework)
        await session.refresh(snapshot)
        return framework, snapshot


async def _closed_framework_attestation(
    db_session: AsyncSession,
    *,
    outcome: str,
    framework_version: str = "1.2",
) -> Attestation:
    """Create a closed, eligible framework attestation with version capture."""
    contributor = await _make_user(role="contributor", prefix="contributor")
    attestor = await _make_user(
        role="attestor",
        prefix="attestor",
        display_name="Badge Attestor",
    )
    await _make_verified_credential(user_id=attestor.id)
    framework, snapshot = await _make_framework(
        contributor_id=contributor.id,
        version=framework_version,
    )
    attestation = Attestation(
        target_type="framework",
        target_id=framework.id,
        requestor_id=contributor.id,
        attestor_id=attestor.id,
        status="closed",
        outcome=outcome,
        review_type="quality",
        framework_version_id=snapshot.id,
        requested_specializations=["governance"],
        requested_jurisdictions=["US"],
        fee_amount=Decimal("500.00"),
        currency="USD",
        report_published_eligible=True,
        closed_at=datetime.now(UTC),
    )
    db_session.add(attestation)
    await db_session.commit()
    await db_session.refresh(attestation)
    return attestation


async def _closed_operator_attestation(
    db_session: AsyncSession,
    *,
    outcome: str,
) -> Attestation:
    """Create a closed, eligible non-framework attestation."""
    requestor = await _make_user(role="operator", prefix="requestor")
    attestor = await _make_user(role="attestor", prefix="attestor")
    attestation = Attestation(
        target_type="operator",
        target_id=requestor.id,
        requestor_id=requestor.id,
        attestor_id=attestor.id,
        status="closed",
        outcome=outcome,
        review_type="expert",
        requested_specializations=["operations"],
        requested_jurisdictions=["NG"],
        fee_amount=Decimal("300.00"),
        currency="USD",
        report_published_eligible=True,
        closed_at=datetime.now(UTC),
    )
    db_session.add(attestation)
    await db_session.commit()
    await db_session.refresh(attestation)
    return attestation


async def test_publish_writes_snapshot_for_approved_framework(
    db_session: AsyncSession,
) -> None:
    """An approved framework attestation gets a badge snapshot at publish."""
    attestation = await _closed_framework_attestation(
        db_session,
        outcome="approved",
        framework_version="1.2",
    )

    await badge_service.publish_badge(db_session, attestation=attestation)

    badge = await db_session.scalar(
        select(AttestationBadge).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert badge is not None
    assert badge.outcome == "approved"
    assert badge.review_type == attestation.review_type
    assert badge.framework_id == attestation.target_id
    assert badge.attestor_id == attestation.attestor_id
    assert badge.framework_version == "1.2"
    assert isinstance(badge.credentials_snapshot, list)


async def test_publish_writes_snapshot_for_rejected(
    db_session: AsyncSession,
) -> None:
    """A rejected outcome is still snapshotted for complete provenance."""
    attestation = await _closed_framework_attestation(
        db_session,
        outcome="rejected",
    )

    await badge_service.publish_badge(db_session, attestation=attestation)

    count = await db_session.scalar(
        select(func.count(AttestationBadge.id)).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert count == 1


async def test_publish_is_idempotent(db_session: AsyncSession) -> None:
    """Publishing twice writes a single badge row."""
    attestation = await _closed_framework_attestation(
        db_session,
        outcome="approved",
    )

    await badge_service.publish_badge(db_session, attestation=attestation)
    await badge_service.publish_badge(db_session, attestation=attestation)

    count = await db_session.scalar(
        select(func.count(AttestationBadge.id)).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert count == 1


async def test_publish_skips_non_framework_target(
    db_session: AsyncSession,
) -> None:
    """A non-framework target writes no badge row."""
    attestation = await _closed_operator_attestation(
        db_session,
        outcome="approved",
    )

    await badge_service.publish_badge(db_session, attestation=attestation)

    count = await db_session.scalar(
        select(func.count(AttestationBadge.id)).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert count == 0


async def _make_attestor_org(*, name: str, verification_level: int) -> UUID:
    """Create an org with an active attestor profile; return the org id."""
    owner = await _make_user(role="attestor", prefix="org-owner")
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"badge-org-{uuid4().hex[:6]}",
                name=name,
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["governance"],
                    jurisdictions=["US"],
                    sectors=["PE"],
                    framework_categories=["Compliance"],
                    active=True,
                    verification_level=verification_level,
                )
            )
            return org.id


async def _closed_org_framework_attestation(
    db_session: AsyncSession,
    *,
    org_id: UUID,
    outcome: str,
) -> Attestation:
    """Create a closed, eligible org-attested framework attestation."""
    contributor = await _make_user(role="contributor", prefix="contributor")
    framework, snapshot = await _make_framework(
        contributor_id=contributor.id,
        version="2.0",
    )
    attestation = Attestation(
        target_type="framework",
        target_id=framework.id,
        requestor_id=contributor.id,
        attestor_org_id=org_id,
        status="closed",
        outcome=outcome,
        review_type="quality",
        framework_version_id=snapshot.id,
        requested_specializations=["governance"],
        requested_jurisdictions=["US"],
        fee_amount=Decimal("500.00"),
        currency="USD",
        report_published_eligible=True,
        closed_at=datetime.now(UTC),
    )
    db_session.add(attestation)
    await db_session.commit()
    await db_session.refresh(attestation)
    return attestation


async def test_publish_snapshots_org_identity(db_session: AsyncSession) -> None:
    """An org-attested framework badge snapshots org identity, not a member."""
    org_id = await _make_attestor_org(name="Trust Partners LLP", verification_level=3)
    attestation = await _closed_org_framework_attestation(
        db_session,
        org_id=org_id,
        outcome="approved",
    )

    await badge_service.publish_badge(db_session, attestation=attestation)

    badge = await db_session.scalar(
        select(AttestationBadge).where(
            AttestationBadge.attestation_id == attestation.id
        )
    )
    assert badge is not None
    assert badge.attestor_id is None
    assert badge.attestor_org_id == org_id
    assert badge.attestor_display_name == "Trust Partners LLP"
    assert badge.attestor_org_slug is not None
    assert badge.verification_level == 3
    assert badge.credentials_snapshot == []
