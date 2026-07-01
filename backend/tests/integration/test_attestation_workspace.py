"""Integration tests for the Module 4 review-workspace migration and CRUD."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, func, select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.core.database import async_session_factory, engine
from app.modules.attestation import rubrics
from app.modules.attestation import workspace_service
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationArtifactAccess,
    AttestationClarification,
    AttestationDispute,
    AttestationOffer,
    AttestationRubricDimension,
    AttestationRubricMethodology,
    AttestationRubricScore,
    AttestationUploadSession,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear attestation workspace rows in FK-safe order."""
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
    """Reset workspace state before and after each integration test."""
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
    """Provide an async session for workspace service tests."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _make_user(role: str, prefix: str) -> User:
    """Create one verified user with an approved role row."""
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


def _auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for one test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def _make_attestor(prefix: str) -> User:
    """Create one approved attestor with a valid current CoI."""
    user = await _make_user("attestor", prefix)
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        session.add(
            AttestorProfile(
                user_id=user.id,
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
        await session.commit()
    return user


async def _accepted_attestation() -> tuple[User, Attestation]:
    """Create one accepted attestation assigned to an approved attestor."""
    attestor = await _make_attestor("attestor")
    requestor = await _make_user("operator", "requestor")
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor.id,
            attestor_id=attestor.id,
            status="accepted",
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            content_ack_at=datetime.now(UTC),
            content_ack_version="v1",
            completion_due_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(attestation)
        await session.commit()
        await session.refresh(attestation)
    return attestor, attestation


async def _in_review_attestation(
    db_session,
) -> tuple[User, Attestation]:
    """Create one attestation already transitioned into the workspace state."""
    attestor, attestation = await _accepted_attestation()
    started = await workspace_service.start_review(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
    )
    return attestor, started


async def test_rubric_dimensions_seeded(migrated_database) -> None:
    """All review-type rubric dimensions and methodology rows are seeded."""
    del migrated_database
    await engine.dispose()

    expected_dimensions = sum(
        len(dimensions) for dimensions in rubrics.RUBRICS.values()
    )
    async with async_session_factory() as session:
        dimension_count = await session.scalar(
            select(func.count()).select_from(AttestationRubricDimension)
        )
        methodology_count = await session.scalar(
            select(func.count()).select_from(AttestationRubricMethodology)
        )

    await engine.dispose()

    assert dimension_count == expected_dimensions
    assert methodology_count == len(rubrics.METHODOLOGY)


async def test_start_review_transitions_accepted_to_in_review(db_session) -> None:
    """The assigned Attestor opening the workspace moves accepted to in_review."""
    attestor, attestation = await _accepted_attestation()

    result = await workspace_service.start_review(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
    )

    assert result.status == "in_review"
    assert result.review_started_at is not None


async def test_start_review_is_idempotent(db_session) -> None:
    """Calling start_review twice leaves the assignment in in_review."""
    attestor, attestation = await _accepted_attestation()

    await workspace_service.start_review(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
    )
    again = await workspace_service.start_review(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
    )

    assert again.status == "in_review"


async def test_start_review_404_for_non_assigned(db_session) -> None:
    """A non-assigned Attestor cannot discover the workspace by ID."""
    _assigned, attestation = await _accepted_attestation()
    intruder = await _make_attestor("intruder")

    with pytest.raises(HTTPException) as exc:
        await workspace_service.start_review(
            db_session,
            attestor=intruder,
            attestation_id=attestation.id,
        )

    assert exc.value.status_code == 404


async def test_upsert_rubric_score_creates_then_updates(db_session) -> None:
    """Scoring one dimension upserts a single row per attestation and dimension."""
    attestor, attestation = await _in_review_attestation(db_session)

    first = await workspace_service.upsert_rubric_score(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        dimension_key="completeness",
        score=4,
        comment="Thorough.",
    )
    assert first.score == 4

    second = await workspace_service.upsert_rubric_score(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        dimension_key="completeness",
        score=5,
        comment="Revised up.",
    )
    assert second.id == first.id
    assert second.score == 5


async def test_upsert_rubric_score_rejects_foreign_dimension(db_session) -> None:
    """A dimension key outside the attestation review type is rejected."""
    attestor, attestation = await _in_review_attestation(db_session)

    with pytest.raises(HTTPException) as exc:
        await workspace_service.upsert_rubric_score(
            db_session,
            attestor=attestor,
            attestation_id=attestation.id,
            dimension_key="chain_of_custody",
            score=3,
            comment="Not valid for quality reviews.",
        )

    assert exc.value.status_code == 422


async def test_create_and_delete_annotation(db_session) -> None:
    """The assigned Attestor can add and remove a free-anchor annotation."""
    attestor, attestation = await _in_review_attestation(db_session)

    annotation = await workspace_service.create_annotation(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        artifact_id=None,
        location_label="Section 3.2",
        quoted_excerpt="the clause text",
        annotation_type="concern",
        comment="Ambiguous scope.",
    )
    assert annotation.annotation_type == "concern"

    await workspace_service.delete_annotation(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
        annotation_id=annotation.id,
    )
    remaining = await workspace_service.list_annotations(
        db_session,
        attestor=attestor,
        attestation_id=attestation.id,
    )

    assert remaining == []


async def test_create_annotation_rejects_bad_type(db_session) -> None:
    """Unknown annotation types are rejected with 422."""
    attestor, attestation = await _in_review_attestation(db_session)

    with pytest.raises(HTTPException) as exc:
        await workspace_service.create_annotation(
            db_session,
            attestor=attestor,
            attestation_id=attestation.id,
            artifact_id=None,
            location_label="x",
            quoted_excerpt=None,
            annotation_type="applause",
            comment="c",
        )

    assert exc.value.status_code == 422


async def test_start_review_endpoint_flips_status(
    client: AsyncClient,
    clean_state,
) -> None:
    """POST start-review returns 200 and reports the in_review status."""
    del clean_state
    attestor, attestation = await _accepted_attestation()

    response = await client.post(
        f"/v1/attestations/{attestation.id}/start-review",
        headers=_auth_headers(attestor.id, ["attestor"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_review"


async def test_upsert_rubric_score_endpoint_returns_score(
    client: AsyncClient,
    clean_state,
) -> None:
    """PUT rubric persists the score/comment for the assigned Attestor."""
    del clean_state
    attestor, attestation = await _accepted_attestation()
    start = await client.post(
        f"/v1/attestations/{attestation.id}/start-review",
        headers=_auth_headers(attestor.id, ["attestor"]),
    )
    assert start.status_code == 200

    response = await client.put(
        f"/v1/attestations/{attestation.id}/rubric/completeness",
        headers=_auth_headers(attestor.id, ["attestor"]),
        json={"score": 4, "comment": "Complete enough."},
    )

    assert response.status_code == 200
    assert response.json()["score"] == 4
    assert response.json()["comment"] == "Complete enough."


async def test_workspace_endpoints_hide_non_assigned_attestations(
    client: AsyncClient,
    clean_state,
) -> None:
    """A non-assigned Attestor receives 404 from workspace endpoints."""
    del clean_state
    _attestor, attestation = await _accepted_attestation()
    intruder = await _make_attestor("intruder-endpoint")

    response = await client.post(
        f"/v1/attestations/{attestation.id}/start-review",
        headers=_auth_headers(intruder.id, ["attestor"]),
    )

    assert response.status_code == 404


async def test_workspace_endpoints_require_authentication(
    client: AsyncClient,
    clean_state,
) -> None:
    """Unauthenticated workspace requests are rejected before service logic."""
    del clean_state
    _attestor, attestation = await _accepted_attestation()

    response = await client.post(f"/v1/attestations/{attestation.id}/start-review")

    assert response.status_code == 401


async def test_annotation_endpoints_crud_round_trip(
    client: AsyncClient,
    clean_state,
) -> None:
    """Annotation POST, GET, PATCH, and DELETE operate on the workspace."""
    del clean_state
    attestor, attestation = await _accepted_attestation()
    headers = _auth_headers(attestor.id, ["attestor"])
    start = await client.post(
        f"/v1/attestations/{attestation.id}/start-review",
        headers=headers,
    )
    assert start.status_code == 200

    created = await client.post(
        f"/v1/attestations/{attestation.id}/annotations",
        headers=headers,
        json={
            "artifact_id": None,
            "location_label": "Section 4",
            "quoted_excerpt": "quoted text",
            "annotation_type": "concern",
            "comment": "Needs clarification.",
        },
    )
    assert created.status_code == 200
    annotation_id = created.json()["id"]

    listed = await client.get(
        f"/v1/attestations/{attestation.id}/annotations",
        headers=headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = await client.patch(
        f"/v1/attestations/{attestation.id}/annotations/{annotation_id}",
        headers=headers,
        json={
            "artifact_id": None,
            "location_label": "Section 4.1",
            "quoted_excerpt": "updated quote",
            "annotation_type": "revision_recommended",
            "comment": "Revise this clause.",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["annotation_type"] == "revision_recommended"

    deleted = await client.delete(
        f"/v1/attestations/{attestation.id}/annotations/{annotation_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
