"""Integration tests for Stripe webhook ingestion and dispatch."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import async_session_factory, engine
from app.integrations.stripe import StripeProviderError
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
    AttestationUploadSession,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.projects.models import Milestone, Project, Proposal
from app.modules.webhooks import service as webhook_service
from app.modules.webhooks.models import WebhookEvent
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog


class FakeInvoiceTask:
    """Celery task double that records invoice generation requests."""

    def __init__(self) -> None:
        """Initialise the in-memory dispatch log."""
        self.dispatched: list[str] = []

    def delay(self, transaction_id: str) -> None:
        """Record the transaction id that would be sent to Celery."""
        self.dispatched.append(transaction_id)


async def reset_webhook_state() -> None:
    """Remove webhook test data in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(WebhookEvent))
        await session.execute(delete(AuditLog))
        await session.execute(delete(WorkspaceMessage))
        await session.execute(delete(AttestationUploadSession))
        await session.execute(delete(AttestationOffer))
        await session.execute(delete(AttestationDispute))
        await session.execute(delete(Attestation))
        await session.execute(delete(Milestone))
        await session.execute(delete(Escrow))
        await session.execute(delete(License))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(Project))
        await session.execute(delete(Proposal))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def webhook_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset state and install a controllable Stripe verifier double."""
    await engine.dispose()
    await reset_webhook_state()
    fake_invoice_task = FakeInvoiceTask()
    context: dict[str, Any] = {
        "event": None,
        "verified_payloads": [],
        "invoice_task": fake_invoice_task,
    }

    def fake_verify_webhook(
        payload: bytes,
        signature_header: str | None,
    ) -> dict[str, Any]:
        """Record raw body verification and return the configured event."""
        context["verified_payloads"].append(
            {"payload": payload, "signature": signature_header}
        )
        if signature_header == "bad-signature":
            raise StripeProviderError("bad signature")
        event = context["event"]
        if not isinstance(event, dict):
            raise StripeProviderError("missing test event")
        return event

    monkeypatch.setattr(
        webhook_service.stripe,
        "verify_webhook",
        fake_verify_webhook,
    )
    monkeypatch.setattr(
        webhook_service,
        "generate_invoice_pdf",
        fake_invoice_task,
        raising=False,
    )
    try:
        yield context
    finally:
        await reset_webhook_state()
        await engine.dispose()


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create a verified user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash="not-used",
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


async def create_pending_purchase() -> tuple[UUID, UUID, UUID, UUID]:
    """Create a pending purchase transaction that a webhook can complete."""
    contributor_id = await create_user_with_roles(
        "webhook-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "webhook-operator@auracles.space",
        ["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title="Webhook Purchase Framework",
                description="Framework used by Stripe webhook tests.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["stripe", "webhook"],
                price=Decimal("149.00"),
                currency="USD",
                license_types=["single_user", "team", "organizational"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("149.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("149.00"),
                transaction_type="purchase",
                status="pending",
                provider="stripe",
                provider_ref="pi_webhook_123",
                ref_id=framework.id,
                ref_type="framework",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, framework.id, operator_id, contributor_id


async def create_pending_escrow_transaction() -> tuple[UUID, UUID, UUID]:
    """Create a pending milestone funding transaction for escrow webhook tests."""
    operator_id = await create_user_with_roles(
        "escrow-operator@auracles.space",
        ["operator"],
    )
    contributor_id = await create_user_with_roles(
        "escrow-contributor@auracles.space",
        ["contributor"],
    )
    milestone_id = UUID("00000000-0000-4000-8000-000000000001")
    async with async_session_factory() as session:
        async with session.begin():
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("1250.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("1250.00"),
                transaction_type="milestone",
                status="pending",
                provider="stripe",
                provider_ref="pi_escrow_123",
                ref_id=milestone_id,
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, milestone_id, operator_id


async def create_pending_attestation_fee_transaction(
    *,
    email: str = "attestation-escrow-operator@auracles.space",
    provider_ref: str = "pi_attestation_escrow_123",
) -> tuple[UUID, UUID, UUID]:
    """Create a pending Attestation fee transaction for escrow webhook tests."""
    operator_id = await create_user_with_roles(email, ["operator"])
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="operator",
                target_id=operator_id,
                requestor_id=operator_id,
                status="pending_fee",
                requested_specializations=["operations"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("300.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=None,
                amount=Decimal("300.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("300.00"),
                transaction_type="attestation_fee",
                status="pending",
                provider="stripe",
                provider_ref=provider_ref,
                ref_id=attestation.id,
                ref_type="attestation",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, attestation.id, operator_id


async def create_pending_project_milestone_transaction() -> tuple[
    UUID,
    UUID,
    UUID,
    UUID,
]:
    """Create a finalized Project Milestone and pending funding transaction."""
    operator_id = await create_user_with_roles(
        "project-escrow-operator@auracles.space",
        ["operator"],
    )
    contributor_id = await create_user_with_roles(
        "project-escrow-contributor@auracles.space",
        ["contributor"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                operator_id=operator_id,
                title="Webhook Funded Project",
                description="Project used by webhook milestone funding tests.",
                category="operations",
                required_deliverables=[
                    {"name": "Playbook", "description": "Implementation playbook"}
                ],
                budget_min=Decimal("1500.00"),
                budget_max=Decimal("1500.00"),
                currency="USD",
                status="assigned",
                milestone_plan_status="finalized",
                expires_at=datetime.now(UTC),
            )
            session.add(project)
            await session.flush()
            proposal = Proposal(
                project_id=project.id,
                contributor_id=contributor_id,
                scope="I will deliver the project implementation.",
                budget=Decimal("1500.00"),
                currency="USD",
                timeline_days=21,
                deliverables=[{"name": "Playbook", "description": "Playbook"}],
                status="accepted",
                accepted_at=datetime.now(UTC),
            )
            session.add(proposal)
            await session.flush()
            project.accepted_proposal_id = proposal.id
            milestone = Milestone(
                project_id=project.id,
                sequence=1,
                name="Implementation",
                description="Build the project deliverable.",
                budget=Decimal("1500.00"),
                currency="USD",
                status="pending",
            )
            session.add(milestone)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("1500.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("1500.00"),
                transaction_type="milestone",
                status="pending",
                provider="stripe",
                provider_ref="pi_project_escrow_123",
                ref_id=milestone.id,
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            return transaction.id, project.id, milestone.id, operator_id


def payment_intent_event(
    event_id: str,
    event_type: str,
    *,
    transaction_id: UUID,
    framework_id: UUID,
    license_type: str = "team",
    kind: str = "purchase",
    provider_ref: str = "pi_webhook_123",
    extra_metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a Stripe PaymentIntent event payload for financial webhook tests."""
    metadata = {
        "transaction_id": str(transaction_id),
        "kind": kind,
        "framework_id": str(framework_id),
        "license_type": license_type,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": provider_ref,
                "metadata": metadata,
            }
        },
    }


