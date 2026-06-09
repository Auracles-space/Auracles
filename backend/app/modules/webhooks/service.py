"""Webhook ingestion and dispatch services.

Stripe signs the raw request body, so the router passes bytes here before any
JSON parsing. Verified events are stored in `webhook_events` for replay safety,
then dispatched to small handlers that update local financial state.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import hash_payout_provider_account_id
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.financials import escrow_service
from app.modules.financials.models import Payout, PayoutAccount, Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.webhooks.models import WebhookEvent
from app.modules.webhooks.schemas import WebhookIngestResponse
from app.workers.tasks.financials import generate_invoice_pdf


class WebhookProcessingError(RuntimeError):
    """Raised when a verified provider event cannot be safely applied."""


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


async def _insert_verified_event(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload_hash: str,
) -> bool:
    """Store a verified Stripe event once; return False for replay delivery."""
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
        return False
    return True


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
) -> UUID:
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
    return transaction.id


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


async def _handle_escrow_succeeded(
    db: AsyncSession,
    event: dict[str, Any],
) -> None:
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
    await escrow_service.hold(
        db,
        transaction_id=transaction_id,
        release_conditions=_escrow_release_conditions(event),
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


async def _handle_transfer_event(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    payout_status: str,
) -> None:
    """Apply Stripe transfer status to an existing payout row when present."""
    transfer_id = _event_object_id(event)
    if transfer_id is None:
        raise WebhookProcessingError("transfer event missing transfer id")
    payout = await db.scalar(
        select(Payout).where(Payout.provider_ref == transfer_id)
    )
    if payout is None:
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
) -> tuple[str, UUID | None]:
    """Dispatch a verified event and return status plus optional invoice work."""
    metadata = _event_metadata(event)
    if event_type == "payment_intent.succeeded" and metadata.get("kind") == "purchase":
        invoice_transaction_id = await _handle_purchase_succeeded(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", invoice_transaction_id
    if event_type == "payment_intent.succeeded" and metadata.get("kind") == "escrow":
        await _handle_escrow_succeeded(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None
    if event_type == "payment_intent.payment_failed":
        await _handle_purchase_failed(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None
    if event_type == "account.updated":
        await _handle_account_updated(db, event)
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None
    if event_type == "transfer.paid":
        await _handle_transfer_event(db, event, payout_status="completed")
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None
    if event_type == "transfer.failed":
        await _handle_transfer_event(db, event, payout_status="failed")
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None
    if event_type == "charge.refunded":
        await _mark_event_status(db, event_id=event_id, status_="processed")
        return "processed", None

    logger.bind(
        module="webhooks",
        action="unknown_stripe_event",
        provider_event_id=event_id,
    ).warning("unknown_event_type")
    return "received", None


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
    inserted = await _insert_verified_event(
        db=db,
        event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
    )
    if not inserted:
        logger.bind(
            module="webhooks",
            action="stripe_webhook_replay",
            provider_event_id=event_id,
        ).info("webhook_replay")
        return WebhookIngestResponse(received=True, status="duplicate")

    try:
        if db.in_transaction():
            await db.rollback()
        invoice_transaction_id: UUID | None = None
        async with db.begin():
            event_status, invoice_transaction_id = await _dispatch_verified_event(
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

    logger.bind(
        module="webhooks",
        action="dispatch_stripe_webhook",
        provider_event_id=event_id,
    ).info("webhook_processed")
    return WebhookIngestResponse(received=True, status=event_status)
