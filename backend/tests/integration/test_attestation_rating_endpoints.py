"""Integration tests for the attestation rating endpoint (Module 5 section 5.3)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationRating,
    AttestorProfile,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _reset_state() -> None:
    """Clear rating test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationRating))
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
    """Reset rating state before and after each integration test."""
    del migrated_database
    await engine.dispose()
    await _reset_state()
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


async def _stood_attestation(requestor_id: UUID) -> UUID:
    """Create one closed/approved attestation owned by the requestor."""
    attestor = await _make_user("attestor", "attestor")
    async with async_session_factory() as session:
        attestation = Attestation(
            target_type="contributor",
            target_id=uuid4(),
            requestor_id=requestor_id,
            attestor_id=attestor.id,
            status="closed",
            outcome="approved",
            report_published_eligible=True,
            fee_amount=Decimal("500.00"),
            currency="USD",
            requested_specializations=[],
            requested_jurisdictions=[],
        )
        session.add(attestation)
        await session.commit()
        return attestation.id


async def test_requestor_rates_report(client: AsyncClient, clean_state) -> None:
    """The requestor receives 201 and the persisted rating body."""
    del clean_state
    requestor = await _make_user("operator", "requestor")
    attestation_id = await _stood_attestation(requestor.id)

    response = await client.post(
        f"/v1/attestations/{attestation_id}/rating",
        headers=_auth_headers(requestor.id, ["operator"]),
        json={"stars": 5, "comment": "Excellent."},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["stars"] == 5
    assert body["attestation_id"] == str(attestation_id)


async def test_contributor_requestor_can_rate(
    client: AsyncClient, clean_state
) -> None:
    """A contributor requestor may rate — the endpoint is not operator-only."""
    del clean_state
    requestor = await _make_user("contributor", "requestor")
    attestation_id = await _stood_attestation(requestor.id)

    response = await client.post(
        f"/v1/attestations/{attestation_id}/rating",
        headers=_auth_headers(requestor.id, ["contributor"]),
        json={"stars": 4, "comment": None},
    )

    assert response.status_code == 201


async def test_duplicate_rating_conflicts(client: AsyncClient, clean_state) -> None:
    """A second rating on the same attestation returns 409, never 500."""
    del clean_state
    requestor = await _make_user("operator", "requestor")
    attestation_id = await _stood_attestation(requestor.id)
    headers = _auth_headers(requestor.id, ["operator"])

    first = await client.post(
        f"/v1/attestations/{attestation_id}/rating",
        headers=headers,
        json={"stars": 5, "comment": None},
    )
    second = await client.post(
        f"/v1/attestations/{attestation_id}/rating",
        headers=headers,
        json={"stars": 3, "comment": None},
    )

    assert first.status_code == 201
    assert second.status_code == 409


async def test_non_requestor_gets_404(client: AsyncClient, clean_state) -> None:
    """A non-requestor cannot rate; existence is hidden with 404."""
    del clean_state
    requestor = await _make_user("operator", "requestor")
    stranger = await _make_user("operator", "stranger")
    attestation_id = await _stood_attestation(requestor.id)

    response = await client.post(
        f"/v1/attestations/{attestation_id}/rating",
        headers=_auth_headers(stranger.id, ["operator"]),
        json={"stars": 5, "comment": None},
    )

    assert response.status_code == 404


async def test_wrong_role_forbidden(client: AsyncClient, clean_state) -> None:
    """An attestor-only caller is refused by the RBAC dependency with 403."""
    del clean_state
    requestor = await _make_user("operator", "requestor")
    attestation_id = await _stood_attestation(requestor.id)
    attestor = await _make_user("attestor", "outsider")

    response = await client.post(
        f"/v1/attestations/{attestation_id}/rating",
        headers=_auth_headers(attestor.id, ["attestor"]),
        json={"stars": 5, "comment": None},
    )

    assert response.status_code == 403


async def test_unauthenticated_rejected(client: AsyncClient, clean_state) -> None:
    """A request without a bearer token is rejected with 401."""
    del clean_state
    requestor = await _make_user("operator", "requestor")
    attestation_id = await _stood_attestation(requestor.id)

    response = await client.post(
        f"/v1/attestations/{attestation_id}/rating",
        json={"stars": 5, "comment": None},
    )

    assert response.status_code == 401


async def test_stars_out_of_range_unprocessable(
    client: AsyncClient, clean_state
) -> None:
    """Stars outside 1-5 are rejected by schema validation with 422."""
    del clean_state
    requestor = await _make_user("operator", "requestor")
    attestation_id = await _stood_attestation(requestor.id)

    response = await client.post(
        f"/v1/attestations/{attestation_id}/rating",
        headers=_auth_headers(requestor.id, ["operator"]),
        json={"stars": 6, "comment": None},
    )

    assert response.status_code == 422
