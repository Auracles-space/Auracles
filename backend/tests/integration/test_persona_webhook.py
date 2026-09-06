"""Integration tests for Persona identity-verification webhook ingestion.

Covers `POST /v1/webhooks/persona`: a verified inquiry decision flips
`kyc_status`, replays are deduplicated, and bad signatures are rejected.

Maps to: identity verification design (2026-06-24), build slice 2.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.integrations.persona import PersonaProviderError
from app.main import app
from app.modules.auth.models import IdentityVerification, User
from app.modules.notifications.models import Notification
from app.modules.webhooks import service as webhook_service
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async


def _persona_event(
    inquiry_id: str,
    inquiry_status: str,
    reference_id: str | None = None,
) -> dict[str, Any]:
    """Build a Persona inquiry webhook event body.

    ``reference_id`` is our user id as tagged on the hosted-flow link. Persona
    includes it on real events; it is what lets the first event find a row that
    has no inquiry id yet.
    """
    attributes: dict[str, Any] = {"status": inquiry_status}
    if reference_id is not None:
        attributes["reference-id"] = reference_id
    return {
        "data": {
            "type": "event",
            "id": "evt_test",
            "attributes": {
                "name": f"inquiry.{inquiry_status}",
                "payload": {
                    "data": {
                        "type": "inquiry",
                        "id": inquiry_id,
                        "attributes": attributes,
                    }
                },
            },
        }
    }


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure identity tables exist for endpoint tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def stub_persona_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass HMAC verification, returning the parsed body unless flagged bad."""

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
        **_: Any,
    ) -> dict[str, Any]:
        if signature_header == "bad-signature":
            raise PersonaProviderError("bad signature")
        return json.loads(payload)

    monkeypatch.setattr(
        webhook_service.persona,
        "verify_webhook",
        fake_verify_webhook,
    )


@pytest.fixture
async def webhook_context() -> AsyncIterator[None]:
    """Reset identity state around each webhook test."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _seed_inquiry(email: str, inquiry_id: str | None) -> UUID:
    """Create a user with a pending Persona inquiry and return the user id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="pending",
            )
            session.add(user)
            await session.flush()
            session.add(
                IdentityVerification(
                    user_id=user.id,
                    provider="persona",
                    inquiry_id=inquiry_id,
                    status="created",
                )
            )
        return user.id


async def test_approved_inquiry_marks_user_verified_once(
    client: AsyncClient,
    migrated_database: None,
    stub_persona_signature: None,
    webhook_context: None,
) -> None:
    """An approved inquiry verifies the user; replays are deduplicated."""
    user_id = await _seed_inquiry("approve@auracles.space", "inq_approve")
    body = json.dumps(_persona_event("inq_approve", "approved")).encode()

    first = await client.post(
        "/v1/webhooks/persona",
        content=body,
        headers={"Persona-Signature": "valid"},
    )
    replay = await client.post(
        "/v1/webhooks/persona",
        content=body,
        headers={"Persona-Signature": "valid"},
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        notifications = (
            (
                await session.execute(
                    select(Notification).where(Notification.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )

    assert first.status_code == 200
    assert first.json()["status"] == "processed"
    assert replay.json()["status"] == "duplicate"
    assert user is not None and user.kyc_status == "verified"
    assert len(notifications) == 1
    assert notifications[0].notification_type == "kyc_verified"


async def test_declined_inquiry_marks_user_rejected(
    client: AsyncClient,
    migrated_database: None,
    stub_persona_signature: None,
    webhook_context: None,
) -> None:
    """A declined inquiry marks the user rejected and notifies them."""
    user_id = await _seed_inquiry("decline@auracles.space", "inq_decline")
    body = json.dumps(_persona_event("inq_decline", "declined")).encode()

    response = await client.post(
        "/v1/webhooks/persona",
        content=body,
        headers={"Persona-Signature": "valid"},
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert user is not None and user.kyc_status == "rejected"


async def test_invalid_signature_is_rejected_without_state_change(
    client: AsyncClient,
    migrated_database: None,
    stub_persona_signature: None,
    webhook_context: None,
) -> None:
    """A bad signature returns 400, audits the rejection, and changes nothing."""
    user_id = await _seed_inquiry("badsig@auracles.space", "inq_badsig")
    body = json.dumps(_persona_event("inq_badsig", "approved")).encode()

    response = await client.post(
        "/v1/webhooks/persona",
        content=body,
        headers={"Persona-Signature": "bad-signature"},
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "webhook_signature_invalid")
        )

    assert response.status_code == 400
    assert user is not None and user.kyc_status == "pending"
    assert audit is not None


async def test_hosted_flow_inquiry_is_adopted_by_reference_id(
    client: AsyncClient,
    migrated_database: None,
    stub_persona_signature: None,
    webhook_context: None,
) -> None:
    """The first event claims the pending row that has no inquiry id yet.

    Verification starts from a hosted-flow link, so Persona mints the inquiry
    only when the user arrives and the row is written with a null inquiry_id.
    Without matching on reference-id the decision would be dropped as an
    unknown inquiry and the user would stay pending forever.
    """
    user_id = await _seed_inquiry("hosted@auracles.space", None)
    body = json.dumps(
        _persona_event("inq_hosted", "approved", reference_id=str(user_id))
    ).encode()

    response = await client.post(
        "/v1/webhooks/persona",
        content=body,
        headers={"Persona-Signature": "valid"},
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        record = await session.scalar(
            select(IdentityVerification).where(
                IdentityVerification.user_id == user_id
            )
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert user is not None and user.kyc_status == "verified"
    # The id is adopted, so later events for the same inquiry match directly.
    assert record is not None and record.inquiry_id == "inq_hosted"


async def test_hosted_flow_event_without_matching_user_is_not_applied(
    client: AsyncClient,
    migrated_database: None,
    stub_persona_signature: None,
    webhook_context: None,
) -> None:
    """A reference id that matches no pending row changes nothing.

    Guards the adoption path against binding an inquiry to an arbitrary user:
    an unknown reference is reported as received and dropped, never applied.
    """
    user_id = await _seed_inquiry("nomatch@auracles.space", "inq_owned")
    stranger_id = "00000000-0000-4000-8000-0000000000ff"
    body = json.dumps(
        _persona_event("inq_stranger", "approved", reference_id=stranger_id)
    ).encode()

    response = await client.post(
        "/v1/webhooks/persona",
        content=body,
        headers={"Persona-Signature": "valid"},
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)

    assert response.status_code == 200
    assert response.json()["status"] == "received"
    assert user is not None and user.kyc_status == "pending"
