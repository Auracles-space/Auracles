"""Webhook ingestion and dispatch services.

Stripe signs the raw request body, so the router passes bytes here before any
JSON parsing. Verified events are stored in `webhook_events` for replay safety,
then dispatched to small handlers that update local financial state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import hash_payout_provider_account_id
from app.integrations import paystack, persona, stripe
from app.integrations.payment_failures import (
    normalize_paystack_failure,
    normalize_stripe_failure,
)
from app.integrations.paystack import PaystackProviderError
from app.integrations.persona import PersonaProviderError
from app.integrations.stripe import StripeProviderError
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.attestation import matching_service
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import Attestation
from app.modules.auth.models import IdentityVerification, User
from app.modules.collections.purchase import confirm_collection_purchase
from app.modules.developer import webhooks_service as developer_webhooks_service
from app.modules.developer.models import (
    DeveloperAccount,
    PartnerCommission,
    PartnerPurchaseAttribution,
)
from app.modules.financials import escrow_service
from app.modules.financials.ledger import record_financial_event
from app.modules.financials.models import Escrow, Payout, PayoutAccount, Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.notifications.service import create_notification
from app.modules.projects import notifications as project_notifications
from app.modules.projects.models import Milestone, Project
from app.modules.webhooks.models import WebhookEvent
from app.modules.webhooks.schemas import WebhookIngestResponse
from app.modules.workspace.models import WorkspaceMessage
from app.workers.tasks.financials import generate_invoice_pdf


class WebhookProcessingError(RuntimeError):
    """Raised when a verified provider event cannot be safely applied."""


def _normalise_money(amount: Decimal) -> Decimal:
    """Return a two-decimal money value for webhook-created ledger rows."""
    return amount.quantize(Decimal("0.01"))


async def _record_transaction_transition(
    db: AsyncSession,
    *,
    transaction: Transaction,
    event_type: str,
    from_status: str,
    failure_object: dict[str, Any] | None = None,
) -> None:
    """Append a transaction state change to the financial ledger.

    Called after the status has already been mutated, so `transaction.status`
    is the destination and `from_status` must be captured by the caller before
    the change.

    Args:
        db: Session inside the webhook's transaction, so the ledger row commits
            atomically with the state change it describes.
        transaction: The transaction whose status just changed.
        event_type: snake_case event name, e.g. `purchase_failed`.
        from_status: Status held before the mutation.
        failure_object: The provider's charge object for failure events, whose
            error fields are normalized into a provider-neutral reason. None
            for successful transitions.
    """
    # The normalizer is chosen by the transaction's own provider, not the
    # caller's: Stripe reports a coded error object while Paystack reports
    # prose, and reading either shape with the wrong parser yields "unknown".
    failure = None
    if failure_object:
        failure = (
            normalize_paystack_failure(failure_object)
            if transaction.provider == "paystack"
            else normalize_stripe_failure(failure_object)
        )
    metadata: dict[str, Any] = {}
    if failure is not None and failure.provider_code is not None:
        # Keep the provider's own code alongside the normalized one so a cause
        # we have not mapped yet is still diagnosable from the ledger.
        metadata["provider_code"] = failure.provider_code
    await record_financial_event(
        db,
        entity_type="transaction",
        entity_id=transaction.id,
        event_type=event_type,
        from_status=from_status,
        to_status=transaction.status,
        amount=transaction.amount,
        currency=transaction.currency,
        provider=transaction.provider,
        provider_ref=transaction.provider_ref,
        reason_code=failure.code if failure else None,
        reason_message=failure.message if failure else None,
        actor_id=transaction.payer_id,
        metadata=metadata,
    )


def _event_object(event: dict[str, Any]) -> dict[str, Any]:
    """Return `data.object` from a Stripe event or an empty object."""
    data = event.get("data")
    if not isinstance(data, dict):
        return {}
    event_object = data.get("object")
    return event_object if isinstance(event_object, dict) else {}


def _event_metadata(event: dict[str, Any]) -> dict[str, str]:
    """Return string-only Stripe metadata from a webhook event object."""
    metadata = _event_object(event).get("metadata")
    if not isinstance(metadata, dict):
        return {}
    return {str(key): str(value) for key, value in metadata.items()}


def _event_object_id(event: dict[str, Any]) -> str | None:
    """Return the provider object id carried by a Stripe event."""
    object_id = _event_object(event).get("id")
    return object_id if isinstance(object_id, str) else None


def _required_event_field(event: dict[str, Any], field: str) -> str:
    """Read a required top-level Stripe event string field."""
    value = event.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stripe event missing {field}.",
        )
    return value


def _purchase_transaction_id(event: dict[str, Any]) -> UUID:
    """Parse the Auracles transaction id from Stripe metadata."""
    raw_transaction_id = _event_metadata(event).get("transaction_id")
    if raw_transaction_id is None:
        raise WebhookProcessingError("purchase event missing transaction_id")
    try:
        return UUID(raw_transaction_id)
    except ValueError as exc:
        raise WebhookProcessingError(
            "purchase event transaction_id is invalid"
        ) from exc


def _license_seats_total(license_type: str) -> int | None:
    """Return default seat allocation for purchased license types."""
    if license_type == "single_user":
        return 1
    if license_type == "team":
        return 10
    return None


def _escrow_release_conditions(event: dict[str, Any]) -> dict[str, Any]:
    """Parse optional escrow release conditions from Stripe metadata."""
    raw_conditions = _event_metadata(event).get("release_conditions")
    if raw_conditions is None:
        return {}
    try:
        parsed = json.loads(raw_conditions)
    except json.JSONDecodeError as exc:
        raise WebhookProcessingError(
            "escrow event release_conditions is invalid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise WebhookProcessingError(
            "escrow event release_conditions must be an object"
        )
    return parsed


async def _audit_invalid_signature(db: AsyncSession, *, provider: str) -> None:
    """Persist a minimal audit row for rejected provider signatures."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=None,
            action="webhook_signature_invalid",
            target_type="webhook",
            metadata={"provider": provider},
        )


async def _ensure_verified_event_row(
    db: AsyncSession,
    *,
    provider: str,
    event_id: str,
    event_type: str,
    payload_hash: str,
) -> None:
    """Persist a verified provider event row once, ignoring concurrent inserts.

    The row is the durable idempotency anchor. A row that already exists is
    left untouched here; whether it represents a replay or a retry of a failed
    dispatch is decided under a row lock during dispatch so transient failures
    can be safely reprocessed instead of silently dropped.
    """
    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            db.add(
                WebhookEvent(
                    provider=provider,
                    provider_event_id=event_id,
                    event_type=event_type,
                    status="received",
                    payload_hash=payload_hash,
                )
            )
    except IntegrityError:
        await db.rollback()


