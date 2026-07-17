"""Integration tests for org-staffed attestation workspace + delivery guards.

The reviewing member staffed on an org attestation gets write access to the
review surfaces (start review, rubric, annotations, report); org owners/admins
get read-only oversight; other org members and strangers are refused. Enforces
the guard re-point of
docs/superpowers/specs/2026-07-04-org-attestor-design.md (workspace + delivery).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.attestation import report as report_service
from app.modules.attestation import rubrics, workspace_service
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationClarification,
    AttestationOffer,
    AttestationRubricDimension,
    AttestationRubricScore,
)
from app.modules.attestation.schemas import AttestationReportSubmitRequest
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio

NDA_VERSION = get_settings().org_member_nda_version


async def _reset_state() -> None:
    """Clear workspace + org rows in FK-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationClarification))
            await session.execute(delete(AttestationAnnotation))
            await session.execute(delete(AttestationRubricScore))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
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


def _auth(user_id: UUID) -> dict[str, str]:
    """Build bearer auth headers for one user."""
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, roles=[])}"}


async def _new_user(prefix: str) -> UUID:
    """Create a verified user; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def _load_user(user_id: UUID) -> User:
    """Load a user in a throwaway session (detached, safe across rollbacks)."""
    async with async_session_factory() as session:
        return await session.get(User, user_id)


async def _attestor_org() -> tuple[UUID, UUID]:
    """Create an active attestor org with a valid CoI. Return (org_id, owner_id)."""
    owner_id = await _new_user("owner")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:6]}",
                name="Attestor Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=owner_id, role="owner")
            session.add(member)
            await session.flush()
            session.add(
                OrgCapability(org_id=org.id, capability="attestor", status="active")
            )
            session.add(OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION))
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["tax"],
                    jurisdictions=["US"],
                    sectors=["tax"],
                    functions=[],
                    active=True,
                    approved_at=now,
                    coi_signed_at=now,
                    coi_expires_at=now + timedelta(days=365),
                )
            )
            return org.id, owner_id


async def _add_member(org_id: UUID, *, role: str = "member") -> tuple[UUID, UUID]:
    """Add a member to an org. Return (member_id, user_id)."""
    user_id = await _new_user(role)
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            session.add(OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION))
            return member.id, user_id


async def _staffed_attestation(
    org_id: UUID,
    reviewing_member_id: UUID,
    *,
    status: str = "accepted",
    completion_due_at: datetime | None = None,
    seed_rubric: bool = False,
    content_acked: bool = True,
) -> Attestation:
    """Create an org attestation staffed on one reviewing member."""
    requestor_id = await _new_user("requestor")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor_id,
            attestor_org_id=org_id,
            reviewing_member_id=reviewing_member_id,
            status=status,
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            content_ack_at=now if content_acked else None,
            content_ack_version="v1" if content_acked else None,
            review_started_at=now if status == "in_review" else None,
            completion_due_at=completion_due_at or (now + timedelta(days=7)),
        )
        session.add(attestation)
        await session.flush()
        if seed_rubric:
            dimensions = (
                (
                    await session.execute(
                        select(AttestationRubricDimension).where(
                            AttestationRubricDimension.review_type == "quality",
                            AttestationRubricDimension.version
                            == rubrics.RUBRIC_VERSION,
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
                        comment=f"{dimension.label} is fully addressed for approval.",
                    )
                )
        await session.commit()
        await session.refresh(attestation)
    return attestation


async def test_reviewing_member_starts_review(db_session) -> None:
    """The staffed reviewing member opens the workspace (accepted -> in_review)."""
    org_id, _owner = await _attestor_org()
    member_id, member_user = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, member_id)
    reviewer = await _load_user(member_user)

    result = await workspace_service.start_review(
        db_session,
        attestor=reviewer,
        attestation_id=attestation.id,
    )

    assert result.status == "in_review"
    assert result.review_started_at is not None


async def test_reviewing_member_can_score_and_annotate(db_session) -> None:
    """The reviewing member writes rubric scores and annotations."""
    org_id, _owner = await _attestor_org()
    member_id, member_user = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, member_id)
    reviewer = await _load_user(member_user)
    await workspace_service.start_review(
        db_session, attestor=reviewer, attestation_id=attestation.id
    )

    score = await workspace_service.upsert_rubric_score(
        db_session,
        attestor=reviewer,
        attestation_id=attestation.id,
        dimension_key="completeness",
        score=4,
        comment="Thorough.",
    )
    assert score.score == 4

    annotation = await workspace_service.create_annotation(
        db_session,
        attestor=reviewer,
        attestation_id=attestation.id,
        artifact_id=None,
        location_label="Section 3",
        quoted_excerpt=None,
        annotation_type="concern",
        comment="Scope unclear.",
    )
    assert annotation.annotation_type == "concern"


async def test_org_manager_read_only_cannot_write(
    client: AsyncClient, clean_state
) -> None:
    """An org owner/admin may not write review surfaces (read-only oversight)."""
    del clean_state
    org_id, owner_user = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, member_id)

    response = await client.post(
        f"/v1/attestations/{attestation.id}/start-review",
        headers=_auth(owner_user),
    )
    assert response.status_code == 403


async def test_unrelated_org_member_forbidden(
    client: AsyncClient, clean_state
) -> None:
    """A non-reviewing member of the attestor org is refused (403)."""
    del clean_state
    org_id, _owner = await _attestor_org()
    reviewing_member, _ = await _add_member(org_id)
    _other_member, other_user = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, reviewing_member)

    response = await client.post(
        f"/v1/attestations/{attestation.id}/start-review",
        headers=_auth(other_user),
    )
    assert response.status_code == 403


async def test_stranger_hidden_404(client: AsyncClient, clean_state) -> None:
    """A user with no relationship to the attestor org sees 404 (hidden)."""
    del clean_state
    org_id, _owner = await _attestor_org()
    reviewing_member, _ = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, reviewing_member)
    stranger = await _new_user("stranger")

    response = await client.post(
        f"/v1/attestations/{attestation.id}/start-review",
        headers=_auth(stranger),
    )
    assert response.status_code == 404


async def test_reviewing_member_records_content_ack(
    client: AsyncClient, clean_state
) -> None:
    """The staffed member records the content-use ack, unlocking start-review."""
    del clean_state
    org_id, _owner = await _attestor_org()
    member_id, member_user = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, member_id, content_acked=False)

    acked = await client.post(
        f"/v1/attestations/{attestation.id}/content-ack",
        json={"content_ack": True, "ack_version": "v1"},
        headers=_auth(member_user),
    )
    assert acked.status_code == 200

    started = await client.post(
        f"/v1/attestations/{attestation.id}/start-review",
        headers=_auth(member_user),
    )
    assert started.status_code == 200
    assert started.json()["status"] == "in_review"


async def test_content_ack_requires_affirmation(
    client: AsyncClient, clean_state
) -> None:
    """A non-affirmed acknowledgment is rejected (422)."""
    del clean_state
    org_id, _owner = await _attestor_org()
    member_id, member_user = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, member_id, content_acked=False)

    response = await client.post(
        f"/v1/attestations/{attestation.id}/content-ack",
        json={"content_ack": False, "ack_version": "v1"},
        headers=_auth(member_user),
    )
    assert response.status_code == 422


async def test_content_ack_denied_to_org_manager(
    client: AsyncClient, clean_state
) -> None:
    """An org owner/admin cannot record the member's content ack (403)."""
    del clean_state
    org_id, owner_user = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, member_id, content_acked=False)

    response = await client.post(
        f"/v1/attestations/{attestation.id}/content-ack",
        json={"content_ack": True, "ack_version": "v1"},
        headers=_auth(owner_user),
    )
    assert response.status_code == 403