async def test_stripe_payment_intent_success_creates_license_once(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified purchase webhook completes the transaction and grants access."""
    transaction_id, framework_id, operator_id, _ = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_purchase_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    replay = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        licenses = (
            (
                await session.execute(
                    select(License).where(License.framework_id == framework_id)
                )
            )
            .scalars()
            .all()
        )
        events = (await session.execute(select(WebhookEvent))).scalars().all()
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_completed")
        )

    assert first.status_code == 200
    assert first.json() == {"received": True, "status": "processed"}
    assert replay.status_code == 200
    assert replay.json() == {"received": True, "status": "duplicate"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert len(licenses) == 1
    assert licenses[0].operator_id == operator_id
    assert licenses[0].transaction_id == transaction_id
    assert licenses[0].license_type == "team"
    assert licenses[0].seats_total == 10
    assert len(events) == 1
    assert events[0].provider_event_id == "evt_purchase_success"
    assert events[0].status == "processed"
    assert audit is not None
    assert audit.target_id == transaction_id
    invoice_task: FakeInvoiceTask = webhook_context["invoice_task"]
    assert invoice_task.dispatched == [str(transaction_id)]


async def test_purchase_webhook_fails_duplicate_active_license_transaction(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A second purchase webhook cannot complete without granting a License."""
    (
        first_transaction_id,
        framework_id,
        operator_id,
        contributor_id,
    ) = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_first_purchase_success",
        "payment_intent.succeeded",
        transaction_id=first_transaction_id,
        framework_id=framework_id,
    )
    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        async with session.begin():
            second_transaction = Transaction(
                payer_id=operator_id,
                payee_id=contributor_id,
                amount=Decimal("149.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("149.00"),
                transaction_type="purchase",
                status="pending",
                provider="stripe",
                provider_ref="pi_webhook_duplicate",
                ref_id=framework_id,
                ref_type="framework",
            )
            session.add(second_transaction)
            await session.flush()
            second_transaction_id = second_transaction.id

    webhook_context["event"] = payment_intent_event(
        "evt_duplicate_purchase_success",
        "payment_intent.succeeded",
        transaction_id=second_transaction_id,
        framework_id=framework_id,
        provider_ref="pi_webhook_duplicate",
    )
    duplicate = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        second = await session.get(Transaction, second_transaction_id)
        licenses = (
            (
                await session.execute(
                    select(License).where(License.framework_id == framework_id)
                )
            )
            .scalars()
            .all()
        )
        duplicate_event = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == "evt_duplicate_purchase_success"
            )
        )

    assert first.status_code == 200
    assert duplicate.status_code == 500
    assert second is not None
    assert second.status == "pending"
    assert len(licenses) == 1
    assert duplicate_event is not None
    assert duplicate_event.status == "failed"
    assert duplicate_event.error is not None
    assert "different transaction" in duplicate_event.error