async def _mark_event_status(
    db: AsyncSession,
    *,
    event_id: str,
    status_: str,
    error: str | None = None,
    provider: str = "stripe",
) -> None:
    """Update durable webhook event processing status."""
    event_row = await db.scalar(
        select(WebhookEvent).where(
            WebhookEvent.provider == provider,
            WebhookEvent.provider_event_id == event_id,
        )
    )
    if event_row is None:
        raise WebhookProcessingError("webhook event row missing during dispatch")
    event_row.status = status_
    event_row.error = error
    if status_ in {"processed", "failed"}:
        event_row.processed_at = datetime.now(UTC)


async def _handle_purchase_succeeded(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    provider: str = "stripe",
) -> tuple[UUID | None, list[Callable[[], None]]]:
    """Mark a purchase complete and grant its Framework License.

    Args:
        db: Session inside the webhook's transaction.
        event: Provider event in the internal Stripe-shaped envelope.
        provider: Rail that delivered the event. Checked against the
            transaction so a Paystack event can never settle a charge booked
            to Stripe (or the reverse) on the strength of forgeable metadata.
    """
    transaction_id = _purchase_transaction_id(event)
    charge_ref = _event_object_id(event)
    metadata = _event_metadata(event)
    license_type = metadata.get("license_type")
    if license_type is None:
        raise WebhookProcessingError("purchase event missing license_type")

    transaction = await db.get(Transaction, transaction_id)
    if transaction is None:
        raise WebhookProcessingError("purchase transaction not found")
    # Captured before mutation so the ledger can record the transition.
    previous_status = transaction.status
    if transaction.transaction_type != "purchase":
        raise WebhookProcessingError("transaction is not a purchase")
    if transaction.provider != provider:
        raise WebhookProcessingError("transaction provider mismatch")
    if transaction.provider_ref and transaction.provider_ref != charge_ref:
        raise WebhookProcessingError("provider charge reference mismatch")
    if transaction.ref_id is None:
        raise WebhookProcessingError("purchase transaction missing framework ref")

    framework = await db.get(Framework, transaction.ref_id)
    if framework is None:
        raise WebhookProcessingError("purchase framework not found")
    if license_type not in framework.license_types:
        raise WebhookProcessingError("license type is unavailable")

    # Org-payer purchases must branch before any operator_id-keyed lookup:
    # when payer_id is NULL (org-paid), `operator_id == transaction.payer_id`
    # compiles to `operator_id IS NULL`, which would match an unrelated
    # individual-less License row instead of resolving the org's own License.
    if transaction.payer_org_id is not None:
        existing_license = await db.scalar(
            select(License).where(
                License.framework_id == framework.id,
                License.licensee_org_id == transaction.payer_org_id,
            )
        )
        if existing_license is None:
            existing_license = License(
                framework_id=framework.id,
                operator_id=None,
                licensee_org_id=transaction.payer_org_id,
                transaction_id=transaction.id,
                license_type=license_type,
                status="active",
                version_at_grant=framework.version,
                seats_used=1,
                seats_total=_license_seats_total(license_type),
            )
            db.add(existing_license)
            await db.flush()
        elif existing_license.transaction_id == transaction.id:
            pass
        elif existing_license.status != "active":
            existing_license.transaction_id = transaction.id
            existing_license.license_type = license_type
            existing_license.status = "active"
            existing_license.version_at_grant = framework.version
            existing_license.seats_used = 1
            existing_license.seats_total = _license_seats_total(license_type)
        else:
            raise WebhookProcessingError(
                "framework already licensed by a different transaction"
            )

        transaction.status = "completed"
        # The initiating org admin is already audited at purchase_initiated;
        # this completion event has no individual actor.
        await write_audit(
            db=db,
            actor_id=None,
            action="purchase_completed",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "provider": provider,
                "framework_id": str(framework.id),
                "license_id": str(existing_license.id),
                "license_type": license_type,
                "payer_org_id": str(transaction.payer_org_id),
            },
        )
    else:
        existing_license = await db.scalar(
            select(License).where(
                License.framework_id == framework.id,
                License.operator_id == transaction.payer_id,
            )
        )
        if existing_license is None:
            existing_license = License(
                framework_id=framework.id,
                operator_id=transaction.payer_id,
                transaction_id=transaction.id,
                license_type=license_type,
                status="active",
                version_at_grant=framework.version,
                seats_used=1,
                seats_total=_license_seats_total(license_type),
            )
            db.add(existing_license)
            await db.flush()
        elif existing_license.transaction_id == transaction.id:
            pass
        elif existing_license.status != "active":
            existing_license.transaction_id = transaction.id
            existing_license.license_type = license_type
            existing_license.status = "active"
            existing_license.version_at_grant = framework.version
            existing_license.seats_used = 1
            existing_license.seats_total = _license_seats_total(license_type)
        else:
            raise WebhookProcessingError(
                "framework already licensed by a different transaction"
            )

        transaction.status = "completed"
        await write_audit(
            db=db,
            actor_id=transaction.payer_id,
            action="purchase_completed",
            target_type="transaction",
            target_id=transaction.id,
            metadata={
                "provider": provider,
                "framework_id": str(framework.id),
                "license_id": str(existing_license.id),
                "license_type": license_type,
            },
        )

    # Recorded once for both the org and individual branches above, which
    # converge on the same completed status.
    await _record_transaction_transition(
        db,
        transaction=transaction,
        event_type="purchase_completed",
        from_status=previous_status,
    )

    after_commit_work = await _create_partner_commission_if_attributed(
        db=db,
        transaction=transaction,
        framework_id=framework.id,
    )
    # Only individual purchases queue an invoice PDF: the invoice worker keys on
    # ``payer_id`` and no org purchase-invoice is issued (unspecced), so an org
    # (NULL-payer) row would fail the worker permanently. Skip its dispatch.
    invoice_transaction_id = (
        None if transaction.payer_org_id is not None else transaction.id
    )
    return invoice_transaction_id, after_commit_work


