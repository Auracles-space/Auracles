"""Integration tests for attestation clarification workspace endpoints."""

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
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationArtifactAccess,
    AttestationClarification,
    AttestationDispute,
    AttestationOffer,
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

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear clarification integration rows in FK-safe order."""
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
    """Ensure the integration database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def clean_state(migrated_database) -> AsyncIterator[None]:
    """Reset clarification state before and after each integration test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
    try:
        yield
    finally:
        await _reset_state()
        await engine.dispose()


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


async def _make_attestor_org(prefix: str) -> tuple[User, UUID, UUID]:
    """Create an approved attestor org with an owner member holding a valid CoI.

    Returns the owner ``User`` (the reviewing member), the org id, and the
    owner's ``OrgMember`` id.
    """
    user = await _make_user("attestor", prefix)
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        org = Organization(
            slug=f"clar-org-{uuid4().hex[:6]}",
            name="Clarification Org LLP",
            country="US",
            created_by=user.id,
        )
        session.add(org)
        await session.flush()
        member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
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
                coi_signed_at=now,
                coi_expires_at=now + timedelta(days=365),
            )
        )
        await session.commit()
        await session.refresh(member)
    return user, org.id, member.id


async def _in_review_attestation() -> tuple[User, User, Attestation]:
    """Create one attestation already in the in-review workspace state."""
    attestor, org_id, member_id = await _make_attestor_org("attestor")
    requestor = await _make_user("operator", "requestor")
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor.id,
            attestor_org_id=org_id,
            reviewing_member_id=member_id,
            status="in_review",
            review_type="quality",
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=["tax"],
            requested_jurisdictions=["US"],
            content_ack_at=datetime.now(UTC),
            content_ack_version="v1",
            review_started_at=datetime.now(UTC),
            completion_due_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(attestation)
        await session.commit()
        await session.refresh(attestation)
    return attestor, requestor, attestation


async def test_clarification_endpoints_round_trip(
    client: AsyncClient,
    clean_state,
) -> None:
    """Attestor send, requestor list, and requestor respond work end-to-end."""
    del clean_state
    attestor, requestor, attestation = await _in_review_attestation()
    attestor_headers = _auth_headers(attestor.id, ["attestor"])
    requestor_headers = _auth_headers(requestor.id, ["operator"])

    created = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications",
        headers=attestor_headers,
        json={"question": "Which framework version is in scope?"},
    )
    assert created.status_code == 201
    clarification_id = created.json()["id"]
    assert created.json()["status"] == "open"

    listed = await client.get(
        f"/v1/attestations/{attestation.id}/clarifications",
        headers=requestor_headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == clarification_id

    responded = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications/{clarification_id}/respond",
        headers=requestor_headers,
        json={"response": "Version 2."},
    )
    assert responded.status_code == 200
    assert responded.json()["status"] == "answered"
    assert responded.json()["response"] == "Version 2."


async def test_requestor_list_flags_open_clarification(
    client: AsyncClient,
    clean_state,
) -> None:
    """An open clarification flags the requestor's attestation for attention.

    Drives the requestor list card's attention dot: the flag is True only while
    a question is awaiting the requestor's answer, and clears once answered.
    """
    del clean_state
    attestor, requestor, attestation = await _in_review_attestation()
    attestor_headers = _auth_headers(attestor.id, ["attestor"])
    requestor_headers = _auth_headers(requestor.id, ["operator"])

    before = await client.get(
        "/v1/attestations?role=requestor", headers=requestor_headers
    )
    assert before.status_code == 200
    assert before.json()["attestations"][0]["open_clarification"] is False

    created = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications",
        headers=attestor_headers,
        json={"question": "Which framework version is in scope?"},
    )
    assert created.status_code == 201
    clarification_id = created.json()["id"]

    after = await client.get(
        "/v1/attestations?role=requestor", headers=requestor_headers
    )
    assert after.json()["attestations"][0]["open_clarification"] is True

    await client.post(
        f"/v1/attestations/{attestation.id}/clarifications/{clarification_id}/respond",
        headers=requestor_headers,
        json={"response": "Version 2."},
    )
    resolved = await client.get(
        "/v1/attestations?role=requestor", headers=requestor_headers
    )
    assert resolved.json()["attestations"][0]["open_clarification"] is False


async def test_reviewer_marks_answered_clarification_seen(
    client: AsyncClient,
    clean_state,
) -> None:
    """The assigned reviewer can stamp an answered clarification as seen.

    Clears the reviewer queue's "answer received" dot: mark-seen sets
    ``reviewer_seen_at`` on answered clarifications for the reviewing member.
    """
    del clean_state
    attestor, requestor, attestation = await _in_review_attestation()
    attestor_headers = _auth_headers(attestor.id, ["attestor"])
    requestor_headers = _auth_headers(requestor.id, ["operator"])

    created = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications",
        headers=attestor_headers,
        json={"question": "Which framework version is in scope?"},
    )
    clarification_id = created.json()["id"]
    await client.post(
        f"/v1/attestations/{attestation.id}/clarifications/{clarification_id}/respond",
        headers=requestor_headers,
        json={"response": "Version 2."},
    )

    seen = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications/mark-seen",
        headers=attestor_headers,
    )

    assert seen.status_code == 200
    async with async_session_factory() as session:
        row = await session.scalar(
            select(AttestationClarification).where(
                AttestationClarification.id == UUID(clarification_id)
            )
        )
    assert row is not None
    assert row.reviewer_seen_at is not None


async def test_mark_seen_rejects_non_reviewer(
    client: AsyncClient,
    clean_state,
) -> None:
    """A user who is not the assigned reviewer cannot mark answers seen."""
    del clean_state
    _attestor, requestor, attestation = await _in_review_attestation()

    response = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications/mark-seen",
        headers=_auth_headers(requestor.id, ["operator"]),
    )

    assert response.status_code == 404


async def test_clarification_response_is_hidden_from_third_parties(
    client: AsyncClient,
    clean_state,
) -> None:
    """An unrelated authenticated user receives 404 from clarification responses."""
    del clean_state
    attestor, _requestor, attestation = await _in_review_attestation()
    intruder = await _make_user("operator", "intruder")
    created = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications",
        headers=_auth_headers(attestor.id, ["attestor"]),
        json={"question": "Which framework version is in scope?"},
    )
    clarification_id = created.json()["id"]

    response = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications/{clarification_id}/respond",
        headers=_auth_headers(intruder.id, ["operator"]),
        json={"response": "Attempted response."},
    )

    assert response.status_code == 404


async def test_attestor_cannot_respond_to_clarification(
    client: AsyncClient,
    clean_state,
) -> None:
    """The assigned attestor cannot use the requestor-only respond endpoint."""
    del clean_state
    attestor, _requestor, attestation = await _in_review_attestation()
    headers = _auth_headers(attestor.id, ["attestor"])
    created = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications",
        headers=headers,
        json={"question": "Which framework version is in scope?"},
    )
    clarification_id = created.json()["id"]

    response = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications/{clarification_id}/respond",
        headers=headers,
        json={"response": "Version 2."},
    )

    assert response.status_code == 404


async def test_clarification_endpoints_require_authentication(
    client: AsyncClient,
    clean_state,
) -> None:
    """Unauthenticated clarification requests are rejected before service logic."""
    del clean_state
    _attestor, _requestor, attestation = await _in_review_attestation()

    response = await client.post(
        f"/v1/attestations/{attestation.id}/clarifications",
        json={"question": "Which framework version is in scope?"},
    )

    assert response.status_code == 401
