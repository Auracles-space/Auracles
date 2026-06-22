"""Partner outbound webhook lifecycle service.

Registers Developer-owned webhook endpoints, stores HMAC signing secrets
encrypted at rest, lists safe metadata, and owns retry/dead-letter mutations for
delivery workers.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import (
    decrypt_partner_webhook_secret,
    encrypt_partner_webhook_secret,
)
from app.modules.developer.constants import VALID_PARTNER_WEBHOOK_EVENTS
from app.modules.developer.models import (
    DeveloperAccount,
    PartnerWebhook,
    PartnerWebhookDelivery,
)
from app.modules.developer.schemas import PartnerWebhookCreateRequest
from app.workers.tasks.partner_webhooks import deliver_partner_webhook

WEBHOOK_SECRET_PREFIX = "whsec_"
WEBHOOK_SECRET_RANDOM_BYTES = 32


def webhook_secret_hint(webhook: PartnerWebhook) -> str:
    """Return a masked signing-secret hint (prefix + last four characters).

    Non-sensitive: reveals only the four trailing characters so a partner can
    tell which secret is configured without exposing a usable value.
    """
    secret = decrypt_partner_webhook_secret(webhook.secret_encrypted)
    return f"{WEBHOOK_SECRET_PREFIX}••••{secret[-4:]}"


def _generate_raw_webhook_secret() -> str:
    """Generate a high-entropy Partner webhook signing secret."""
    token = secrets.token_urlsafe(WEBHOOK_SECRET_RANDOM_BYTES)
    return f"{WEBHOOK_SECRET_PREFIX}{token}"


async def create_partner_webhook(
    db: AsyncSession,
    developer_account: DeveloperAccount,
    payload: PartnerWebhookCreateRequest,
) -> tuple[PartnerWebhook, str]:
    """Register a Developer-owned outbound webhook and return its raw secret once."""
    account_id = developer_account.id
    user_id = developer_account.user_id
    raw_secret = _generate_raw_webhook_secret()

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        webhook = PartnerWebhook(
            developer_account_id=account_id,
            url=str(payload.url),
            secret_encrypted=encrypt_partner_webhook_secret(raw_secret),
            events=payload.events,
            active=True,
        )
        db.add(webhook)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=user_id,
            action="partner_webhook_created",
            target_type="partner_webhook",
            target_id=webhook.id,
            metadata={
                "developer_account_id": str(account_id),
                "events": webhook.events,
            },
        )
    return webhook, raw_secret


async def list_partner_webhooks(
    db: AsyncSession,
    developer_account: DeveloperAccount,
) -> list[PartnerWebhook]:
    """Return safe webhook endpoint metadata for one Developer account."""
    result = await db.execute(
        select(PartnerWebhook)
        .where(PartnerWebhook.developer_account_id == developer_account.id)
        .order_by(PartnerWebhook.created_at.desc())
    )
    return list(result.scalars().all())


async def enqueue_partner_webhook_deliveries(
    db: AsyncSession,
    *,
    developer_account_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> list[UUID]:
    """Create pending delivery rows for active webhooks subscribed to an event."""
    if event_type not in VALID_PARTNER_WEBHOOK_EVENTS:
        raise ValueError(f"Unknown Partner webhook event: {event_type}")

    result = await db.execute(
        select(PartnerWebhook).where(
            PartnerWebhook.developer_account_id == developer_account_id,
            PartnerWebhook.active.is_(True),
            PartnerWebhook.events.any(event_type),  # type: ignore[arg-type]  # ARRAY.any() value typing
        )
    )
    webhooks = list(result.scalars().all())
    delivery_ids: list[UUID] = []
    for webhook in webhooks:
        delivery = PartnerWebhookDelivery(
            partner_webhook_id=webhook.id,
            event_type=event_type,
            payload=payload,
            status="pending",
        )
        db.add(delivery)
        await db.flush()
        delivery_ids.append(delivery.id)
        await write_audit(
            db=db,
            actor_id=None,
            action="partner_webhook_delivery_queued",
            target_type="partner_webhook_delivery",
            target_id=delivery.id,
            metadata={
                "developer_account_id": str(developer_account_id),
                "partner_webhook_id": str(webhook.id),
                "event_type": event_type,
            },
        )
    return delivery_ids


def queue_partner_webhook_deliveries(delivery_ids: Iterable[UUID | str]) -> None:
    """Dispatch Celery tasks for committed Partner webhook delivery rows."""
    for delivery_id in delivery_ids:
        deliver_partner_webhook.delay(str(delivery_id))


async def delete_partner_webhook(
    db: AsyncSession,
    developer_account: DeveloperAccount,
    webhook_id: UUID,
) -> PartnerWebhook:
    """Deactivate a Developer-owned webhook without deleting delivery history."""
    account_id = developer_account.id
    user_id = developer_account.user_id

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        webhook = await db.scalar(
            select(PartnerWebhook)
            .where(
                PartnerWebhook.id == webhook_id,
                PartnerWebhook.developer_account_id == account_id,
            )
            .with_for_update()
        )
        if webhook is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner webhook not found.",
            )
        if webhook.active:
            webhook.active = False
            await write_audit(
                db=db,
                actor_id=user_id,
                action="partner_webhook_deleted",
                target_type="partner_webhook",
                target_id=webhook.id,
                metadata={"developer_account_id": str(account_id)},
            )
    return webhook


async def retry_partner_webhook_delivery(
    db: AsyncSession,
    developer_account: DeveloperAccount,
    delivery_id: UUID,
) -> PartnerWebhookDelivery:
    """Reset a failed/dead owned delivery and queue a new outbound attempt."""
    account_id = developer_account.id
    user_id = developer_account.user_id

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        row = await db.execute(
            select(PartnerWebhookDelivery, PartnerWebhook)
            .join(
                PartnerWebhook,
                PartnerWebhook.id == PartnerWebhookDelivery.partner_webhook_id,
            )
            .where(
                PartnerWebhookDelivery.id == delivery_id,
                PartnerWebhook.developer_account_id == account_id,
            )
            .with_for_update()
        )
        result = row.one_or_none()
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Partner webhook delivery not found.",
            )
        delivery, webhook = result
        if delivery.status not in {"failed", "dead"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only failed or dead webhook deliveries can be retried.",
            )
        if not webhook.active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Inactive webhooks cannot be retried.",
            )

        delivery.status = "pending"
        delivery.attempts = 0
        delivery.response_code = None
        delivery.last_attempt_at = None
        delivery.next_attempt_at = None
        await write_audit(
            db=db,
            actor_id=user_id,
            action="partner_webhook_retry_queued",
            target_type="partner_webhook_delivery",
            target_id=delivery.id,
            metadata={
                "developer_account_id": str(account_id),
                "partner_webhook_id": str(webhook.id),
                "event_type": delivery.event_type,
            },
        )

    deliver_partner_webhook.delay(str(delivery_id))
    # delivery is unpacked from a Row tuple, so mypy widens it to Any.
    return cast("PartnerWebhookDelivery", delivery)