async def _create_partner_commission_if_attributed(
    *,
    db: AsyncSession,
    transaction: Transaction,
    framework_id: UUID,
) -> list[Callable[[], None]]:
    """Create a pending partner commission when a purchase has attribution."""
    attribution = await db.scalar(
        select(PartnerPurchaseAttribution).where(
            PartnerPurchaseAttribution.transaction_id == transaction.id
        )
    )
    if attribution is None:
        return []

    existing_commission = await db.scalar(
        select(PartnerCommission).where(
            PartnerCommission.transaction_id == transaction.id
        )
    )
    if existing_commission is not None:
        return []

    developer_account = await db.get(
        DeveloperAccount,
        attribution.developer_account_id,
    )
    if developer_account is None:
        raise WebhookProcessingError("partner attribution missing developer account")

    commission_amount = _normalise_money(transaction.amount * attribution.tier_rate)
    commission = PartnerCommission(
        api_key_id=attribution.api_key_id,
        developer_account_id=attribution.developer_account_id,
        transaction_id=transaction.id,
        framework_id=framework_id,
        sale_amount=transaction.amount,
        currency=transaction.currency,
        tier_at_sale=attribution.tier_at_sale,
        tier_rate=attribution.tier_rate,
        commission_amount=commission_amount,
        status="pending",
    )
    db.add(commission)
    await db.flush()
    await write_audit(
        db=db,
        actor_id=developer_account.user_id,
        action="partner_commission_created",
        target_type="partner_commission",
        target_id=commission.id,
        metadata={
            "api_key_id": str(attribution.api_key_id),
            "transaction_id": str(transaction.id),
            "framework_id": str(framework_id),
            "sale_amount": str(transaction.amount),
            "tier_rate": str(attribution.tier_rate),
            "commission_amount": str(commission_amount),
        },
    )
    delivery_ids = await developer_webhooks_service.enqueue_partner_webhook_deliveries(
        db,
        developer_account_id=developer_account.id,
        event_type="purchase.confirmed",
        payload={
            "event": "purchase.confirmed",
            "commission_id": str(commission.id),
            "transaction_id": str(transaction.id),
            "framework_id": str(framework_id),
            "sale_amount": str(transaction.amount),
            "currency": transaction.currency,
            "commission_amount": str(commission_amount),
            "status": commission.status,
        },
    )
    if not delivery_ids:
        return []

    def _queue_deliveries() -> None:
        """After-commit hook: enqueue the Partner webhook deliveries."""
        developer_webhooks_service.queue_partner_webhook_deliveries(delivery_ids)

    return [_queue_deliveries]


def _queue_purchase_invoice_generation(transaction_id: UUID) -> None:
    """Queue invoice PDF generation after purchase state is committed."""
    try:
        generate_invoice_pdf.delay(str(transaction_id))
    except Exception as exc:
        logger.bind(
            module="webhooks",
            action="queue_purchase_invoice_generation",
            transaction_id=transaction_id,
        ).error("invoice_generation_dispatch_failed", error=str(exc))


async def _handle_purchase_failed(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    provider: str = "stripe",
    reason: str = "payment_intent.payment_failed",
) -> None:
    """Mark a purchase transaction failed after a provider payment failure.

    Args:
        db: Session inside the webhook's transaction.
        event: Provider event in the internal Stripe-shaped envelope.
        provider: Rail that delivered the event, checked against the
            transaction before any state change.
        reason: Provider event name recorded on the audit entry.
    """
    transaction_id = _purchase_transaction_id(event)
    charge_ref = _event_object_id(event)
    transaction = await db.get(Transaction, transaction_id)
    if transaction is None:
        raise WebhookProcessingError("purchase transaction not found")
    if transaction.provider != provider:
        raise WebhookProcessingError("transaction provider mismatch")
    if transaction.provider_ref and transaction.provider_ref != charge_ref:
        raise WebhookProcessingError("provider charge reference mismatch")
    previous_status = transaction.status
    transaction.status = "failed"
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="purchase_failed",
        target_type="transaction",
        target_id=transaction.id,
        metadata={"provider": provider, "reason": reason},
    )
    await _record_transaction_transition(
        db,
        transaction=transaction,
        event_type="purchase_failed",
        from_status=previous_status,
        failure_object=_event_object(event),
    )


async def _handle_escrow_failed(
    db: AsyncSession,
    event: dict[str, Any],
) -> None:
    """Mark an escrow funding transaction failed after provider failure/cancel."""
    transaction_id = _purchase_transaction_id(event)
    payment_intent_id = _event_object_id(event)
    event_type = _required_event_field(event, "type")
    transaction = await db.get(Transaction, transaction_id)
    if transaction is None:
        raise WebhookProcessingError("escrow transaction not found")
    if transaction.provider != "stripe":
        raise WebhookProcessingError("escrow transaction provider mismatch")
    if transaction.provider_ref and transaction.provider_ref != payment_intent_id:
        raise WebhookProcessingError("payment intent id mismatch")

    if transaction.ref_type == "attestation":
        await _mark_attestation_fee_failed(
            db=db,
            transaction=transaction,
            reason=event_type,
            failure_object=_event_object(event),
        )
        return

    previous_status = transaction.status
    transaction.status = "failed"
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="escrow_funding_failed",
        target_type="transaction",
        target_id=transaction.id,
        metadata={"provider": "stripe", "reason": event_type},
    )
    await _record_transaction_transition(
        db,
        transaction=transaction,
        event_type="escrow_funding_failed",
        from_status=previous_status,
        failure_object=_event_object(event),
    )


async def _mark_attestation_fee_failed(
    *,
    db: AsyncSession,
    transaction: Transaction,
    reason: str,
    failure_object: dict[str, Any] | None = None,
) -> None:
    """Cancel an Attestation when fee escrow funding fails before hold.

    Args:
        db: Session inside the webhook's transaction.
        transaction: The attestation-fee transaction being failed.
        reason: Stripe event type that triggered the failure.
        failure_object: Stripe `data.object`, whose error fields are normalized
            into the ledger's provider-neutral reason.
    """
    if transaction.transaction_type != "attestation_fee" or transaction.ref_id is None:
        raise WebhookProcessingError("attestation fee transaction mismatch")
    attestation = await db.scalar(
        select(Attestation)
        .where(Attestation.id == transaction.ref_id)
        .with_for_update()
    )
    if attestation is None:
        raise WebhookProcessingError("attestation not found for funding failure")
    if transaction.status == "failed" and attestation.status == "cancelled":
        return
    if attestation.status != "pending_fee":
        raise WebhookProcessingError("attestation is not pending fee funding")

    previous_status = transaction.status
    transaction.status = "failed"
    attestation.status = "cancelled"
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="attestation_fee_failed",
        target_type="attestation",
        target_id=attestation.id,
        metadata={
            "provider": "stripe",
            "reason": reason,
            "transaction_id": str(transaction.id),
        },
    )
    await _record_transaction_transition(
        db,
        transaction=transaction,
        event_type="attestation_fee_failed",
        from_status=previous_status,
        failure_object=failure_object,
    )


async def _handle_escrow_succeeded(
    db: AsyncSession,
    event: dict[str, Any],
) -> list[Callable[[], None]]:
    """Mark an escrow funding transaction complete and hold its funds."""
    transaction_id = _purchase_transaction_id(event)
    payment_intent_id = _event_object_id(event)
    transaction = await db.get(Transaction, transaction_id)
    if transaction is None:
        raise WebhookProcessingError("escrow transaction not found")
    if transaction.provider != "stripe":
        raise WebhookProcessingError("escrow transaction provider mismatch")
    if transaction.provider_ref and transaction.provider_ref != payment_intent_id:
        raise WebhookProcessingError("payment intent id mismatch")
    escrow = await escrow_service.hold(
        db,
        transaction_id=transaction_id,
        release_conditions=_escrow_release_conditions(event),
    )
    after_commit_notifications = await _mark_attestation_fee_funded(
        db=db,
        transaction=transaction,
        escrow=escrow,
    )
    await _mark_project_milestone_funded(
        db=db,
        transaction=transaction,
        escrow=escrow,
    )
    return after_commit_notifications


