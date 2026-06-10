"""Integration tests for Attestation matching and cohort offer handling."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation import matching_service, release_service
from app.modules.attestation import report as report_service
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
                "attestation_dispute_window_days": "14",
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
            attestation.completion_due_at = current_time - timedelta(hours=1)
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

    current_time = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            attestation = await session.get(Attestation, attestation_id)
            transaction = await session.get(Transaction, transaction_id)
            assert attestation is not None
            assert transaction is not None
            attestation.status = "accepted"
            attestation.attestor_id = attestor_id
            attestation.accepted_at = current_time
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
            "summary": "The reviewed operator evidence supports approval.",
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
            "summary": "The reviewed operator evidence supports approval.",
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
    assert report_response.json()["summary"] == (
        "The reviewed operator evidence supports approval."
    )
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

    assert upload_response.status_code == 403
    assert report_response.status_code == 403


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


async def test_requestor_accepts_report_and_releases_attestation_escrow(
    client: AsyncClient,
    migrated_database: None,
    matching_context: dict[str, Any],
) -> None:
    """Requestors can accept a submitted report and close released escrow."""
    del migrated_database, matching_context
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
