"""Integration tests for gated attestation report submission."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import freezegun
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.attestation import notifications, rubrics
from app.modules.attestation import report as report_service
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


class FakeRenderTask:
    """Capture queued report render requests without running Celery."""

    calls: list[str] = []

    @classmethod
    def delay(cls, attestation_id: str) -> None:
        """Record the attestation id passed to the render task."""
        cls.calls.append(attestation_id)


class FakeNotificationTask:
    """Capture dispatched attestation notifications in memory."""

    calls: list[dict[str, Any]] = []

    @classmethod
    def delay(cls, **kwargs: Any) -> None:
        """Record one queued notification payload."""
        cls.calls.append(kwargs)


async def _reset_state() -> None:
    """Clear attestation submission test rows in foreign-key-safe order."""
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
    """Ensure the integration database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Reset submission state before and after each integration test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    FakeRenderTask.calls = []
    FakeNotificationTask.calls = []
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


def _auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for one authenticated test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


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


async def _seed_in_review_attestation_with_rubric(
    *,
    missing_dimension_key: str | None = None,
    completion_due_at: datetime | None = None,
    status: str = "in_review",
    revision_count: int = 0,
) -> tuple[UUID, UUID]:
    """Create one in-review quality attestation with rubric rows for submission."""
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
                verification_level=4,
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
            status=status,
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            review_started_at=now,
            completion_due_at=completion_due_at or (now + timedelta(days=7)),
            revision_count=revision_count,
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
            if dimension.key == missing_dimension_key:
                continue
            session.add(
                AttestationRubricScore(
                    attestation_id=attestation.id,
                    dimension_id=dimension.id,
                    score=5,
                    comment=f"{dimension.label} is fully addressed for approval.",
                )
            )
        await session.commit()
        return attestor.id, attestation.id


async def _add_annotation(attestation_id: UUID) -> None:
    """Attach one annotation to the seeded attestation."""
    async with async_session_factory() as session:
        session.add(
            AttestationAnnotation(
                attestation_id=attestation_id,
                artifact_id=None,
                location_label="Section 3.2",
                quoted_excerpt="Quoted excerpt",
                annotation_type="concern",
                comment="Needs revision.",
            )
        )
        await session.commit()


async def test_submit_blocked_by_incomplete_rubric_returns_422(
    client: AsyncClient,
    clean_state,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting with an unscored dimension returns itemized 422 failures."""
    del clean_state
    attestor_id, attestation_id = await _seed_in_review_attestation_with_rubric(
        missing_dimension_key="clarity"
    )
    monkeypatch.setattr(report_service, "render_attestation_report_pdf", FakeRenderTask)
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask,
    )

    response = await client.post(
        f"/v1/attestations/{attestation_id}/report",
        headers=_auth_headers(attestor_id, ["attestor"]),
        json={
            "outcome": "approved",
            "summary": " ".join(["summary"] * 200),
            "scope": "Credential, process, and sample evidence review.",
            "evidence_references": {},
        },
    )

    assert response.status_code == 422
    assert any("dimension" in item.lower() for item in response.json()["detail"])


async def test_submit_past_deadline_within_grace_stamps_late(
    client: AsyncClient,
    clean_state,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting after completion_due_at marks late and increments the profile."""
    del clean_state
    due_at = datetime.now(UTC) - timedelta(hours=1)
    attestor_id, attestation_id = await _seed_in_review_attestation_with_rubric(
        completion_due_at=due_at
    )
    monkeypatch.setattr(report_service, "render_attestation_report_pdf", FakeRenderTask)
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask,
    )

    response = await client.post(
        f"/v1/attestations/{attestation_id}/report",
        headers=_auth_headers(attestor_id, ["attestor"]),
        json={
            "outcome": "approved",
            "summary": " ".join(["summary"] * 200),
            "scope": "Credential, process, and sample evidence review.",
            "conditions": None,
            "evidence_references": {},
        },
    )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        profile = await session.scalar(
            select(AttestorProfile).where(AttestorProfile.user_id == attestor_id)
        )
        audits = (
            await session.execute(
                select(AuditLog.action).where(
                    AuditLog.target_type == "attestation",
                    AuditLog.target_id == attestation_id,
                )
            )
        ).scalars().all()

    assert response.status_code == 200
    assert response.json()["status"] == "report_submitted"
    assert attestation is not None
    assert attestation.submitted_late is True
    assert attestation.rubric_version == rubrics.RUBRIC_VERSION
    assert profile is not None
    assert profile.late_submission_count == 1
    assert "attestation_late_submission" in audits
    assert FakeRenderTask.calls == [str(attestation_id)]


@freezegun.freeze_time("2026-07-06T12:00:00Z")
async def test_submit_sets_business_day_dispute_window(
    client: AsyncClient,
    clean_state,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report submit sets dispute_window_ends_at 5 business days out.

    Enforces Module 5 spec section 4.2 (weekend-skipping window).
    """
    del clean_state
    attestor_id, attestation_id = await _seed_in_review_attestation_with_rubric()
    monkeypatch.setattr(report_service, "render_attestation_report_pdf", FakeRenderTask)
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask,
    )

    response = await client.post(
        f"/v1/attestations/{attestation_id}/report",
        headers=_auth_headers(attestor_id, ["attestor"]),
        json={
            "outcome": "approved",
            "summary": " ".join(["summary"] * 200),
            "scope": "Credential, process, and sample evidence review.",
            "conditions": None,
            "evidence_references": {},
        },
    )

    assert response.status_code == 200

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)

    # 5 business days from Mon 2026-07-06 == Mon 2026-07-13.
    expected_window = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    assert attestation.dispute_window_ends_at == expected_window


@freezegun.freeze_time("2026-07-06T12:00:00Z")
async def test_resubmit_from_revision_requested_reopens_window(
    client: AsyncClient,
    clean_state,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revised report re-enters report_submitted with a fresh dispute window.

    Enforces Module 5 spec section 4.6 (revise-resubmit loop): an admin who
    upholds a dispute as ``upheld_revise`` reopens the attestation, and the
    attestor may resubmit through the same report endpoint.
    """
    del clean_state
    attestor_id, attestation_id = await _seed_in_review_attestation_with_rubric(
        status="revision_requested",
        revision_count=1,
    )
    monkeypatch.setattr(report_service, "render_attestation_report_pdf", FakeRenderTask)
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask,
    )

    response = await client.post(
        f"/v1/attestations/{attestation_id}/report",
        headers=_auth_headers(attestor_id, ["attestor"]),
        json={
            "outcome": "approved",
            "summary": " ".join(["summary"] * 200),
            "scope": "Credential, process, and sample evidence review.",
            "conditions": None,
            "evidence_references": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "report_submitted"

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)

    assert attestation is not None
    assert attestation.status == "report_submitted"
    # 5 business days from Mon 2026-07-06 == Mon 2026-07-13.
    expected_window = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    assert attestation.dispute_window_ends_at == expected_window
