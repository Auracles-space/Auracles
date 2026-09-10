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
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestorTrial,
    AttestorTrialAnswerKey,
    AttestorTrialRubricScore,
)
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations import attestor_application_service as app_svc
from app.modules.organizations import attestor_trial_service as svc
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgMember,
)
from app.modules.organizations.schemas import (
    TrialDecideRequest,
    TrialScoreInput,
    TrialSubmitRequest,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio

BACKEND_DIR = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class SeededTrialContext:
    """Seeded org/application/trial state for nominee trial-service tests."""

    application_id: UUID
    org_id: UUID
    trial_id: UUID
    admin_id: UUID
    nominee: OrgMember
    other_member: OrgMember
    dimension_ids: tuple[UUID, ...]

    def full_submission(self) -> TrialSubmitRequest:
        """Return one valid score per trial rubric dimension."""
        return TrialSubmitRequest(
            scores=[
                TrialScoreInput(
                    dimension_id=dimension_id,
                    score=4,
                    comment="Strong alignment.",
                )
                for dimension_id in self.dimension_ids
            ]
        )


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database is upgraded to the current head."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
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
                await session.execute(delete(AuditLog))
                await session.execute(delete(AttestorTrialRubricScore))
                await session.execute(delete(AttestorTrialAnswerKey))
                await session.execute(delete(AttestorTrial))
                await session.execute(delete(Artifact))
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
    admin_user = await _create_user(prefix="trial-admin")

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

            dimensions = (
                await session.scalars(
                    select(AttestationRubricDimension)
                    .where(
                        AttestationRubricDimension.review_type == "quality",
                        AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                    )
                    .order_by(AttestationRubricDimension.display_order.asc())
                )
            ).all()
            assert len(dimensions) >= 2

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
                Artifact(
                    framework_id=framework.id,
                    name="fixture.pdf",
                    file_key=f"frameworks/{framework.id}/fixture.pdf",
                    file_size=2048,
                    mime_type="application/pdf",
                    scan_status="clean",
                    processing_status="processed",
                )
            )
            for dimension in dimensions:
                session.add(
                    AttestorTrialAnswerKey(
                        framework_id=framework.id,
                        dimension_id=dimension.id,
                        expected_score=4,
                        tolerance=0,
                    )
                )
            await session.flush()

            trial = AttestorTrial(
                id=uuid4(),
                org_application_id=application.id,
                org_id=org.id,
                member_id=owner_member.id,
                seeded_framework_id=framework.id,
                status="assigned",
                attempt=1,
            )
            session.add(trial)

            await session.refresh(owner_member)
            await session.refresh(other_member)
            return SeededTrialContext(
                application_id=application.id,
                org_id=org.id,
                trial_id=trial.id,
                admin_id=admin_user.id,
                nominee=owner_member,
                other_member=other_member,
                dimension_ids=tuple(dimension.id for dimension in dimensions),
            )


@pytest.fixture
async def seeded_trial(clean_state: None) -> SeededTrialContext:
    """Seed one active trial and return both nominee and non-nominee members."""
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


async def test_submit_computes_score_and_flips_to_submitted(
    seeded_trial: SeededTrialContext,
) -> None:
    """A complete submission stores scores and advances the trial to submitted."""
    async with async_session_factory() as session:
        response = await svc.submit_nominee_trial(
            session,
            org_id=seeded_trial.org_id,
            member=seeded_trial.nominee,
            payload=seeded_trial.full_submission(),
        )

    assert response.status == "submitted"

    async with async_session_factory() as session:
        trial = await session.get(AttestorTrial, seeded_trial.trial_id)
        stored_scores = (
            await session.scalars(
                select(AttestorTrialRubricScore).where(
                    AttestorTrialRubricScore.trial_id == seeded_trial.trial_id
                )
            )
        ).all()

    assert trial is not None
    assert trial.status == "submitted"
    assert trial.submitted_at is not None
    assert trial.score_pct == Decimal("100.00")
    assert trial.auto_result == "pass"
    assert len(stored_scores) == len(seeded_trial.dimension_ids)