async def test_stripe_payment_intent_success_funds_escrow_once(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified escrow webhook creates one held escrow ledger row."""
    (
        transaction_id,
        milestone_id,
        operator_id,
    ) = await create_pending_escrow_transaction()
    webhook_context["event"] = payment_intent_event(
        "evt_escrow_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=milestone_id,
        kind="escrow",
        provider_ref="pi_escrow_123",
        extra_metadata={
            "release_conditions": (
                '{"kind":"project_milestone","required_event":"operator_approval"}'
            )
        },
    )

    first = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )
    replay = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        escrows = (await session.execute(select(Escrow))).scalars().all()
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "escrow_funded")
        )

    assert first.status_code == 200
    assert first.json() == {"received": True, "status": "processed"}
    assert replay.status_code == 200
    assert replay.json() == {"received": True, "status": "duplicate"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert len(escrows) == 1
    assert escrows[0].ref_id == milestone_id
    assert escrows[0].ref_type == "project_milestone"
    assert escrows[0].transaction_id == transaction_id
    assert escrows[0].status == "held"
    assert escrows[0].release_conditions["required_event"] == "operator_approval"
    assert audit is not None
    assert audit.actor_id == operator_id


async def test_stripe_attestation_fee_success_holds_escrow_and_starts_matching(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified Attestation fee webhook holds escrow and starts matching."""
    (
        transaction_id,
        attestation_id,
        operator_id,
    ) = await create_pending_attestation_fee_transaction()
    webhook_context["event"] = payment_intent_event(
        "evt_attestation_escrow_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=attestation_id,
        kind="escrow",
        provider_ref="pi_attestation_escrow_123",
        extra_metadata={
            "attestation_id": str(attestation_id),
            "release_conditions": (
                "{"
                '"kind":"attestation",'
                f'"attestation_id":"{attestation_id}",'
                f'"requestor_user_id":"{operator_id}"'
                "}"
            ),
        },
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        attestation = await session.get(Attestation, attestation_id)
        escrow = await session.scalar(select(Escrow))
        funded_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "attestation_fee_funded")
        )
        needs_admin_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "attestation_needs_admin")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert escrow is not None
    assert escrow.ref_id == attestation_id
    assert escrow.ref_type == "attestation"
    assert escrow.status == "held"
    assert attestation is not None
    assert attestation.status == "needs_admin"
    assert attestation.escrow_id == escrow.id
    assert funded_audit is not None
    assert funded_audit.actor_id == operator_id
    assert needs_admin_audit is not None


