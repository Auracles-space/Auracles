"""Integration tests for Attestation matching and cohort offer handling."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation import matching_service
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
    AttestorApplication,
    AttestorProfile,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework
from app.modules.projects.models import Milestone, Project, Proposal
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> None:
    """Ensure Attestation matching tables exist before the test runs."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    sync_engine.dispose()


@pytest.fixture
async def matching_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset matching state and install a deterministic Stripe webhook double."""
    await engine.dispose()
    await reset_matching_state()
    context: dict[str, Any] = {"event": None}

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Return the configured event after simulating signature verification."""
        del payload
        if signature_header != "valid-signature":
            msg = "bad signature"
            raise webhook_service.StripeProviderError(msg)
        event = context["event"]
        if not isinstance(event, dict):
            msg = "missing test event"
            raise webhook_service.StripeProviderError(msg)
        return event

    monkeypatch.setattr(webhook_service.stripe, "verify_webhook", fake_verify_webhook)
    try:
        yield context
    finally:
        await reset_matching_state()
        await engine.dispose()


async def reset_matching_state() -> None:
    """Delete test rows in dependency-safe order."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(WebhookEvent))
            await session.execute(delete(AuditLog))
            await session.execute(delete(WorkspaceMessage))
            await session.execute(delete(AttestationUploadSession))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(Attestation))
            await session.execute(delete(AttestorProfile))
            await session.execute(delete(AttestorApplication))
            await session.execute(delete(Milestone))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(Credential))
            await session.execute(delete(Framework))
            await session.execute(delete(Project))
            await session.execute(delete(Proposal))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            for key, value in {
                "attestation_cohort_size": "2",
                "attestation_offer_accept_hours": "48",
                "attestation_completion_sla_days_operator": "7",
            }.items():
                row = await session.get(PlatformConfig, key)
                if row is None:
                    session.add(PlatformConfig(key=key, value=value))
                else:
                    row.value = value


async def create_user(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved role rows."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


async def create_attestor_profile(
    user_id: UUID,
    *,
    specializations: list[str],
    jurisdictions: list[str],
    approved_at: datetime | None = None,
) -> None:
    """Create one active approved matching profile for an Attestor."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                AttestorProfile(
                    user_id=user_id,
                    specializations=specializations,
                    jurisdictions=jurisdictions,
                    active=True,
                    approved_at=approved_at or datetime.now(UTC),
                )
            )


async def create_pending_attestation_fee(
    requestor_id: UUID,
) -> tuple[UUID, UUID]:
    """Create a pending funded-target Attestation fee transaction."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="operator",
                target_id=requestor_id,
                requestor_id=requestor_id,
                status="pending_fee",
                requested_specializations=["healthcare"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("300.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=requestor_id,
                payee_id=None,
                amount=Decimal("300.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("300.00"),
                transaction_type="attestation_fee",
                status="pending",
                provider="stripe",
                provider_ref="pi_attestation_matching_123",
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            await session.flush()
            return attestation.id, transaction.id


async def set_platform_config(key: str, value: str) -> None:
    """Set one platform configuration value for a matching test."""
    async with async_session_factory() as session:
        async with session.begin():
            row = await session.get(PlatformConfig, key)
            if row is None:
                session.add(PlatformConfig(key=key, value=value))
            else:
                row.value = value


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


def payment_intent_event(
    event_id: str,
    *,
    transaction_id: UUID,
    attestation_id: UUID,
    requestor_id: UUID,
) -> dict[str, Any]:
    """Build a Stripe escrow success event for an Attestation fee."""
    return {
        "id": event_id,
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_attestation_matching_123",
                "metadata": {
                    "transaction_id": str(transaction_id),
                    "kind": "escrow",
                    "attestation_id": str(attestation_id),
                    "release_conditions": json.dumps(
                        {
                            "kind": "attestation",
                            "attestation_id": str(attestation_id),
                            "requestor_user_id": str(requestor_id),
                        }
                    ),
                },
            }
        },
    }


async def test_attestation_matching_offers_and_first_accept_wins(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Funded Attestations offer a cohort and assign only the first acceptor."""
    del migrated_database
    requestor_id = await create_user(
        "matching-requestor@auracles.space",
        ["operator", "attestor"],
    )
    first_attestor_id = await create_user(
        "matching-first@auracles.space",
        ["attestor"],
    )
    second_attestor_id = await create_user(
        "matching-second@auracles.space",
        ["attestor"],
    )
    unmatched_attestor_id = await create_user(
        "matching-unmatched@auracles.space",
        ["attestor"],
    )
    await create_attestor_profile(
        requestor_id,
        specializations=["healthcare"],
        jurisdictions=["US"],
    )
    await create_attestor_profile(
        first_attestor_id,
        specializations=["healthcare", "operations"],
        jurisdictions=["US"],
    )
    await create_attestor_profile(
        second_attestor_id,
        specializations=["healthcare"],
        jurisdictions=["US", "CA"],
    )
    await create_attestor_profile(
        unmatched_attestor_id,
        specializations=["healthcare"],
        jurisdictions=["GB"],
    )
    attestation_id, transaction_id = await create_pending_attestation_fee(requestor_id)

    matching_context["event"] = payment_intent_event(
        "evt_attestation_matching_success",
        transaction_id=transaction_id,
        attestation_id=attestation_id,
        requestor_id=requestor_id,
    )
    webhook_response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    assignments_response = await client.get(
        "/v1/attestor/assignments",
        headers=auth_headers(first_attestor_id, ["attestor"]),
    )
    accept_response = await client.post(
        f"/v1/attestations/{attestation_id}/accept",
        headers=auth_headers(first_attestor_id, ["attestor"]),
    )
    late_accept_response = await client.post(
        f"/v1/attestations/{attestation_id}/accept",
        headers=auth_headers(second_attestor_id, ["attestor"]),
    )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        transaction = await session.get(Transaction, transaction_id)
        offers = (
            await session.execute(
                select(AttestationOffer).where(
                    AttestationOffer.attestation_id == attestation_id
                )
            )
        ).scalars().all()
        audits = (
            await session.execute(
                select(AuditLog.action).where(
                    AuditLog.target_type == "attestation",
                    AuditLog.target_id == attestation_id,
                )
            )
        ).scalars().all()

    assert webhook_response.status_code == 200
    assert assignments_response.status_code == 200
    assert assignments_response.json()["assignments"][0]["attestation_id"] == str(
        attestation_id
    )
    assert assignments_response.json()["assignments"][0]["offer_status"] == "offered"
    assert accept_response.status_code == 200
    assert late_accept_response.status_code == 409
    assert attestation is not None
    assert attestation.status == "accepted"
    assert attestation.attestor_id == first_attestor_id
    assert attestation.accepted_at is not None
    assert attestation.completion_due_at is not None
    assert transaction is not None
    assert transaction.status == "completed"
    assert transaction.payee_id == first_attestor_id
    assert {offer.attestor_id for offer in offers} == {
        first_attestor_id,
        second_attestor_id,
    }
    assert {
        (offer.attestor_id, offer.status)
        for offer in offers
    } == {
        (first_attestor_id, "accepted"),
        (second_attestor_id, "superseded"),
    }
    assert "attestation_offered" in audits
    assert "attestation_accepted" in audits