async def test_submit_missing_dimension_422(
    seeded_trial: SeededTrialContext,
) -> None:
    """A submission missing any rubric dimension is rejected with 422."""
    payload = seeded_trial.full_submission()
    payload.scores.pop()

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.submit_nominee_trial(
                session,
                org_id=seeded_trial.org_id,
                member=seeded_trial.nominee,
                payload=payload,
            )

    assert exc.value.status_code == 422


async def test_resubmit_after_submitted_409(
    seeded_trial: SeededTrialContext,
) -> None:
    """Submitting again after the first submit is rejected with 409."""
    async with async_session_factory() as session:
        await svc.submit_nominee_trial(
            session,
            org_id=seeded_trial.org_id,
            member=seeded_trial.nominee,
            payload=seeded_trial.full_submission(),
        )

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.submit_nominee_trial(
                session,
                org_id=seeded_trial.org_id,
                member=seeded_trial.nominee,
                payload=seeded_trial.full_submission(),
            )

    assert exc.value.status_code == 409


async def test_load_nominee_trial_shows_terminal_outcome(
    seeded_trial: SeededTrialContext,
) -> None:
    """The nominee can still load the latest decided trial with feedback."""
    async with async_session_factory() as session:
        async with session.begin():
            trial = await session.get(AttestorTrial, seeded_trial.trial_id)
            assert trial is not None
            trial.status = "passed"
            trial.feedback = "Excellent evidence traceability."

    async with async_session_factory() as session:
        response = await svc.load_nominee_trial(
            session,
            org_id=seeded_trial.org_id,
            member=seeded_trial.nominee,
        )

    assert response.status == "passed"
    assert response.feedback == "Excellent evidence traceability."


async def test_submit_rechecks_locked_trial_status_before_writing(
    seeded_trial: SeededTrialContext,
) -> None:
    """A stale assigned read that loses the race returns 409, not a DB error."""
    payload = seeded_trial.full_submission()

    async with async_session_factory() as session:
        original_rollback = session.rollback

        async def rollback_and_submit() -> None:
            """Simulate another submit winning between the stale read and lock."""
            await original_rollback()
            async with async_session_factory() as competing_session:
                async with competing_session.begin():
                    competing_trial = await competing_session.get(
                        AttestorTrial,
                        seeded_trial.trial_id,
                        with_for_update=True,
                    )
                    assert competing_trial is not None
                    competing_trial.status = "submitted"
                    for score in payload.scores:
                        competing_session.add(
                            AttestorTrialRubricScore(
                                trial_id=seeded_trial.trial_id,
                                dimension_id=score.dimension_id,
                                score=score.score,
                                comment=score.comment,
                            )
                        )

        session.rollback = rollback_and_submit  # type: ignore[method-assign]

        with pytest.raises(HTTPException) as exc:
            await svc.submit_nominee_trial(
                session,
                org_id=seeded_trial.org_id,
                member=seeded_trial.nominee,
                payload=payload,
            )

    assert exc.value.status_code == 409


async def test_admin_decide_pass_flips_gate(
    seeded_trial: SeededTrialContext,
) -> None:
    """Admin deciding pass stamps the trial and opens the application gate."""
    async with async_session_factory() as session:
        await svc.submit_nominee_trial(
            session,
            org_id=seeded_trial.org_id,
            member=seeded_trial.nominee,
            payload=seeded_trial.full_submission(),
        )

    async with async_session_factory() as session:
        trial = await svc.admin_decide_trial(
            session,
            application_id=seeded_trial.application_id,
            admin_id=seeded_trial.admin_id,
            payload=TrialDecideRequest(
                result="pass",
                feedback="Solid calibration.",
            ),
        )
        gate_passed = await app_svc._trial_passed(session, seeded_trial.application_id)

    assert trial.status == "passed"
    assert trial.decided_by == seeded_trial.admin_id
    assert gate_passed is True


async def test_admin_decide_requires_submitted(
    seeded_trial: SeededTrialContext,
) -> None:
    """Deciding a trial that is still assigned is rejected with 409."""
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await svc.admin_decide_trial(
                session,
                application_id=seeded_trial.application_id,
                admin_id=seeded_trial.admin_id,
                payload=TrialDecideRequest(result="pass"),
            )

    assert exc.value.status_code == 409