async def test_stripe_attestation_fee_failure_or_cancel_cancels_request(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Failed or cancelled Attestation fee webhooks cancel the request."""
    (
        failed_transaction_id,
        failed_attestation_id,
        _,
    ) = await create_pending_attestation_fee_transaction(
        email="attestation-failed-operator@auracles.space",
        provider_ref="pi_attestation_failed_123",
    )
    webhook_context["event"] = payment_intent_event(
        "evt_attestation_escrow_failed",
        "payment_intent.payment_failed",
        transaction_id=failed_transaction_id,
        framework_id=failed_attestation_id,
        kind="escrow",
        provider_ref="pi_attestation_failed_123",
        extra_metadata={"attestation_id": str(failed_attestation_id)},
    )

    failed = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    (
        cancelled_transaction_id,
        cancelled_attestation_id,
        _,
    ) = await create_pending_attestation_fee_transaction(
        email="attestation-cancelled-operator@auracles.space",
        provider_ref="pi_attestation_cancelled_123",
    )
    webhook_context["event"] = payment_intent_event(
        "evt_attestation_escrow_cancelled",
        "payment_intent.canceled",
        transaction_id=cancelled_transaction_id,
        framework_id=cancelled_attestation_id,
        kind="escrow",
        provider_ref="pi_attestation_cancelled_123",
        extra_metadata={"attestation_id": str(cancelled_attestation_id)},
    )

    cancelled = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        failed_transaction = await session.get(Transaction, failed_transaction_id)
        failed_attestation = await session.get(Attestation, failed_attestation_id)
        cancelled_transaction = await session.get(
            Transaction,
            cancelled_transaction_id,
        )
        cancelled_attestation = await session.get(
            Attestation,
            cancelled_attestation_id,
        )
        audits = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "attestation_fee_failed")
            )
        ).scalars().all()
        purchase_failed_audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_failed")
        )

    assert failed.status_code == 200
    assert failed.json() == {"received": True, "status": "processed"}
    assert cancelled.status_code == 200
    assert cancelled.json() == {"received": True, "status": "processed"}
    assert failed_transaction is not None
    assert failed_transaction.status == "failed"
    assert failed_attestation is not None
    assert failed_attestation.status == "cancelled"
    assert cancelled_transaction is not None
    assert cancelled_transaction.status == "failed"
    assert cancelled_attestation is not None
    assert cancelled_attestation.status == "cancelled"
    assert len(audits) == 2
    assert purchase_failed_audit is None


async def test_stripe_escrow_webhook_marks_project_milestone_funded(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Project Milestone escrow success moves the workspace into funded state."""
    (
        transaction_id,
        project_id,
        milestone_id,
        operator_id,
    ) = await create_pending_project_milestone_transaction()
    webhook_context["event"] = payment_intent_event(
        "evt_project_escrow_success",
        "payment_intent.succeeded",
        transaction_id=transaction_id,
        framework_id=milestone_id,
        kind="escrow",
        provider_ref="pi_project_escrow_123",
        extra_metadata={
            "project_id": str(project_id),
            "milestone_id": str(milestone_id),
            "release_conditions": (
                "{"
                '"kind":"project_milestone",'
                f'"project_id":"{project_id}",'
                f'"milestone_id":"{milestone_id}",'
                f'"approver_user_id":"{operator_id}"'
                "}"
            ),
        },
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        project = await session.get(Project, project_id)
        milestone = await session.get(Milestone, milestone_id)
        escrow = await session.scalar(select(Escrow))
        message = await session.scalar(select(WorkspaceMessage))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "milestone_funded")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert transaction is not None
    assert transaction.status == "completed"
    assert escrow is not None
    assert project is not None
    assert project.status == "in_progress"
    assert milestone is not None
    assert milestone.status == "funded"
    assert milestone.funded_at is not None
    assert milestone.escrow_id == escrow.id
    assert message is not None
    assert message.system_event == "milestone_funded"
    assert audit is not None
    assert audit.actor_id == operator_id


async def test_stripe_webhook_rejects_bad_signature_before_event_storage(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """Invalid signatures return 400 and do not create webhook event rows."""
    webhook_context["event"] = {"id": "evt_bad", "type": "payment_intent.succeeded"}

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "bad-signature"},
    )

    async with async_session_factory() as session:
        event = await session.scalar(select(WebhookEvent))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "webhook_signature_invalid")
        )

    assert response.status_code == 400
    assert event is None
    assert audit is not None
    assert audit.metadata_["provider"] == "stripe"


async def test_stripe_payment_intent_failure_marks_purchase_failed(
    client: AsyncClient,
    webhook_context: dict[str, Any],
) -> None:
    """A verified payment failure webhook marks the local purchase failed."""
    transaction_id, framework_id, _, _ = await create_pending_purchase()
    webhook_context["event"] = payment_intent_event(
        "evt_purchase_failed",
        "payment_intent.payment_failed",
        transaction_id=transaction_id,
        framework_id=framework_id,
    )

    response = await client.post(
        "/v1/webhooks/stripe",
        content=b'{"raw":true}',
        headers={"Stripe-Signature": "valid-signature"},
    )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        license_row = await session.scalar(select(License))
        event = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == "evt_purchase_failed"
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "purchase_failed")
        )

    assert response.status_code == 200
    assert response.json() == {"received": True, "status": "processed"}
    assert transaction is not None
    assert transaction.status == "failed"
    assert license_row is None
    assert event is not None
    assert event.status == "processed"
    assert audit is not None
    assert audit.target_id == transaction_id
