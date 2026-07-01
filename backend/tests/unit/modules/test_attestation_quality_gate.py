"""Unit tests for the attestation submission quality gate."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import quality_gate, rubrics
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
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear quality-gate test rows in foreign-key-safe order."""
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
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is upgraded to the latest alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Reset quality-gate state before and after each test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


@pytest.fixture
async def db_session(clean_state) -> AsyncIterator:
    """Provide an async session for quality-gate service tests."""
    del clean_state
    async with async_session_factory() as session:
        yield session


def _long_text(words: int) -> str:
    """Return deterministic prose with the requested word count."""
    return " ".join(f"word{index}" for index in range(words))


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


async def _in_review_with_full_quality_rubric(db_session) -> Attestation:
    """Create one in-review quality attestation with every dimension scored."""
    attestor = await _make_user("attestor", "attestor")
    requestor = await _make_user("operator", "requestor")
    now = datetime.now(UTC)

    async with async_session_factory() as session:
        session.add(
            AttestorProfile(
                user_id=attestor.id,
                specializations=["tax"],
                jurisdictions=["US"],
                sectors=["tax"],
                framework_categories=[],
                active=True,
                approved_at=now,
                coi_declarations=[],
                coi_signed_at=now,
                coi_expires_at=now + timedelta(days=365),
            )
        )
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor.id,
            attestor_id=attestor.id,
            status="in_review",
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            completion_due_at=now + timedelta(days=7),
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
                    comment=f"{dimension.label} is fully addressed.",
                )
            )
        await session.commit()
        await session.refresh(attestation)

    refreshed = await db_session.get(Attestation, attestation.id)
    assert refreshed is not None
    return refreshed


async def _in_review_missing_one_score(db_session) -> Attestation:
    """Create one in-review quality attestation missing a single rubric score."""
    attestation = await _in_review_with_full_quality_rubric(db_session)
    dimension = await db_session.scalar(
        select(AttestationRubricDimension).where(
            AttestationRubricDimension.review_type == "quality",
            AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
            AttestationRubricDimension.key == "clarity",
        )
    )
    assert dimension is not None
    score = await db_session.scalar(
        select(AttestationRubricScore).where(
            AttestationRubricScore.attestation_id == attestation.id,
            AttestationRubricScore.dimension_id == dimension.id,
        )
    )
    assert score is not None
    await db_session.delete(score)
    await db_session.commit()
    refreshed = await db_session.get(Attestation, attestation.id)
    assert refreshed is not None
    return refreshed


async def _add_annotation(db_session, attestation: Attestation) -> None:
    """Attach one annotation to the attestation for non-approved outcomes."""
    db_session.add(
        AttestationAnnotation(
            attestation_id=attestation.id,
            artifact_id=None,
            location_label="Section 3.2",
            quoted_excerpt="Quoted excerpt",
            annotation_type="concern",
            comment="Needs revision.",
        )
    )
    await db_session.commit()


async def _in_review_with_open_clarification(db_session) -> Attestation:
    """Create one in-review attestation with an outstanding clarification."""
    attestation = await _in_review_with_full_quality_rubric(db_session)
    db_session.add(
        AttestationClarification(
            attestation_id=attestation.id,
            question="Please confirm the scope.",
            response_due_at=datetime.now(UTC) + timedelta(hours=48),
            status="open",
        )
    )
    await db_session.commit()
    refreshed = await db_session.get(Attestation, attestation.id)
    assert refreshed is not None
    return refreshed


async def test_gate_passes_complete_approved(db_session) -> None:
    """A fully scored, sufficiently long approved submission passes."""
    attestation = await _in_review_with_full_quality_rubric(db_session)

    failures = await quality_gate.evaluate_quality_gate(
        db_session,
        attestation=attestation,
        summary=_long_text(200),
        scope="In scope: all clauses.",
        conditions=None,
        outcome="approved",
    )

    assert failures == []


async def test_gate_flags_incomplete_rubric(db_session) -> None:
    """A missing dimension score is returned as a gate failure."""
    attestation = await _in_review_missing_one_score(db_session)

    failures = await quality_gate.evaluate_quality_gate(
        db_session,
        attestation=attestation,
        summary=_long_text(200),
        scope="In scope: all clauses.",
        conditions=None,
        outcome="approved",
    )

    assert any("dimension" in failure.lower() for failure in failures)


async def test_gate_requires_conditions_when_conditional(db_session) -> None:
    """A conditional outcome without conditions text must fail."""
    attestation = await _in_review_with_full_quality_rubric(db_session)
    await _add_annotation(db_session, attestation)

    failures = await quality_gate.evaluate_quality_gate(
        db_session,
        attestation=attestation,
        summary=_long_text(200),
        scope="In scope: all clauses.",
        conditions=None,
        outcome="conditional",
    )

    assert any("condition" in failure.lower() for failure in failures)


async def test_gate_rejects_conditions_for_non_conditional(db_session) -> None:
    """Conditions text is only allowed for conditional determinations."""
    attestation = await _in_review_with_full_quality_rubric(db_session)

    failures = await quality_gate.evaluate_quality_gate(
        db_session,
        attestation=attestation,
        summary=_long_text(200),
        scope="In scope: all clauses.",
        conditions="Must update the citations.",
        outcome="approved",
    )

    assert any("condition" in failure.lower() for failure in failures)


async def test_gate_requires_annotation_when_rejected(db_session) -> None:
    """A rejected outcome without any annotation must fail."""
    attestation = await _in_review_with_full_quality_rubric(db_session)

    failures = await quality_gate.evaluate_quality_gate(
        db_session,
        attestation=attestation,
        summary=_long_text(200),
        scope="In scope: all clauses.",
        conditions=None,
        outcome="rejected",
    )

    assert any("annotation" in failure.lower() for failure in failures)


async def test_gate_blocks_contact_info(db_session) -> None:
    """Direct contact details in report text are prohibited."""
    attestation = await _in_review_with_full_quality_rubric(db_session)

    failures = await quality_gate.evaluate_quality_gate(
        db_session,
        attestation=attestation,
        summary=f"{_long_text(200)} reach me at a@b.com",
        scope="In scope: all clauses.",
        conditions=None,
        outcome="approved",
    )

    assert any("contact" in failure.lower() for failure in failures)


async def test_gate_blocks_open_clarification(db_session) -> None:
    """An open clarification blocks submission until it is resolved."""
    attestation = await _in_review_with_open_clarification(db_session)

    failures = await quality_gate.evaluate_quality_gate(
        db_session,
        attestation=attestation,
        summary=_long_text(200),
        scope="In scope: all clauses.",
        conditions=None,
        outcome="approved",
    )

    assert any("clarification" in failure.lower() for failure in failures)


async def test_gate_aggregates_multiple_failures(db_session) -> None:
    """The gate returns every failure instead of stopping at the first one."""
    attestation = await _in_review_missing_one_score(db_session)

    failures = await quality_gate.evaluate_quality_gate(
        db_session,
        attestation=attestation,
        summary="reach me at a@b.com",
        scope="In scope: all clauses.",
        conditions=None,
        outcome="rejected",
    )

    assert len(failures) >= 3