async def test_attestation_decline_advances_to_next_cohort(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Declining the only active cohort offer sends the next eligible offer."""
    del migrated_database
    await set_platform_config("attestation_cohort_size", "1")
    requestor_id = await create_user(
        "decline-requestor@auracles.space",
        ["operator"],
    )
    first_attestor_id = await create_user("decline-first@auracles.space", ["attestor"])
    second_attestor_id = await create_user(
        "decline-second@auracles.space",
        ["attestor"],
    )
    await create_attestor_profile(
        first_attestor_id,
        specializations=["healthcare"],
        jurisdictions=["US"],
        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await create_attestor_profile(
        second_attestor_id,
        specializations=["healthcare"],
        jurisdictions=["US"],
        approved_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    attestation_id, transaction_id = await create_pending_attestation_fee(requestor_id)
    matching_context["event"] = payment_intent_event(
        "evt_attestation_decline_success",
        transaction_id=transaction_id,
        attestation_id=attestation_id,
        requestor_id=requestor_id,
    )
    webhook_response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    decline_response = await client.post(
        f"/v1/attestations/{attestation_id}/decline",
        headers=auth_headers(first_attestor_id, ["attestor"]),
    )

    async with async_session_factory() as session:
        offers = (
            await session.execute(
                select(AttestationOffer)
                .where(AttestationOffer.attestation_id == attestation_id)
                .order_by(AttestationOffer.cohort_index)
            )
        ).scalars().all()
        attestation = await session.get(Attestation, attestation_id)

    assert webhook_response.status_code == 200
    assert decline_response.status_code == 200
    assert attestation is not None
    assert attestation.status == "offered"
    offer_states = [
        (offer.attestor_id, offer.status, offer.cohort_index) for offer in offers
    ]
    assert offer_states == [
        (first_attestor_id, "declined", 0),
        (second_attestor_id, "offered", 1),
    ]


async def test_expire_stale_attestation_offers_marks_needs_admin(
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Offer expiry closes stale offers and escalates when no cohort remains."""
    del migrated_database, matching_context
    requestor_id = await create_user("expiry-requestor@auracles.space", ["operator"])
    attestor_id = await create_user("expiry-attestor@auracles.space", ["attestor"])
    await create_attestor_profile(
        attestor_id,
        specializations=["healthcare"],
        jurisdictions=["US"],
    )
    attestation_id, transaction_id = await create_pending_attestation_fee(requestor_id)
    current_time = datetime.now(UTC)

    async with async_session_factory() as session:
        async with session.begin():
            attestation = await session.get(Attestation, attestation_id)
            transaction = await session.get(Transaction, transaction_id)
            assert attestation is not None
            assert transaction is not None
            attestation.status = "offered"
            transaction.status = "completed"
            session.add(
                AttestationOffer(
                    attestation_id=attestation_id,
                    attestor_id=attestor_id,
                    cohort_index=0,
                    status="offered",
                    offered_at=current_time - timedelta(hours=49),
                    expires_at=current_time - timedelta(hours=1),
                )
            )

    async with async_session_factory() as session:
        expired_count = await matching_service.expire_stale_offers(
            session,
            now=current_time,
        )

    async with async_session_factory() as session:
        offer = await session.scalar(
            select(AttestationOffer).where(
                AttestationOffer.attestation_id == attestation_id
            )
        )
        attestation = await session.get(Attestation, attestation_id)
        needs_admin_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_needs_admin",
                AuditLog.target_id == attestation_id,
            )
        )

    assert expired_count == 1
    assert offer is not None
    assert offer.status == "expired"
    assert attestation is not None
    assert attestation.status == "needs_admin"
    assert needs_admin_audit is not None
