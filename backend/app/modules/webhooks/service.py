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
from app.integrations import persona, stripe
from app.integrations.persona import PersonaProviderError
from app.integrations.stripe import StripeProviderError
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


async def _audit_invalid_signature(db: AsyncSession) -> None:
    """Persist a minimal audit row for rejected provider signatures."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=None,
            action="webhook_signature_invalid",
            target_type="webhook",
            metadata={"provider": "stripe"},
        )


async def _ensure_verified_event_row(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload_hash: str,
) -> None:
    """Persist a verified Stripe event row once, ignoring concurrent inserts.

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
                    provider="stripe",
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
) -> None:
    """Update durable webhook event processing status."""
    event_row = await db.scalar(
        select(WebhookEvent).where(
            WebhookEvent.provider == "stripe",
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
) -> tuple[UUID, list[Callable[[], None]]]:
    """Mark a purchase complete and grant its Framework License."""
    transaction_id = _purchase_transaction_id(event)
    payment_intent_id = _event_object_id(event)
    metadata = _event_metadata(event)
    license_type = metadata.get("license_type")
    if license_type is None:
        raise WebhookProcessingError("purchase event missing license_type")

    transaction = await db.get(Transaction, transaction_id)
    if transaction is None:
        raise WebhookProcessingError("purchase transaction not found")
    if transaction.transaction_type != "purchase":
        raise WebhookProcessingError("transaction is not a purchase")
    if transaction.provider != "stripe":
        raise WebhookProcessingError("transaction provider mismatch")
    if transaction.provider_ref and transaction.provider_ref != payment_intent_id:
        raise WebhookProcessingError("payment intent id mismatch")
    if transaction.ref_id is None:
        raise WebhookProcessingError("purchase transaction missing framework ref")

    framework = await db.get(Framework, transaction.ref_id)
    if framework is None:
        raise WebhookProcessingError("purchase framework not found")
    if license_type not in framework.license_types:
        raise WebhookProcessingError("license type is unavailable")

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
            "provider": "stripe",
            "framework_id": str(framework.id),
            "license_id": str(existing_license.id),
            "license_type": license_type,
        },
    )
    after_commit_work = await _create_partner_commission_if_attributed(
        db=db,
        transaction=transaction,
        framework_id=framework.id,
    )
    return transaction.id, after_commit_work


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
) -> None:
    """Mark a purchase transaction failed after Stripe payment failure."""
    transaction_id = _purchase_transaction_id(event)
    payment_intent_id = _event_object_id(event)
    transaction = await db.get(Transaction, transaction_id)
    if transaction is None:
        raise WebhookProcessingError("purchase transaction not found")
    if transaction.provider_ref and transaction.provider_ref != payment_intent_id:
        raise WebhookProcessingError("payment intent id mismatch")
    transaction.status = "failed"
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="purchase_failed",
        target_type="transaction",
        target_id=transaction.id,
        metadata={"provider": "stripe", "reason": "payment_intent.payment_failed"},
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
        )
        return

    transaction.status = "failed"
    await write_audit(
        db=db,
        actor_id=transaction.payer_id,
        action="escrow_funding_failed",
        target_type="transaction",
        target_id=transaction.id,
        metadata={"provider": "stripe", "reason": event_type},
    )


async def _mark_attestation_fee_failed(
    *,
    db: AsyncSession,
    transaction: Transaction,
    reason: str,
) -> None:
    """Cancel an Attestation when fee escrow funding fails before hold."""
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
    return [
        lambda: attestation_notifications.notify_fee_funded(attestation),
        lambda: attestation_notifications.notify_offers(attestation, offers),
        lambda: (
            attestation_notifications.notify_needs_admin(attestation)
            if attestation.status == "needs_admin"
            else None
        ),
    ]


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
    # The payee is the assigned Contributor, who starts work once escrow holds.
    project_notifications.notify_milestone_funded(
        contributor_id=transaction.payee_id,
        project_id=project.id,
        milestone_id=milestone.id,
    )


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


async def _handle_transfer_event(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    payout_status: str,
) -> None:
    """Apply Stripe transfer status to an existing payout row when present.

    Matches the payout first by stored ``provider_ref`` (the transfer id). When
    that misses — a ``transfer.created`` event can arrive before the worker
    commits ``provider_ref`` — falls back to the ``payout_id`` carried in the
    transfer metadata and backfills the reference. Unknown transfers no-op.
    """
    transfer_id = _event_object_id(event)
    if transfer_id is None:
        raise WebhookProcessingError("transfer event missing transfer id")
    payout = await db.scalar(select(Payout).where(Payout.provider_ref == transfer_id))
    if payout is None:
        payout = await _payout_from_metadata(db, event)
        if payout is None:
            return
        if payout.provider_ref is None:
            payout.provider_ref = transfer_id
    if payout.status == payout_status:
        return
    payout.status = payout_status
    if payout_status == "completed":
        payout.completed_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=payout.contributor_id,
        action=f"payout_{payout_status}",
        target_type="payout",
        target_id=payout.id,
        metadata={"provider": "stripe", "transfer_ref": transfer_id[-4:]},
    )


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
        invoice_transaction_id, after_commit_notifications = (
            await _handle_purchase_succeeded(db, event)
        )
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
    if event_type == "transfer.created":
        await _handle_transfer_event(db, event, payout_status="completed")
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []
    if event_type == "transfer.reversed":
        await _handle_transfer_event(db, event, payout_status="failed")
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None, []
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
        await _audit_invalid_signature(db)
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
            "Identity verified"
            if verified
            else "Identity verification needs attention"
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
        logger.bind(module="webhooks", action="persona_webhook").warning(
            "unknown_event_type", provider="persona"
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