async def _mark_attestation_fee_funded(
    *,
    db: AsyncSession,
    transaction: Transaction,
    escrow: Escrow,
) -> list[Callable[[], None]]:
    """Apply Attestation state after a fee escrow hold succeeds."""
    if transaction.ref_type != "attestation" or transaction.ref_id is None:
        return []
    if transaction.transaction_type != "attestation_fee":
        raise WebhookProcessingError("attestation escrow transaction type mismatch")

    attestation = await db.scalar(
        select(Attestation)
        .where(Attestation.id == transaction.ref_id)
        .with_for_update()
    )
    if attestation is None:
        raise WebhookProcessingError("attestation not found for escrow funding")
    if attestation.status == "matching" and attestation.escrow_id == escrow.id:
        return []
    if attestation.status != "pending_fee":
        raise WebhookProcessingError("attestation is not pending fee funding")

    attestation.status = "matching"
    attestation.escrow_id = escrow.id
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="attestation_fee_funded",
        target_type="attestation",
        target_id=attestation.id,
        metadata={
            "escrow_id": str(escrow.id),
            "transaction_id": str(transaction.id),
        },
    )
    offers = await matching_service.offer_next_cohort(db, attestation_id=attestation.id)
    offer_recipients = await matching_service.resolve_offer_recipients(db, offers)
    callbacks: list[Callable[[], None]] = [
        lambda: attestation_notifications.notify_fee_funded(attestation),
        lambda: matching_service.dispatch_offer_notifications(
            attestation, offers, offer_recipients
        ),
        lambda: (
            attestation_notifications.notify_needs_admin(attestation)
            if attestation.status == "needs_admin"
            else None
        ),
    ]
    return callbacks


async def _mark_project_milestone_funded(
    *,
    db: AsyncSession,
    transaction: Transaction,
    escrow: Escrow,
) -> None:
    """Apply project workspace state after a project Milestone escrow hold."""
    if transaction.ref_type != "project_milestone" or transaction.ref_id is None:
        return

    milestone = await db.scalar(
        select(Milestone).where(Milestone.id == transaction.ref_id).with_for_update()
    )
    if milestone is None:
        # Phase 3 tests and future escrow consumers can fund escrow refs before
        # the Projects module owns the referenced row.
        return
    if milestone.status == "funded" and milestone.escrow_id == escrow.id:
        return
    if milestone.status != "pending":
        raise WebhookProcessingError("project milestone is not pending funding")

    project = await db.scalar(
        select(Project).where(Project.id == milestone.project_id).with_for_update()
    )
    if project is None:
        raise WebhookProcessingError("project milestone parent project not found")

    now = datetime.now(UTC)
    milestone.status = "funded"
    milestone.funded_at = now
    milestone.escrow_id = escrow.id
    if project.status == "assigned":
        project.status = "in_progress"
    db.add(
        WorkspaceMessage(
            project_id=project.id,
            sender_id=None,
            system_event="milestone_funded",
            system_payload={
                "milestone_id": str(milestone.id),
                "escrow_id": str(escrow.id),
                "transaction_id": str(transaction.id),
            },
        )
    )
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="milestone_funded",
        target_type="milestone",
        target_id=milestone.id,
        metadata={
            "project_id": str(project.id),
            "escrow_id": str(escrow.id),
            "transaction_id": str(transaction.id),
        },
    )
    # Resolve the staffed workspace contributor even when the org, not the
    # member, is the milestone's financial beneficiary.
    # Local imports keep the projects -> webhooks dependency one-way.
    from app.modules.projects.models import Proposal
    from app.modules.projects.workspace import workspace_contributor_user_id

    proposal = await db.scalar(
        select(Proposal)
        .where(Proposal.id == project.accepted_proposal_id)
        .with_for_update()
    )
    if proposal is None:
        raise WebhookProcessingError("project milestone accepted proposal not found")

    contributor_user_id = await workspace_contributor_user_id(db, proposal=proposal)
    if contributor_user_id is None:
        raise WebhookProcessingError(
            "project milestone funded without a staffed workspace contributor"
        )
    project_notifications.notify_milestone_funded(
        contributor_id=contributor_user_id,
        project_id=project.id,
        milestone_id=milestone.id,
    )


async def _connected_payout_account(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    action: str,
) -> PayoutAccount | None:
    """Resolve the PayoutAccount a connected-account payout event refers to.

    Connected-account events name the account at the event's top level, not in
    the payout object, and the account id is stored encrypted, so the lookup
    goes through the deterministic hash column.

    Args:
        db: Session inside the webhook's transaction.
        event: The verified Stripe event.
        action: Log action tag identifying the calling handler.

    Returns:
        The matching payout account, or None when the account is not ours.

    Raises:
        WebhookProcessingError: If the event carries no connected account id.
    """
    account_id = event.get("account")
    if not isinstance(account_id, str) or not account_id:
        raise WebhookProcessingError(
            f"{event.get('type')} missing connected account id"
        )

    payout_account = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.provider == "stripe",
            PayoutAccount.provider_account_lookup_hash
            == hash_payout_provider_account_id(account_id),
            PayoutAccount.deleted_at.is_(None),
        )
    )
    if payout_account is None:
        # Stripe delivers connected-account events for every account on the
        # platform. Erroring would make it retry an event we do not own.
        logger.bind(module="webhooks", action=action).info(
            "connected_payout_event_for_untracked_account"
        )
    return payout_account