async def test_content_ack_hidden_from_stranger(
    client: AsyncClient, clean_state
) -> None:
    """A user unrelated to the attestor org is hidden the attestation (404)."""
    del clean_state
    org_id, _owner = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    attestation = await _staffed_attestation(org_id, member_id, content_acked=False)
    stranger = await _new_user("stranger")

    response = await client.post(
        f"/v1/attestations/{attestation.id}/content-ack",
        json={"content_ack": True, "ack_version": "v1"},
        headers=_auth(stranger),
    )
    assert response.status_code == 404


async def test_late_submission_increments_org_profile(db_session) -> None:
    """A late report increments the org attestor profile's late counter."""
    org_id, _owner = await _attestor_org()
    member_id, member_user = await _add_member(org_id)
    reviewer = await _load_user(member_user)
    attestation = await _staffed_attestation(
        org_id,
        member_id,
        status="in_review",
        completion_due_at=datetime.now(UTC) - timedelta(hours=1),
        seed_rubric=True,
    )

    await report_service.submit_report(
        db=db_session,
        attestor=reviewer,
        attestation_id=attestation.id,
        payload=AttestationReportSubmitRequest(
            outcome="approved",
            summary=" ".join(["summary"] * 200),
            scope="Credential, process, and sample evidence review.",
            conditions=None,
            evidence_references={},
        ),
    )

    refreshed = await db_session.get(Attestation, attestation.id)
    assert refreshed.submitted_late is True
    async with async_session_factory() as session:
        count = await session.scalar(
            select(OrgAttestorProfile.late_submission_count).where(
                OrgAttestorProfile.org_id == org_id
            )
        )
    assert count == 1


async def test_requestor_sees_report_rubric_after_submission(
    client: AsyncClient, clean_state
) -> None:
    """The requestor can read the attestor's rubric once a report is submitted.

    The rubric is the attestor's per-dimension scoring; the paying requestor
    needs it to decide whether to accept or dispute, so a submitted report
    exposes each dimension's label, score, and comment to the requestor.
    """
    org_id, _owner = await _attestor_org()
    member_id, _member_user = await _add_member(org_id)
    attestation = await _staffed_attestation(
        org_id,
        member_id,
        status="report_submitted",
        seed_rubric=True,
    )

    token = create_access_token(
        user_id=attestation.requestor_id, roles=["operator"]
    )
    response = await client.get(
        f"/v1/attestations/{attestation.id}/report/rubric",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    scores = response.json()["scores"]
    assert len(scores) > 0
    first = scores[0]
    assert set(first) == {"dimension_key", "label", "score", "comment"}
    assert first["score"] == 5
    assert first["label"]
    assert "approval" in first["comment"]


async def test_report_rubric_hidden_from_non_requestor(
    client: AsyncClient, clean_state
) -> None:
    """A caller who is not the requestor cannot read the report rubric."""
    org_id, _owner = await _attestor_org()
    member_id, _member_user = await _add_member(org_id)
    attestation = await _staffed_attestation(
        org_id,
        member_id,
        status="report_submitted",
        seed_rubric=True,
    )
    stranger = await _new_user("rubric-stranger")
    token = create_access_token(user_id=stranger, roles=["operator"])

    response = await client.get(
        f"/v1/attestations/{attestation.id}/report/rubric",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
