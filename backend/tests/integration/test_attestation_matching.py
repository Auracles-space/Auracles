"""Integration tests for Attestation matching and cohort offer handling."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.attestation import (
    dispute_service,
    matching_service,
    notifications,
    release_service,
    rubrics,
)
from app.modules.attestation import report as report_service
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationRubricDimension,
    AttestationRubricScore,
    AttestationUploadSession,
    AttestorApplication,
    AttestorProfile,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework
from app.modules.projects.models import Milestone, Project, Proposal
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for TOTP-sensitive admin attestation routes."""

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored value or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        """Delete stored values and counters."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


class FakeStripeRefund:
    """Small stand-in for a Stripe refund result."""

    def __init__(self, refund_id: str) -> None:
        """Store the provider refund id and status."""
        self.id = refund_id
        self.status = "succeeded"


class FakeNotificationTask:
    """Celery-task-shaped test double for attestation notifications."""

    def __init__(self, calls: list[dict[str, Any]]) -> None:
        """Store delayed notification dispatches in the provided list."""
        self.calls = calls

    def delay(self, **kwargs: Any) -> None:
        """Capture notification dispatch parameters without Redis or email."""
        self.calls.append(kwargs)


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
                "attestation_dispute_window_business_days": "5",
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


async def create_admin_user() -> tuple[UUID, str]:
    """Create an admin user with encrypted TOTP enabled."""
    secret = pyotp.random_base32()
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"attestation-admin-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Attestation Admin",
                email_verified=True,
                totp_enabled=True,
                totp_secret=encrypt_totp_secret(secret),
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="admin",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id, secret


async def create_attestor_profile(
    user_id: UUID,
    *,
    specializations: list[str],
    jurisdictions: list[str],
    approved_at: datetime | None = None,
) -> None:
    """Create one active approved matching profile with a valid signed CoI."""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                AttestorProfile(
                    user_id=user_id,
                    specializations=specializations,
                    jurisdictions=jurisdictions,
                    active=True,
                    approved_at=approved_at or now,
                    coi_signed_at=now,
                    coi_expires_at=now + timedelta(days=365),
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


async def seed_quality_rubric_scores(attestation_id: UUID) -> None:
    """Populate a quality workspace with complete rubric scores and comments."""
    async with async_session_factory() as session:
        async with session.begin():
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
                        attestation_id=attestation_id,
                        dimension_id=dimension.id,
                        score=5,
                        comment=(
                            f"{dimension.label} is fully covered in this review "
                            "with detailed evidence and implementation notes."
                        ),
                    )
                )


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Funded Attestations offer a cohort and assign only the first acceptor."""
    del migrated_database
    notification_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )
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
        json={"content_ack": True, "ack_version": "v1"},
    )
    late_accept_response = await client.post(
        f"/v1/attestations/{attestation_id}/accept",
        headers=auth_headers(second_attestor_id, ["attestor"]),
        json={"content_ack": True, "ack_version": "v1"},
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
    assert attestation.content_ack_at is not None
    assert attestation.content_ack_version == "v1"
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
    assert [call["notification_type"] for call in notification_calls] == [
        "attestation_fee_funded",
        "attestation_offer_received",
        "attestation_offer_received",
        "attestation_accepted",
    ]
    assert notification_calls[0]["user_id"] == str(requestor_id)
    assert {call["user_id"] for call in notification_calls[1:3]} == {
        str(first_attestor_id),
        str(second_attestor_id),
    }
    assert notification_calls[3]["user_id"] == str(requestor_id)


async def test_accept_requires_content_use_acknowledgment(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Accepting an attestation offer without the acknowledgment returns 422."""
    del migrated_database
    requestor_id = await create_user(
        "ack-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user("ack-attestor@auracles.space", ["attestor"])
    await create_attestor_profile(
        attestor_id,
        specializations=["healthcare"],
        jurisdictions=["US"],
    )
    attestation_id, transaction_id = await create_pending_attestation_fee(requestor_id)
    matching_context["event"] = payment_intent_event(
        "evt_attestation_ack_required",
        transaction_id=transaction_id,
        attestation_id=attestation_id,
        requestor_id=requestor_id,
    )
    webhook_response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    accept_response = await client.post(
        f"/v1/attestations/{attestation_id}/accept",
        headers=auth_headers(attestor_id, ["attestor"]),
        json={"content_ack": False, "ack_version": "v1"},
    )

    assert webhook_response.status_code == 200
    assert accept_response.status_code == 422
    assert accept_response.json()["detail"] == (
        "Content-use acknowledgment is required to accept."
    )


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


async def test_revoke_overdue_attestation_reoffers_and_clears_payee(
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Overdue accepted assignments are revoked and moved to the next cohort."""
    del migrated_database, matching_context
    await set_platform_config("attestation_cohort_size", "1")
    requestor_id = await create_user("overdue-requestor@auracles.space", ["operator"])
    first_attestor_id = await create_user("overdue-first@auracles.space", ["attestor"])
    second_attestor_id = await create_user(
        "overdue-second@auracles.space",
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
    current_time = datetime.now(UTC)

    async with async_session_factory() as session:
        async with session.begin():
            attestation = await session.get(Attestation, attestation_id)
            transaction = await session.get(Transaction, transaction_id)
            assert attestation is not None
            assert transaction is not None
            attestation.status = "accepted"
            attestation.attestor_id = first_attestor_id
            attestation.accepted_at = current_time - timedelta(days=8)
            # Past SLA *and* past the 24h completion grace window (§4.8), so the
            # grace-aware revoke beat fires.
            attestation.completion_due_at = current_time - timedelta(hours=25)
            transaction.status = "completed"
            transaction.payee_id = first_attestor_id
            session.add(
                AttestationOffer(
                    attestation_id=attestation_id,
                    attestor_id=first_attestor_id,
                    cohort_index=0,
                    status="accepted",
                    offered_at=current_time - timedelta(days=9),
                    responded_at=current_time - timedelta(days=8),
                    expires_at=current_time - timedelta(days=7),
                )
            )

    async with async_session_factory() as session:
        revoked_count = await matching_service.revoke_overdue_attestations(
            session,
            now=current_time,
        )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        transaction = await session.get(Transaction, transaction_id)
        offers = (
            await session.execute(
                select(AttestationOffer)
                .where(AttestationOffer.attestation_id == attestation_id)
                .order_by(AttestationOffer.cohort_index)
            )
        ).scalars().all()
        reassigned_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_reassigned",
                AuditLog.target_id == attestation_id,
            )
        )

    assert revoked_count == 1
    assert attestation is not None
    assert attestation.status == "offered"
    assert attestation.attestor_id is None
    assert attestation.accepted_at is None
    assert attestation.completion_due_at is None
    assert transaction is not None
    assert transaction.payee_id is None
    offer_states = [
        (offer.attestor_id, offer.status, offer.cohort_index) for offer in offers
    ]
    assert offer_states == [
        (first_attestor_id, "superseded", 0),
        (second_attestor_id, "offered", 1),
    ]
    assert reassigned_audit is not None


async def test_assigned_attestor_uploads_evidence_and_submits_report(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assigned Attestors can publish structured reports with private evidence."""
    del migrated_database, matching_context
    notification_calls: list[dict[str, Any]] = []
    requestor_id = await create_user("report-requestor@auracles.space", ["operator"])
    attestor_id = await create_user("report-attestor@auracles.space", ["attestor"])
    await create_attestor_profile(
        attestor_id,
        specializations=["healthcare"],
        jurisdictions=["US"],
    )
    attestation_id, transaction_id = await create_pending_attestation_fee(requestor_id)
    dispatched_tasks: list[str] = []
    dispatched_scans: list[str] = []

    def fake_presigned_post(
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Return a deterministic presigned POST payload for the report test."""
        del bucket, max_size, expires_in
        return {
            "url": "https://uploads.example.test",
            "fields": {"key": key, "Content-Type": mime_type},
        }

    class FakeRenderTask:
        """Capture queued report rendering tasks without running Celery."""

        @staticmethod
        def delay(attestation_id: str) -> None:
            dispatched_tasks.append(attestation_id)

    class FakeScanTask:
        """Capture queued evidence scan tasks without running Celery."""

        @staticmethod
        def delay(upload_session_id: str) -> None:
            dispatched_scans.append(upload_session_id)

    monkeypatch.setattr(
        report_service.s3.storage,
        "presigned_post",
        fake_presigned_post,
    )
    monkeypatch.setattr(report_service, "render_attestation_report_pdf", FakeRenderTask)
    monkeypatch.setattr(report_service, "scan_attestation_upload", FakeScanTask)
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )
    report_summary = " ".join(["reviewed"] * 80)

    current_time = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            attestation = await session.get(Attestation, attestation_id)
            transaction = await session.get(Transaction, transaction_id)
            assert attestation is not None
            assert transaction is not None
            attestation.status = "in_review"
            attestation.attestor_id = attestor_id
            attestation.accepted_at = current_time
            attestation.review_type = "quality"
            attestation.review_started_at = current_time
            attestation.completion_due_at = current_time + timedelta(days=7)
            transaction.status = "completed"
            transaction.payee_id = attestor_id
            session.add(
                AttestationOffer(
                    attestation_id=attestation_id,
                    attestor_id=attestor_id,
                    cohort_index=0,
                    status="accepted",
                    offered_at=current_time - timedelta(hours=2),
                    responded_at=current_time - timedelta(hours=1),
                    expires_at=current_time + timedelta(hours=47),
                )
            )
    await seed_quality_rubric_scores(attestation_id)

    upload_response = await client.post(
        f"/v1/attestations/{attestation_id}/uploads",
        headers=auth_headers(attestor_id, ["attestor"]),
        json={
            "file_name": "inspection-notes.pdf",
            "content_type": "application/pdf",
            "size_bytes": 4096,
        },
    )
    evidence_key = upload_response.json()["s3_key"]
    pending_report_response = await client.post(
        f"/v1/attestations/{attestation_id}/report",
        headers=auth_headers(attestor_id, ["attestor"]),
        json={
            "outcome": "approved",
            "summary": report_summary,
            "scope": "Credential, process, and sample evidence review.",
            "evidence_references": {"file_keys": [evidence_key]},
        },
    )

    async with async_session_factory() as session:
        upload_session = await session.scalar(
            select(AttestationUploadSession).where(
                AttestationUploadSession.s3_key == evidence_key
            )
        )
        assert upload_session is not None
        upload_session_id = upload_session.id

    async with async_session_factory() as session:
        async with session.begin():
            upload_session = await session.scalar(
                select(AttestationUploadSession).where(
                    AttestationUploadSession.s3_key == evidence_key
                )
            )
            assert upload_session is not None
            upload_session.scan_status = "clean"

    report_response = await client.post(
        f"/v1/attestations/{attestation_id}/report",
        headers=auth_headers(attestor_id, ["attestor"]),
        json={
            "outcome": "approved",
            "summary": report_summary,
            "scope": "Credential, process, and sample evidence review.",
            "evidence_references": {"file_keys": [evidence_key]},
        },
    )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        upload_session = await session.scalar(
            select(AttestationUploadSession).where(
                AttestationUploadSession.s3_key == evidence_key
            )
        )
        audits = (
            await session.execute(
                select(AuditLog.action).where(
                    AuditLog.target_type == "attestation",
                    AuditLog.target_id == attestation_id,
                )
            )
        ).scalars().all()

    assert upload_response.status_code == 201
    assert upload_response.json()["fields"]["Content-Type"] == "application/pdf"
    assert pending_report_response.status_code == 409
    assert dispatched_scans == [str(upload_session_id)]
    assert report_response.status_code == 200
    assert report_response.json()["status"] == "report_submitted"
    assert report_response.json()["outcome"] == "approved"
    assert report_response.json()["summary"] == report_summary
    assert report_response.json()["report_key"] == (
        f"attestation-reports/{attestation_id}/report.pdf"
    )
    assert attestation is not None
    assert attestation.status == "report_submitted"
    assert attestation.issued_at is not None
    assert attestation.dispute_window_ends_at is not None
    assert attestation.dispute_window_ends_at > attestation.issued_at
    assert upload_session is not None
    assert upload_session.scan_status == "clean"
    assert upload_session.consumed_at is not None
    assert dispatched_tasks == [str(attestation_id)]
    assert "attestation_report_submitted" in audits
    assert "attestation_published" in audits
    assert "attestation_outcome_recorded" in audits
    assert [call["notification_type"] for call in notification_calls] == [
        "attestation_report_submitted",
    ]
    assert notification_calls[0]["user_id"] == str(requestor_id)
    assert notification_calls[0]["payload"]["outcome"] == "approved"


async def test_unassigned_attestor_cannot_submit_report(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Approved but unassigned Attestors cannot manage another Attestor's report."""
    del migrated_database, matching_context
    requestor_id = await create_user(
        "report-denied-requestor@auracles.space",
        ["operator"],
    )
    assigned_attestor_id = await create_user(
        "report-denied-assigned@auracles.space",
        ["attestor"],
    )
    unassigned_attestor_id = await create_user(
        "report-denied-unassigned@auracles.space",
        ["attestor"],
    )
    await create_attestor_profile(
        assigned_attestor_id,
        specializations=["healthcare"],
        jurisdictions=["US"],
    )
    await create_attestor_profile(
        unassigned_attestor_id,
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
            attestation.status = "accepted"
            attestation.attestor_id = assigned_attestor_id
            attestation.accepted_at = current_time
            attestation.completion_due_at = current_time + timedelta(days=7)
            transaction.status = "completed"
            transaction.payee_id = assigned_attestor_id

    upload_response = await client.post(
        f"/v1/attestations/{attestation_id}/uploads",
        headers=auth_headers(unassigned_attestor_id, ["attestor"]),
        json={
            "file_name": "wrong-attestor.pdf",
            "content_type": "application/pdf",
            "size_bytes": 4096,
        },
    )
    report_response = await client.post(
        f"/v1/attestations/{attestation_id}/report",
        headers=auth_headers(unassigned_attestor_id, ["attestor"]),
        json={
            "outcome": "approved",
            "summary": "This report should not be accepted by the API.",
            "scope": "Unauthorized attestor submission attempt.",
            "evidence_references": {},
        },
    )

    assert upload_response.status_code == 404
    assert report_response.status_code == 404


async def create_report_submitted_attestation(
    requestor_id: UUID,
    attestor_id: UUID,
    *,
    dispute_window_ends_at: datetime | None = None,
) -> tuple[UUID, UUID, UUID]:
    """Create a report-submitted Attestation with held escrow for release tests."""
    current_time = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="operator",
                target_id=requestor_id,
                requestor_id=requestor_id,
                attestor_id=attestor_id,
                status="report_submitted",
                outcome="approved",
                requested_specializations=["healthcare"],
                requested_jurisdictions=["US"],
                summary="The reviewed operator evidence supports approval.",
                scope="Credential, process, and sample evidence review.",
                evidence_references={},
                report_key=f"attestation-reports/{uuid4()}/report.pdf",
                fee_amount=Decimal("300.00"),
                currency="USD",
                accepted_at=current_time - timedelta(days=1),
                completion_due_at=current_time + timedelta(days=6),
                issued_at=current_time - timedelta(hours=1),
                dispute_window_ends_at=dispute_window_ends_at
                or current_time + timedelta(days=14),
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=requestor_id,
                payee_id=attestor_id,
                amount=Decimal("300.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("300.00"),
                transaction_type="attestation_fee",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_attestation_release_{uuid4()}",
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=attestation.id,
                ref_type="attestation",
                amount=Decimal("300.00"),
                currency="USD",
                status="held",
                release_conditions={"kind": "attestation"},
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            attestation.escrow_id = escrow.id
            return attestation.id, transaction.id, escrow.id


async def create_needs_admin_attestation(
    requestor_id: UUID,
) -> tuple[UUID, UUID, UUID]:
    """Create a needs-admin Attestation with held escrow for admin tests."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="operator",
                target_id=requestor_id,
                requestor_id=requestor_id,
                status="needs_admin",
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
                status="completed",
                provider="stripe",
                provider_ref=f"pi_attestation_needs_admin_{uuid4()}",
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=attestation.id,
                ref_type="attestation",
                amount=Decimal("300.00"),
                currency="USD",
                status="held",
                release_conditions={"kind": "attestation"},
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            attestation.escrow_id = escrow.id
            return attestation.id, transaction.id, escrow.id


async def test_requestor_accepts_report_and_releases_attestation_escrow(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requestors can accept a submitted report and close released escrow."""
    del migrated_database, matching_context
    notification_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )
    requestor_id = await create_user("release-requestor@auracles.space", ["operator"])
    attestor_id = await create_user("release-attestor@auracles.space", ["attestor"])
    (
        attestation_id,
        transaction_id,
        escrow_id,
    ) = await create_report_submitted_attestation(requestor_id, attestor_id)

    response = await client.post(
        f"/v1/attestations/{attestation_id}/accept-report",
        headers=auth_headers(requestor_id, ["operator"]),
    )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        transaction = await session.get(Transaction, transaction_id)
        escrow = await session.get(Escrow, escrow_id)
        audits = (
            await session.execute(
                select(AuditLog.action).where(
                    AuditLog.target_type.in_(("attestation", "escrow")),
                    AuditLog.target_id.in_((attestation_id, escrow_id)),
                )
            )
        ).scalars().all()

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["closed_at"] is not None
    assert attestation is not None
    assert attestation.status == "closed"
    assert attestation.closed_at is not None
    assert transaction is not None
    assert transaction.status == "completed"
    assert transaction.payee_id == attestor_id
    assert escrow is not None
    assert escrow.status == "released"
    assert escrow.released_by == requestor_id
    assert "escrow_released" in audits
    assert "attestation_released" in audits
    assert [call["notification_type"] for call in notification_calls] == [
        "attestation_released",
    ]
    assert notification_calls[0]["user_id"] == str(attestor_id)


async def test_auto_release_attestations_closes_past_dispute_window_reports(
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Beat auto-releases undisputed reports after the dispute window ends."""
    del migrated_database, matching_context
    requestor_id = await create_user(
        "auto-release-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "auto-release-attestor@auracles.space",
        ["attestor"],
    )
    releasable_id, _, releasable_escrow_id = await create_report_submitted_attestation(
        requestor_id,
        attestor_id,
        dispute_window_ends_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    disputed_id, _, disputed_escrow_id = await create_report_submitted_attestation(
        requestor_id,
        attestor_id,
        dispute_window_ends_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                AttestationDispute(
                    attestation_id=disputed_id,
                    raised_by=requestor_id,
                    category="process_violation",
                    reason="The evidence does not match the report.",
                    status="open",
                )
            )

    async with async_session_factory() as session:
        released_count = await release_service.auto_release_attestations(session)
        second_count = await release_service.auto_release_attestations(session)

    async with async_session_factory() as session:
        releasable = await session.get(Attestation, releasable_id)
        releasable_escrow = await session.get(Escrow, releasable_escrow_id)
        disputed = await session.get(Attestation, disputed_id)
        disputed_escrow = await session.get(Escrow, disputed_escrow_id)
        release_audits = (
            await session.execute(
                select(AuditLog.action).where(
                    AuditLog.action == "attestation_released",
                    AuditLog.target_id == releasable_id,
                )
            )
        ).scalars().all()

    assert released_count == 1
    assert second_count == 0
    assert releasable is not None
    assert releasable.status == "closed"
    assert releasable.closed_at is not None
    assert releasable_escrow is not None
    assert releasable_escrow.status == "released"
    assert disputed is not None
    assert disputed.status == "report_submitted"
    assert disputed_escrow is not None
    assert disputed_escrow.status == "held"
    assert release_audits == ["attestation_released"]


async def test_requestor_raises_attestation_dispute_before_window_closes(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requestors can dispute report-submitted Attestations during the window."""
    del migrated_database, matching_context
    notification_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )
    requestor_id = await create_user("dispute-requestor@auracles.space", ["operator"])
    attestor_id = await create_user("dispute-attestor@auracles.space", ["attestor"])
    attestation_id, _, _ = await create_report_submitted_attestation(
        requestor_id,
        attestor_id,
    )

    response = await client.post(
        f"/v1/attestations/{attestation_id}/disputes",
        headers=auth_headers(requestor_id, ["operator"]),
        json={
            "category": "scope_error",
            "reason": "The public report omits evidence we submitted.",
        },
    )
    duplicate = await client.post(
        f"/v1/attestations/{attestation_id}/disputes",
        headers=auth_headers(requestor_id, ["operator"]),
        json={
            "category": "scope_error",
            "reason": "Duplicate active dispute should be blocked.",
        },
    )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        dispute = await session.get(AttestationDispute, UUID(response.json()["id"]))
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_disputed",
                AuditLog.target_id == attestation_id,
            )
        )

    assert response.status_code == 201
    assert response.json()["status"] == "open"
    assert duplicate.status_code == 409
    assert attestation is not None
    assert attestation.status == "disputed"
    assert dispute is not None
    assert dispute.raised_by == requestor_id
    assert dispute.reason == "The public report omits evidence we submitted."
    assert audit is not None
    assert [call["notification_type"] for call in notification_calls] == [
        "attestation_disputed",
    ]
    assert notification_calls[0]["user_id"] == str(attestor_id)


async def test_admin_resolves_attestation_dispute_with_split(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin split resolution releases part of an Attestation fee and refunds rest."""
    del migrated_database, matching_context
    fake_redis = FakeRedis()
    refund_calls: list[dict[str, Any]] = []
    notification_calls: list[dict[str, Any]] = []

    async def override_redis() -> FakeRedis:
        """Return Redis test double for admin TOTP verification."""
        return fake_redis

    async def fake_create_refund(
        *,
        payment_intent_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> FakeStripeRefund:
        """Record the Stripe refund portion of a split resolution."""
        refund_calls.append(
            {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeRefund("re_attestation_split_123")

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(escrow_service.stripe, "create_refund", fake_create_refund)
    monkeypatch.setattr(
        notifications,
        "dispatch_project_notification",
        FakeNotificationTask(notification_calls),
    )

    requestor_id = await create_user(
        "split-dispute-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "split-dispute-attestor@auracles.space",
        ["attestor"],
    )
    admin_id, totp_secret = await create_admin_user()
    attestation_id, transaction_id, escrow_id = (
        await create_report_submitted_attestation(requestor_id, attestor_id)
    )
    raised = await client.post(
        f"/v1/attestations/{attestation_id}/disputes",
        headers=auth_headers(requestor_id, ["operator"]),
        json={
            "category": "scope_error",
            "reason": "The report partly overstates what was verified.",
        },
    )
    dispute_id = raised.json()["id"]
    bad_split = await client.post(
        f"/v1/admin/attestation-disputes/{dispute_id}/resolve",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "resolution_type": "split",
            "release_amount": "200.00",
            "refund_amount": "50.00",
            "resolution_notes": "Amounts do not match the attestation fee.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )
    resolved = await client.post(
        f"/v1/admin/attestation-disputes/{dispute_id}/resolve",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "resolution_type": "split",
            "release_amount": "180.00",
            "refund_amount": "120.00",
            "resolution_notes": "Report partially accepted after review.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )
    double_resolve = await client.post(
        f"/v1/admin/attestation-disputes/{dispute_id}/resolve",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "resolution_type": "release",
            "resolution_notes": "Duplicate resolution should be blocked.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        dispute = await session.get(AttestationDispute, UUID(dispute_id))
        escrow = await session.get(Escrow, escrow_id)
        transactions = (
            (
                await session.execute(
                    select(Transaction).where(
                        Transaction.ref_id == attestation_id,
                        Transaction.ref_type == "attestation",
                    )
                )
            )
            .scalars()
            .all()
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_dispute_resolved",
                AuditLog.target_id == UUID(dispute_id),
            )
        )

    app.dependency_overrides.pop(get_redis, None)

    assert raised.status_code == 201
    assert bad_split.status_code == 422
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_type"] == "split"
    assert double_resolve.status_code == 409
    assert attestation is not None
    assert attestation.status == "closed"
    assert attestation.closed_at is not None
    assert dispute is not None
    assert dispute.status == "resolved"
    assert dispute.release_amount == Decimal("180.00")
    assert dispute.refund_amount == Decimal("120.00")
    assert escrow is not None
    assert escrow.status == "released"
    assert escrow.released_by == admin_id
    assert sorted(
        (
            transaction.id == transaction_id,
            transaction.transaction_type,
            transaction.amount,
            transaction.status,
        )
        for transaction in transactions
    ) == sorted(
        [
            (True, "attestation_fee", Decimal("300.00"), "refunded"),
            (False, "attestation_fee", Decimal("180.00"), "completed"),
            (False, "refund", Decimal("120.00"), "refunded"),
        ]
    )
    assert refund_calls == [
        {
            "payment_intent_id": next(
                transaction.provider_ref
                for transaction in transactions
                if transaction.id == transaction_id
            ),
            "amount": Decimal("120.00"),
            "currency": "USD",
            "idempotency_key": f"escrow_split_refund:{escrow_id}",
        }
    ]
    assert audit is not None
    assert [call["notification_type"] for call in notification_calls] == [
        "attestation_disputed",
        "attestation_dispute_resolved",
        "attestation_dispute_resolved",
    ]
    assert {call["user_id"] for call in notification_calls[1:]} == {
        str(requestor_id),
        str(attestor_id),
    }


async def test_admin_manually_assigns_needs_admin_attestation(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Admin can manually assign a needs-admin Attestation to an approved Attestor."""
    del migrated_database, matching_context
    fake_redis = FakeRedis()

    async def override_redis() -> FakeRedis:
        """Return Redis test double for admin TOTP verification."""
        return fake_redis

    app.dependency_overrides[get_redis] = override_redis
    requestor_id = await create_user(
        "manual-assign-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "manual-assign-attestor@auracles.space",
        ["attestor"],
    )
    await create_attestor_profile(
        attestor_id,
        specializations=["healthcare"],
        jurisdictions=["US"],
    )
    admin_id, totp_secret = await create_admin_user()
    attestation_id, transaction_id, _ = await create_needs_admin_attestation(
        requestor_id
    )

    response = await client.post(
        f"/v1/admin/attestations/{attestation_id}/assign",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "attestor_id": str(attestor_id),
            "reason": "Manual assignment after cohort exhaustion.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        transaction = await session.get(Transaction, transaction_id)
        offer = await session.scalar(
            select(AttestationOffer).where(
                AttestationOffer.attestation_id == attestation_id,
                AttestationOffer.attestor_id == attestor_id,
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_accepted",
                AuditLog.target_id == attestation_id,
            )
        )

    app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["attestor_id"] == str(attestor_id)
    assert attestation is not None
    assert attestation.status == "accepted"
    assert attestation.accepted_at is not None
    assert attestation.completion_due_at is not None
    assert transaction is not None
    assert transaction.payee_id == attestor_id
    assert offer is not None
    assert offer.status == "accepted"
    assert audit is not None


async def test_admin_refunds_needs_admin_attestation(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admin can refund and close a needs-admin Attestation."""
    del migrated_database, matching_context
    fake_redis = FakeRedis()
    refund_calls: list[dict[str, Any]] = []

    async def override_redis() -> FakeRedis:
        """Return Redis test double for admin TOTP verification."""
        return fake_redis

    async def fake_create_refund(
        *,
        payment_intent_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str,
    ) -> FakeStripeRefund:
        """Record the Stripe full refund request."""
        refund_calls.append(
            {
                "payment_intent_id": payment_intent_id,
                "amount": amount,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        return FakeStripeRefund("re_attestation_admin_refund_123")

    app.dependency_overrides[get_redis] = override_redis
    monkeypatch.setattr(dispute_service.stripe, "create_refund", fake_create_refund)
    requestor_id = await create_user(
        "admin-refund-requestor@auracles.space",
        ["operator"],
    )
    admin_id, totp_secret = await create_admin_user()
    attestation_id, transaction_id, escrow_id = await create_needs_admin_attestation(
        requestor_id
    )

    response = await client.post(
        f"/v1/admin/attestations/{attestation_id}/refund",
        headers=auth_headers(admin_id, ["admin"]),
        json={
            "reason": "No eligible Attestor available after cohort exhaustion.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
        },
    )

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        transaction = await session.get(Transaction, transaction_id)
        escrow = await session.get(Escrow, escrow_id)
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_refunded",
                AuditLog.target_id == attestation_id,
            )
        )

    app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert attestation is not None
    assert attestation.status == "closed"
    assert attestation.closed_at is not None
    assert transaction is not None
    assert transaction.status == "refunded"
    assert escrow is not None
    assert escrow.status == "refunded"
    assert refund_calls == [
        {
            "payment_intent_id": transaction.provider_ref,
            "amount": Decimal("300.00"),
            "currency": "USD",
            "idempotency_key": f"attestation_needs_admin_refund:{escrow_id}",
        }
    ]
    assert audit is not None


async def test_escalate_attestation_disputes_moves_stale_open_disputes_under_review(
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Open Attestation disputes older than seven days escalate once."""
    del migrated_database, matching_context
    requestor_id = await create_user(
        "stale-dispute-requestor@auracles.space",
        ["operator"],
    )
    attestor_id = await create_user(
        "stale-dispute-attestor@auracles.space",
        ["attestor"],
    )
    attestation_id, _, _ = await create_report_submitted_attestation(
        requestor_id,
        attestor_id,
    )
    async with async_session_factory() as session:
        async with session.begin():
            dispute = AttestationDispute(
                attestation_id=attestation_id,
                raised_by=requestor_id,
                category="process_violation",
                reason="This old dispute needs admin attention.",
                status="open",
                created_at=datetime.now(UTC) - timedelta(days=8),
            )
            session.add(dispute)
            await session.flush()
            dispute_id = dispute.id

    async with async_session_factory() as session:
        escalated_count = await dispute_service.escalate_attestation_disputes(session)
        second_count = await dispute_service.escalate_attestation_disputes(session)

    async with async_session_factory() as session:
        dispute = await session.get(AttestationDispute, dispute_id)
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "attestation_dispute_escalated",
                AuditLog.target_id == dispute_id,
            )
        )

    assert escalated_count == 1
    assert second_count == 0
    assert dispute is not None
    assert dispute.status == "under_review"
    assert dispute.escalated_at is not None
    assert audit is not None