async def _handle_connected_payout_paid(
    db: AsyncSession,
    event: dict[str, Any],
) -> None:
    """Settle the payouts a connected account's bank payout carried.

    This is the only Stripe event on the payout path meaning the contributor's
    bank was funded. `transfer.created` only moves money into their Stripe
    balance, so completing a payout there would tell a contributor they had
    been paid while the money was still at the provider.

    Stripe names the account, not our payout rows, and one bank payout can
    settle several of our transfers at once. Every in-flight payout on the
    account is therefore settled, bounded by the bank payout's own creation
    time: a transfer created after the bank payout left cannot have been in it.
    The bound is what keeps the attribution honest — without it a later
    transfer would be marked paid on the strength of someone else's settlement.

    Args:
        db: Session inside the webhook's transaction.
        event: The verified Stripe event.
    """
    payout_account = await _connected_payout_account(
        db, event, action="connected_payout_paid"
    )
    if payout_account is None:
        return

    event_object = _event_object(event)
    created_raw = event_object.get("created")
    settled_at = (
        datetime.fromtimestamp(created_raw, UTC)
        if isinstance(created_raw, int)
        else datetime.now(UTC)
    )
    payouts = (
        await db.scalars(
            select(Payout).where(
                Payout.payout_account_id == payout_account.id,
                Payout.status == "processing",
                Payout.initiated_at <= settled_at,
            )
        )
    ).all()
    bank_payout_ref = _event_object_id(event)
    completed_at = datetime.now(UTC)
    for payout in payouts:
        payout.status = "completed"
        payout.completed_at = completed_at
        await write_audit(
            db=db,
            actor_id=payout.contributor_id,
            action="payout_completed",
            target_type="payout",
            target_id=payout.id,
            metadata={"provider": "stripe", "settled_by_bank_payout": True},
        )
        await record_financial_event(
            db,
            entity_type="payout",
            entity_id=payout.id,
            event_type="payout_completed",
            from_status="processing",
            to_status="completed",
            amount=payout.amount,
            currency=payout.currency,
            provider="stripe",
            provider_ref=bank_payout_ref,
            actor_id=payout.contributor_id,
            metadata={"transfer_ref": payout.provider_ref}
            if payout.provider_ref
            else {},
        )


async def _handle_connected_payout_failed(
    db: AsyncSession,
    event: dict[str, Any],
) -> list[Callable[[], None]]:
    """Record why a connected account's bank payout failed.

    Stripe emits this for the connected account's own payout to its bank, and
    it is the only event on the payout path carrying a failure code —
    `transfer.reversed`, which undoes our transfer, carries none.

    The event names a connected account, not one of our `payouts` rows, and one
    bank payout can settle several of our transfers, so the failure is recorded
    against the payout account rather than guessing at a single payout. The
    contributor's funds are stranded in their Stripe balance, so admins are
    alerted once the record is durable.

    Args:
        db: Session inside the webhook's transaction.
        event: The verified Stripe event.

    Returns:
        Post-commit callables raising an admin alert, or an empty list when the
        account is not one we track.
    """
    payout_account = await _connected_payout_account(
        db, event, action="connected_payout_failed"
    )
    if payout_account is None:
        return []

    event_object = _event_object(event)
    failure = normalize_stripe_failure(event_object)
    await record_financial_event(
        db,
        entity_type="payout_account",
        entity_id=payout_account.id,
        event_type="connected_payout_failed",
        provider="stripe",
        provider_ref=_event_object_id(event),
        reason_code=failure.code,
        reason_message=failure.message,
        actor_id=payout_account.user_id,
        metadata=(
            {"provider_code": failure.provider_code} if failure.provider_code else {}
        ),
    )

    payout_account_id = payout_account.id
    return [
        lambda: notify_admins_review_pending(
            domain="payout",
            target_id=payout_account_id,
            body=(
                "A contributor's bank payout failed; their funds are held at "
                "the payment provider and need admin investigation."
            ),
            link="/admin/payouts",
        )
    ]


async def _handle_account_updated(db: AsyncSession, event: dict[str, Any]) -> None:
    """Mark a payout account verified when Stripe Connect enables it."""
    event_object = _event_object(event)
    account_id = event_object.get("id")
    if not isinstance(account_id, str):
        raise WebhookProcessingError("account.updated missing account id")
    if not event_object.get("charges_enabled") or not event_object.get(
        "payouts_enabled"
    ):
        return

    payout_account = await db.scalar(
        select(PayoutAccount).where(
            PayoutAccount.provider == "stripe",
            PayoutAccount.provider_account_lookup_hash
            == hash_payout_provider_account_id(account_id),
            PayoutAccount.deleted_at.is_(None),
        )
    )
    if payout_account is None:
        logger.bind(
            module="webhooks",
            action="stripe_account_updated",
        ).warning("payout_account_not_found", provider="stripe")
        return
    if payout_account.verified_at is not None:
        logger.bind(
            module="webhooks",
            action="stripe_account_updated",
            user_id=payout_account.user_id,
        ).info("payout_account_already_verified")
        return
    payout_account.verified_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=payout_account.user_id,
        action="payout_account_verified",
        target_type="payout_account",
        target_id=payout_account.id,
        metadata={"provider": "stripe"},
    )


async def _payout_from_metadata(
    db: AsyncSession,
    event: dict[str, Any],
) -> Payout | None:
    """Return the Payout named by the transfer metadata ``payout_id``, if any."""
    payout_id_raw = _event_metadata(event).get("payout_id")
    if not payout_id_raw:
        return None
    try:
        payout_id = UUID(payout_id_raw)
    except ValueError:
        return None
    return await db.get(Payout, payout_id)


async def _payout_for_transfer(
    db: AsyncSession,
    event: dict[str, Any],
) -> tuple[Payout | None, str]:
    """Resolve the payout a transfer event refers to, backfilling its reference.

    Matches first by stored ``provider_ref`` (the transfer id). When that misses
    — a ``transfer.created`` event can arrive before the worker commits
    ``provider_ref`` — falls back to the ``payout_id`` carried in the transfer
    metadata and backfills the reference.

    Args:
        db: Session inside the webhook's transaction.
        event: The verified Stripe event.

    Returns:
        Tuple of (payout or None for an unknown transfer, transfer id).

    Raises:
        WebhookProcessingError: If the event carries no transfer id.
    """
    transfer_id = _event_object_id(event)
    if transfer_id is None:
        raise WebhookProcessingError("transfer event missing transfer id")
    payout = await db.scalar(select(Payout).where(Payout.provider_ref == transfer_id))
    if payout is None:
        payout = await _payout_from_metadata(db, event)
        if payout is not None and payout.provider_ref is None:
            payout.provider_ref = transfer_id
    return payout, transfer_id


async def _handle_transfer_created(
    db: AsyncSession,
    event: dict[str, Any],
) -> None:
    """Confirm a payout's transfer exists without claiming it has settled.

    A Stripe transfer moves money from the platform balance into the connected
    account's Stripe balance — it is not a bank settlement. Completion belongs
    to `payout.paid` on the connected account; this handler only backfills the
    transfer reference and records the step on the payout's timeline.

    Args:
        db: Session inside the webhook's transaction.
        event: The verified Stripe event.
    """
    payout, transfer_id = await _payout_for_transfer(db, event)
    if payout is None:
        return
    previous_status = payout.status
    # The worker sets `processing` when it creates the transfer, but the event
    # can beat that commit, so treat the transfer's existence as authoritative.
    payout.status = "processing"
    await record_financial_event(
        db,
        entity_type="payout",
        entity_id=payout.id,
        event_type="payout_transfer_created",
        from_status=previous_status,
        to_status="processing",
        amount=payout.amount,
        currency=payout.currency,
        provider="stripe",
        provider_ref=transfer_id,
        actor_id=payout.contributor_id,
    )


