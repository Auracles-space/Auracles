"""Unit tests for the attestation report PDF HTML builder."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationArtifactAccess,
    AttestationClarification,
    AttestationDispute,
    AttestationOffer,
    AttestationRubricDimension,
    AttestationRubricScore,
    AttestationUploadSession,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgMember,
)
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import attestation_pdf

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear attestation PDF test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationClarification))
            await session.execute(delete(AttestationAnnotation))
            await session.execute(delete(AttestationRubricScore))
            await session.execute(delete(AttestationArtifactAccess))
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Reset attestation PDF state before and after each test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


async def _make_user(role: str, prefix: str) -> User:
    """Create one verified user with one approved role row."""
    async with async_session_factory() as session:
        user = User(
            email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name=prefix,
            email_verified=True,
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(user_id=user.id, role=role, approved_at=datetime.now(UTC)))
        await session.commit()
        await session.refresh(user)
    return user


async def _seed_submitted_attestation() -> UUID:
    """Create one submitted org attestation with full rubric and identity data."""
    owner = await _make_user("attestor", "org-owner")
    requestor = await _make_user("operator", "requestor")
    now = datetime.now(UTC)

    async with async_session_factory() as session:
        org = Organization(
            slug=f"pdf-org-{uuid4().hex[:6]}",
            name="Meridian Trust LLP",
            country="US",
            created_by=owner.id,
        )
        session.add(org)
        await session.flush()
        member = OrgMember(org_id=org.id, user_id=owner.id, role="owner")
        session.add(member)
        session.add(
            OrgAttestorProfile(
                org_id=org.id,
                specializations=["tax"],
                jurisdictions=["US"],
                sectors=["tax"],
                functions=[],
                active=True,
                approved_at=now,
                verification_level=4,
            )
        )
        await session.flush()
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor.id,
            attestor_org_id=org.id,
            reviewing_member_id=member.id,
            status="report_submitted",
            review_type="quality",
            outcome="conditional",
            summary=" ".join(["summary"] * 50),
            scope="Review covered the submitted framework materials and evidence.",
            conditions="Update the outdated regulatory references before reuse.",
            rubric_version=rubrics.RUBRIC_VERSION,
            report_key=f"attestation-reports/{uuid4()}/report.pdf",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            issued_at=now,
            dispute_window_ends_at=now + timedelta(days=14),
            evidence_references={"file_keys": ["evidence/report.pdf"]},
        )
        session.add(attestation)
        await session.flush()

        dimensions = (
            (
                await session.execute(
                    select(AttestationRubricDimension).where(
                        AttestationRubricDimension.review_type == "quality",
                        AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                    )
                )
            )
            .scalars()
            .all()
        )
        for dimension in dimensions:
            session.add(
                AttestationRubricScore(
                    attestation_id=attestation.id,
                    dimension_id=dimension.id,
                    score=5,
                    comment=f"{dimension.label} is fully addressed in the review.",
                )
            )
        session.add(
            AttestationAnnotation(
                attestation_id=attestation.id,
                artifact_id=None,
                location_label="Section 3.2",
                quoted_excerpt="Quoted clause excerpt",
                annotation_type="concern",
                comment="This clause needs updated references.",
            )
        )
        await session.commit()
        return attestation.id


async def _seed_org_submitted_attestation() -> UUID:
    """Create one submitted org-attested attestation with rubric data."""
    owner = await _make_user("attestor", "org-owner")
    requestor = await _make_user("operator", "requestor")
    now = datetime.now(UTC)

    async with async_session_factory() as session:
        org = Organization(
            slug=f"pdf-org-{uuid4().hex[:6]}",
            name="Meridian Trust LLP",
            country="US",
            created_by=owner.id,
        )
        session.add(org)
        await session.flush()
        session.add(OrgMember(org_id=org.id, user_id=owner.id, role="owner"))
        session.add(
            OrgAttestorProfile(
                org_id=org.id,
                specializations=["tax"],
                jurisdictions=["US"],
                sectors=["tax"],
                functions=[],
                active=True,
                approved_at=now,
                verification_level=5,
            )
        )
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor.id,
            attestor_org_id=org.id,
            status="report_submitted",
            review_type="quality",
            outcome="approved",
            summary=" ".join(["summary"] * 50),
            scope="Review covered the submitted framework materials and evidence.",
            rubric_version=rubrics.RUBRIC_VERSION,
            report_key=f"attestation-reports/{uuid4()}/report.pdf",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            issued_at=now,
            dispute_window_ends_at=now + timedelta(days=14),
        )
        session.add(attestation)
        await session.flush()

        dimensions = (
            (
                await session.execute(
                    select(AttestationRubricDimension).where(
                        AttestationRubricDimension.review_type == "quality",
                        AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                    )
                )
            )
            .scalars()
            .all()
        )
        for dimension in dimensions:
            session.add(
                AttestationRubricScore(
                    attestation_id=attestation.id,
                    dimension_id=dimension.id,
                    score=5,
                    comment=f"{dimension.label} is fully addressed in the review.",
                )
            )
        await session.commit()
        return attestation.id


async def test_report_html_contains_workspace_sections(clean_state) -> None:
    """Rendered report HTML includes the eight workspace sections and rubric output."""
    del clean_state
    attestation_id = await _seed_submitted_attestation()

    context = await attestation_pdf._build_report_context(str(attestation_id))
    html = attestation_pdf._build_report_html(context)

    assert "Executive Summary" in html
    assert "Scope of Review" in html
    assert "Methodology" in html
    assert "Dimension Scores" in html
    assert "Key Findings" in html
    assert "Conditions" in html
    assert "Overall Determination" in html
    assert "Attestor Identity" in html
    assert "Completeness" in html
    assert "5.00" in html


async def test_report_html_shows_org_identity_without_member(clean_state) -> None:
    """An org-attested report renders org identity and no member email."""
    del clean_state
    attestation_id = await _seed_org_submitted_attestation()

    context = await attestation_pdf._build_report_context(str(attestation_id))
    html = attestation_pdf._build_report_html(context)

    assert context["attestor_name"] == "Meridian Trust LLP"
    assert context["attestor_email"] is None
    assert context["verification_level"] == 5
    assert context["credentials"] == []
    assert "Meridian Trust LLP" in html
    # No reviewing-member email angle-bracket line is rendered for an org.
    assert "&lt;" not in html