async def _handle_transfer_event(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    payout_status: str,
    provider: str = "stripe",
) -> list[Callable[[], None]]:
    """Apply a terminal transfer status to an existing payout row.

    Shared by both rails, which differ in what a terminal transfer means. A
    Stripe transfer only moves money into a connected account's balance, so it
    reaches here solely via `transfer.reversed`; a Paystack transfer goes
    straight to the beneficiary's bank, so its success is genuinely final.

    Unknown transfers no-op. Returns post-commit callables (an admin failure
    alert on a newly failed payout) so the notification only fires once the
    status change is durable.

    Args:
        db: Session inside the webhook's transaction.
        event: The verified event, in the internal envelope shape.
        payout_status: Terminal status to apply to the payout row.
        provider: Rail the event arrived on. Selects the failure normalizer —
            Stripe reports a coded error object while Paystack reports prose,
            and the wrong parser yields "unknown" with no cause to act on.
    """
    payout, transfer_id = await _payout_for_transfer(db, event)
    if payout is None:
        return []
    if payout.status == payout_status:
        return []
    previous_status = payout.status
    payout.status = payout_status
    if payout_status == "completed":
        payout.completed_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=payout.contributor_id,
        action=f"payout_{payout_status}",
        target_type="payout",
        target_id=payout.id,
        metadata={"provider": provider, "transfer_ref": transfer_id[-4:]},
    )
    # The audit row above deliberately keeps only the last four characters of
    # the transfer reference; the ledger carries the cause a failed payout needs.
    failure = None
    if payout_status == "failed":
        failure = (
            normalize_paystack_failure(_event_object(event))
            if provider == "paystack"
            else normalize_stripe_failure(_event_object(event))
        )
    await record_financial_event(
        db,
        entity_type="payout",
        entity_id=payout.id,
        event_type=f"payout_{payout_status}",
        from_status=previous_status,
        to_status=payout_status,
        amount=payout.amount,
        currency=payout.currency,
        provider=provider,
        provider_ref=transfer_id,
        reason_code=failure.code if failure else None,
        reason_message=failure.message if failure else None,
        actor_id=payout.contributor_id,
        metadata=(
            {"provider_code": failure.provider_code}
            if failure and failure.provider_code
            else {}
        ),
    )
    if payout_status != "failed":
        return []
    failed_payout_id = payout.id
    return [
        lambda: notify_admins_review_pending(
            domain="payout",
            target_id=failed_payout_id,
            body="A payout transfer failed and needs admin investigation.",
            link="/admin/payouts",
        )
    ]


async def _dispatch_verified_event(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    event: dict[str, Any],
) -> tuple[str, UUID | None, list[Callable[[], None]]]:
    """Dispatch a verified event and return status plus post-commit work."""
    metadata = _event_metadata(event)
    if event_type == "payment_intent.succeeded" and metadata.get("kind") == "purchase":
        (
            invoice_transaction_id,
            after_commit_notifications,
        ) = await _handle_purchase_succeeded(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", invoice_transaction_id, after_commit_notifications
    if (
        event_type == "payment_intent.succeeded"
        and metadata.get("kind") == "collection"
    ):
        invoice_transaction_id = await confirm_collection_purchase(
            db,
            transaction_id=_purchase_transaction_id(event),
            payment_intent_id=_event_object_id(event),
        )
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", invoice_transaction_id, []
    if event_type == "payment_intent.succeeded" and metadata.get("kind") == "escrow":
        after_commit_notifications = await _handle_escrow_succeeded(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, after_commit_notifications
    if (
        event_type == "payment_intent.payment_failed"
        and metadata.get("kind") == "escrow"
    ):
        await _handle_escrow_failed(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []
    if event_type == "payment_intent.payment_failed":
        await _handle_purchase_failed(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []
    if event_type == "payment_intent.canceled" and metadata.get("kind") == "escrow":
        await _handle_escrow_failed(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []
    if event_type == "account.updated":
        await _handle_account_updated(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []
    if event_type == "payout.paid":
        await _handle_connected_payout_paid(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []
    if event_type == "payout.failed":
        payout_notifications = await _handle_connected_payout_failed(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, payout_notifications
    if event_type == "transfer.created":
        await _handle_transfer_created(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []
    if event_type == "transfer.reversed":
        transfer_notifications = await _handle_transfer_event(
            db, event, payout_status="failed"
        )
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, transfer_notifications
    if event_type == "charge.refunded":
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []

    logger.bind(
        module="webhooks",
        action="unknown_stripe_event",
        provider_event_id=event_id,
    ).warning("unknown_event_type")
    return "received", None, []


async def handle_stripe_webhook(
    db: AsyncSession,
    *,
    payload: bytes,
    signature_header: str | None,
) -> WebhookIngestResponse:
    """Verify, store, and dispatch a Stripe webhook event."""
    try:
        event = stripe.verify_webhook(payload, signature_header)
    except StripeProviderError as exc:
        await _audit_invalid_signature(db, provider="stripe")
        logger.bind(module="webhooks", action="verify_stripe_webhook").warning(
            "signature_invalid",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature.",
        ) from exc

    event_id = _required_event_field(event, "id")
    event_type = _required_event_field(event, "type")
    payload_hash = hashlib.sha256(payload).hexdigest()
    await _ensure_verified_event_row(
        db=db,
        provider="stripe",
        event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
    )

    try:
        if db.in_transaction():
            await db.rollback()
        invoice_transaction_id: UUID | None = None
        after_commit_notifications: list[Callable[[], None]] = []
        async with db.begin():
            # Lock the idempotency row so concurrent deliveries serialize and a
            # retry only short-circuits when the event already fully processed.
            # Rows in `received`/`failed` (e.g. a transient dispatch error) are
            # reprocessed; the dispatch handlers are individually idempotent.
            locked_event = await db.scalar(
                select(WebhookEvent)
                .where(
                    WebhookEvent.provider == "stripe",
                    WebhookEvent.provider_event_id == event_id,
                )
                .with_for_update()
            )
            if locked_event is None:
                raise WebhookProcessingError(
                    "webhook event row missing during dispatch"
                )
            if locked_event.status == "processed":
                logger.bind(
                    module="webhooks",
                    action="stripe_webhook_replay",
                    provider_event_id=event_id,
                ).info("webhook_replay")
                return WebhookIngestResponse(received=True, status="duplicate")
            (
                event_status,
                invoice_transaction_id,
                after_commit_notifications,
            ) = await _dispatch_verified_event(
                db,
                event_id=event_id,
                event_type=event_type,
                event=event,
            )
    except Exception as exc:
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            await _mark_event_status(
                db,
                event_id=event_id,
                status_="failed",
                error=str(exc)[:500],
            )
        logger.bind(
            module="webhooks",
            action="dispatch_stripe_webhook",
            provider_event_id=event_id,
        ).error("webhook_dispatch_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed.",
        ) from exc
    if invoice_transaction_id is not None:
        _queue_purchase_invoice_generation(invoice_transaction_id)
    for queue_notification in after_commit_notifications:
        queue_notification()

    logger.bind(
        module="webhooks",
        action="dispatch_stripe_webhook",
        provider_event_id=event_id,
    ).info("webhook_processed")
    return WebhookIngestResponse(received=True, status=event_status)


def _paystack_envelope(event: dict[str, Any]) -> dict[str, Any]:
    """Reshape a Paystack event into the internal Stripe-shaped envelope.

    Paystack names the event under `event` and puts the object directly under
    `data`, where Stripe uses `type` and `data.object`. Translating once here
    lets the purchase handlers stay single-shaped instead of branching on
    provider at every field read.

    The object id is overwritten with the charge `reference`, because that —
    not Paystack's numeric `id` — is what we store as `provider_ref` at
    initialization and what refunds are keyed by.

    Args:
        event: Verified Paystack event payload.

    Returns:
        The same event in `{"type": ..., "data": {"object": ...}}` form.
    """
    raw_data = event.get("data")
    event_object = dict(raw_data) if isinstance(raw_data, dict) else {}
    reference = event_object.get("reference")
    if isinstance(reference, str):
        event_object["id"] = reference
    return {"type": event.get("event"), "data": {"object": event_object}}


def _paystack_event_id(event_type: str, envelope: dict[str, Any]) -> str:
    """Derive a stable idempotency key for a Paystack event.

    Paystack sends no event id, so `webhook_events.provider_event_id` is
    synthesized from the event name plus the charge reference. Including the
    name keeps `charge.success` and `charge.failed` for one reference distinct;
    including the reference keeps redeliveries of the same charge collapsed.

    Args:
        event_type: The Paystack event name.
        envelope: The normalized envelope from `_paystack_envelope`.

    Returns:
        The synthesized provider event id.

    Raises:
        HTTPException(400): The event carries no reference to key on.
    """
    object_id = _event_object_id(envelope)
    if object_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paystack event missing reference.",
        )
    return f"{event_type}:{object_id}"


async def _dispatch_paystack_event(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    envelope: dict[str, Any],
) -> tuple[str, UUID | None, list[Callable[[], None]]]:
    """Dispatch a verified Paystack event and return status plus follow-up work."""
    metadata = _event_metadata(envelope)
    if event_type == "charge.success" and metadata.get("kind") == "purchase":
        invoice_transaction_id, _ = await _handle_purchase_succeeded(
            db, envelope, provider="paystack"
        )
        await _mark_event_status(
            db, event_id=event_id, status_="processed", provider="paystack"
        )
        return "processed", invoice_transaction_id, []
    if event_type in {"charge.failed", "charge.abandoned"}:
        await _handle_purchase_failed(
            db, envelope, provider="paystack", reason=event_type
        )
        await _mark_event_status(
            db, event_id=event_id, status_="processed", provider="paystack"
        )
        return "processed", None, []
    if event_type == "transfer.success":
        # Terminal on this rail, unlike Stripe. A Paystack transfer settles
        # directly to the beneficiary's bank rather than into a provider-held
        # balance, so there is no later bank-payout event to wait for.
        await _handle_transfer_event(
            db, envelope, payout_status="completed", provider="paystack"
        )
        await _mark_event_status(
            db, event_id=event_id, status_="processed", provider="paystack"
        )
        return "processed", None, []
    if event_type in {"transfer.failed", "transfer.reversed"}:
        transfer_notifications = await _handle_transfer_event(
            db, envelope, payout_status="failed", provider="paystack"
        )
        await _mark_event_status(
            db, event_id=event_id, status_="processed", provider="paystack"
        )
        return "processed", None, transfer_notifications

    # Paystack delivers every event enabled on the integration, most of which
    # this platform never acts on. Storing without dispatching keeps the
    # delivery acknowledged so Paystack stops retrying it.
    logger.bind(
        module="webhooks",
        action="unknown_paystack_event",
        provider_event_id=event_id,
    ).warning("unknown_event_type")
    return "received", None, []


async def handle_paystack_webhook(
    db: AsyncSession,
    *,
    payload: bytes,
    signature_header: str | None,
) -> WebhookIngestResponse:
    """Verify, store, and dispatch a Paystack webhook event.

    Mirrors the Stripe path: the signature is checked against the raw body
    before any parsing, the verified event is stored as the durable
    idempotency anchor, and dispatch runs under a row lock so concurrent
    redeliveries serialize.

    Args:
        db: Async SQLAlchemy session.
        payload: Raw request body, required for HMAC verification.
        signature_header: Value of the `x-paystack-signature` header.

    Returns:
        Ingest acknowledgement carrying the resulting event status.

    Raises:
        HTTPException(400): Signature verification failed or the event carries
            no reference to key idempotency on.
        HTTPException(500): A verified event could not be applied.
    """
    try:
        event = paystack.verify_webhook(payload, signature_header)
    except PaystackProviderError as exc:
        await _audit_invalid_signature(db, provider="paystack")
        logger.bind(module="webhooks", action="verify_paystack_webhook").warning(
            "signature_invalid",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Paystack signature.",
        ) from exc

    event_type = event.get("event")
    if not isinstance(event_type, str) or not event_type.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paystack event missing event name.",
        )
    envelope = _paystack_envelope(event)
    event_id = _paystack_event_id(event_type, envelope)
    payload_hash = hashlib.sha256(payload).hexdigest()
    await _ensure_verified_event_row(
        db=db,
        provider="paystack",
        event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
    )

    try:
        if db.in_transaction():
            await db.rollback()
        invoice_transaction_id: UUID | None = None
        after_commit_notifications: list[Callable[[], None]] = []
        async with db.begin():
            locked_event = await db.scalar(
                select(WebhookEvent)
                .where(
                    WebhookEvent.provider == "paystack",
                    WebhookEvent.provider_event_id == event_id,
                )
                .with_for_update()
            )
            if locked_event is None:
                raise WebhookProcessingError(
                    "webhook event row missing during dispatch"
                )
            if locked_event.status == "processed":
                logger.bind(
                    module="webhooks",
                    action="paystack_webhook_replay",
                    provider_event_id=event_id,
                ).info("webhook_replay")
                return WebhookIngestResponse(received=True, status="duplicate")
            (
                event_status,
                invoice_transaction_id,
                after_commit_notifications,
            ) = await _dispatch_paystack_event(
                db,
                event_id=event_id,
                event_type=event_type,
                envelope=envelope,
            )
    except Exception as exc:
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            await _mark_event_status(
                db,
                event_id=event_id,
                status_="failed",
                error=str(exc)[:500],
                provider="paystack",
            )
        logger.bind(
            module="webhooks",
            action="dispatch_paystack_webhook",
            provider_event_id=event_id,
        ).error("webhook_dispatch_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed.",
        ) from exc

    if invoice_transaction_id is not None:
        _queue_purchase_invoice_generation(invoice_transaction_id)
    for queue_notification in after_commit_notifications:
        queue_notification()

    logger.bind(
        module="webhooks",
        action="dispatch_paystack_webhook",
        provider_event_id=event_id,
    ).info("webhook_processed")
    return WebhookIngestResponse(received=True, status=event_status)


# Persona inquiry statuses that close out an inquiry. A terminal row is final:
# later deliveries for the same inquiry are treated as replays.
_PERSONA_VERIFIED_STATUSES = frozenset({"approved", "completed"})
_PERSONA_REJECTED_STATUSES = frozenset({"declined", "failed", "expired"})
_PERSONA_TERMINAL_STATUSES = _PERSONA_VERIFIED_STATUSES | _PERSONA_REJECTED_STATUSES


def _persona_inquiry_resource(event: dict[str, Any]) -> dict[str, Any]:
    """Return the inquiry resource carried by a Persona webhook event.

    Persona nests the changed resource at
    ``data.attributes.payload.data`` (a JSON:API resource object).
    """
    data = event.get("data")
    attributes = data.get("attributes") if isinstance(data, dict) else None
    payload = attributes.get("payload") if isinstance(attributes, dict) else None
    resource = payload.get("data") if isinstance(payload, dict) else None
    return resource if isinstance(resource, dict) else {}


async def _audit_persona_invalid_signature(db: AsyncSession) -> None:
    """Persist a minimal audit row for a rejected Persona signature."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=None,
            action="webhook_signature_invalid",
            target_type="webhook",
            metadata={"provider": "persona"},
        )


async def _apply_persona_decision(
    db: AsyncSession,
    *,
    inquiry_id: str,
    inquiry_status: str,
) -> str:
    """Apply one Persona inquiry decision to identity + KYC state.

    Returns the webhook ingest status: ``processed`` when a decision is applied,
    ``duplicate`` when the inquiry already reached a terminal state, or
    ``received`` when the status is non-terminal or the inquiry is unknown.
    """
    record = await db.scalar(
        select(IdentityVerification)
        .where(IdentityVerification.inquiry_id == inquiry_id)
        .with_for_update()
    )
    if record is None:
        logger.bind(
            module="webhooks",
            action="persona_webhook",
        ).warning("unknown_inquiry", provider="persona")
        return "received"

    if record.status in _PERSONA_TERMINAL_STATUSES:
        return "duplicate"

    if inquiry_status not in _PERSONA_TERMINAL_STATUSES:
        # Non-terminal progress (created/pending/needs_review): track only.
        record.status = inquiry_status
        return "received"

    verified = inquiry_status in _PERSONA_VERIFIED_STATUSES
    kyc_status = "verified" if verified else "rejected"
    record.status = inquiry_status
    record.decision_at = datetime.now(UTC)

    user = await db.get(User, record.user_id)
    if user is None:
        raise WebhookProcessingError("identity verification user not found")
    user.kyc_status = kyc_status

    await write_audit(
        db=db,
        actor_id=user.id,
        action="kyc_status_change",
        target_type="user",
        target_id=user.id,
        metadata={
            "status": kyc_status,
            "provider": "persona",
            "inquiry_id": inquiry_id,
        },
    )
    await create_notification(
        db=db,
        user_id=user.id,
        notification_type="kyc_verified" if verified else "kyc_rejected",
        title=(
            "Identity verified" if verified else "Identity verification needs attention"
        ),
        body=(
            "Your identity verification is complete."
            if verified
            else "Your identity verification was not approved. Start a new "
            "verification to try again."
        ),
        link="/settings/kyc",
        payload={"inquiry_id": inquiry_id, "status": kyc_status},
        dedupe_key=f"persona-decision:{inquiry_id}:{kyc_status}",
    )
    return "processed"


async def handle_persona_webhook(
    db: AsyncSession,
    *,
    payload: bytes,
    signature_header: str | None,
) -> WebhookIngestResponse:
    """Verify and apply a Persona identity-verification webhook.

    The signature is verified over the raw body before any parsing. A verified
    inquiry decision drives ``users.kyc_status``; replays of a terminal inquiry
    are reported as duplicates.

    Args:
        db: Async DB session.
        payload: Raw request body bytes.
        signature_header: The ``Persona-Signature`` header value.

    Returns:
        A small acknowledgement with the processing status.

    Raises:
        HTTPException(400): If the signature is invalid.
        HTTPException(500): If a verified event cannot be applied.
    """
    try:
        event = persona.verify_webhook(payload, signature_header)
    except PersonaProviderError as exc:
        await _audit_persona_invalid_signature(db)
        logger.bind(module="webhooks", action="verify_persona_webhook").warning(
            "signature_invalid",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Persona signature.",
        ) from exc

    resource = _persona_inquiry_resource(event)
    inquiry_id = resource.get("id")
    inquiry_attributes = resource.get("attributes")
    inquiry_status = (
        inquiry_attributes.get("status")
        if isinstance(inquiry_attributes, dict)
        else None
    )
    if not isinstance(inquiry_id, str) or not isinstance(inquiry_status, str):
        # Could not locate the inquiry id/status at the expected envelope path.
        # Log structure only (event name + resource type/keys) so a real-world
        # shape mismatch is diagnosable without leaking PII from the payload.
        event_attributes = event.get("data", {})
        event_attributes = (
            event_attributes.get("attributes", {})
            if isinstance(event_attributes, dict)
            else {}
        )
        logger.bind(module="webhooks", action="persona_webhook").warning(
            "unparseable_event",
            provider="persona",
            event_name=event_attributes.get("name")
            if isinstance(event_attributes, dict)
            else None,
            resource_type=resource.get("type"),
            resource_keys=sorted(resource.keys()),
        )
        return WebhookIngestResponse(received=True, status="received")

    try:
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            ingest_status = await _apply_persona_decision(
                db,
                inquiry_id=inquiry_id,
                inquiry_status=inquiry_status,
            )
    except Exception as exc:
        if db.in_transaction():
            await db.rollback()
        logger.bind(
            module="webhooks",
            action="dispatch_persona_webhook",
            inquiry_id=inquiry_id,
        ).error("webhook_dispatch_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed.",
        ) from exc

    logger.bind(
        module="webhooks",
        action="dispatch_persona_webhook",
        inquiry_id=inquiry_id,
    ).info("webhook_processed")
    return WebhookIngestResponse(received=True, status=ingest_status)
