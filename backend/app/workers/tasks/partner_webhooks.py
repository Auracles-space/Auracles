"""Celery tasks for Partner outbound webhook delivery.

Outbound webhooks notify Developer partners about marketplace events using
HMAC-SHA256 signatures. The task stores every attempt on
`partner_webhook_deliveries` so retries and dead letters are auditable.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.core.security import decrypt_partner_webhook_secret
from app.modules.developer.models import PartnerWebhook, PartnerWebhookDelivery
from app.workers.async_runner import run_async
from app.workers.celery_app import app

MAX_WEBHOOK_ATTEMPTS = 5
WEBHOOK_TIMEOUT_SECONDS = 10


def _serialize_payload(payload: dict[str, Any]) -> bytes:
    """Serialize webhook JSON deterministically for stable HMAC verification."""
    return json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _next_retry_at(attempts: int) -> datetime:
    """Return the exponential backoff timestamp after a failed attempt."""
    delay_seconds = min(60 * (2 ** max(attempts - 1, 0)), 3600)
    return datetime.now(UTC) + timedelta(seconds=delay_seconds)


def _is_blocked_ip(address: str) -> bool:
    """Return whether a resolved webhook address is unsafe to call."""
    ip = ipaddress.ip_address(address)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_webhook_url_for_delivery(url: str) -> None:
    """Block non-HTTPS and internal Partner webhook destinations at send time."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Partner webhook URL must be HTTPS.")
    resolved = socket.getaddrinfo(
        parsed.hostname,
        parsed.port or 443,
        type=socket.SOCK_STREAM,
    )
    for item in resolved:
        address = item[4][0]
        if _is_blocked_ip(address):
            raise ValueError("Partner webhook URL resolves to a blocked address.")


async def _post_webhook(url: str, raw_body: bytes, headers: dict[str, str]) -> int:
    """POST one signed Partner webhook request and return its status code."""
    _validate_webhook_url_for_delivery(url)
    async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
        response = await client.post(url, content=raw_body, headers=headers)
    return response.status_code


async def _deliver_partner_webhook(delivery_id: str) -> dict[str, str]:
    """Load, sign, POST, and persist one Partner webhook delivery attempt."""
    parsed_delivery_id = UUID(delivery_id)
    async with async_session_factory() as db:
        row = await db.execute(
            select(PartnerWebhookDelivery, PartnerWebhook)
            .join(
                PartnerWebhook,
                PartnerWebhook.id == PartnerWebhookDelivery.partner_webhook_id,
            )
            .where(PartnerWebhookDelivery.id == parsed_delivery_id)
        )
        result = row.one_or_none()
        if result is None:
            raise ValueError("Partner webhook delivery not found.")
        delivery, webhook = result
        if delivery.status in {"delivered", "dead"}:
            return {"delivery_id": str(delivery.id), "status": delivery.status}
        if not webhook.active:
            if db.in_transaction():
                await db.rollback()
            async with db.begin():
                locked_delivery = await db.get(
                    PartnerWebhookDelivery,
                    parsed_delivery_id,
                )
                if locked_delivery is None:
                    raise ValueError("Partner webhook delivery not found.")
                locked_delivery.status = "dead"
                locked_delivery.last_attempt_at = datetime.now(UTC)
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="partner_webhook_dead",
                    target_type="partner_webhook_delivery",
                    target_id=locked_delivery.id,
                    metadata={"reason": "webhook_inactive"},
                )
            return {"delivery_id": str(parsed_delivery_id), "status": "dead"}

        raw_body = _serialize_payload(delivery.payload)
        timestamp = str(int(datetime.now(UTC).timestamp()))
        raw_secret = decrypt_partner_webhook_secret(webhook.secret_encrypted)
        signature = hmac.new(
            raw_secret.encode("utf-8"),
            f"{timestamp}.".encode() + raw_body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Auracles-Event": delivery.event_type,
            "X-Auracles-Timestamp": timestamp,
            "X-Auracles-Signature": signature,
        }

        response_code: int | None
        try:
            response_code = await _post_webhook(webhook.url, raw_body, headers)
            delivered = 200 <= response_code < 300
        except Exception as exc:
            logger.bind(
                module="developer",
                action="deliver_partner_webhook",
                delivery_id=str(parsed_delivery_id),
            ).warning("partner_webhook_post_failed", error=str(exc))
            response_code = None
            delivered = False

        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            locked_delivery = await db.scalar(
                select(PartnerWebhookDelivery)
                .where(PartnerWebhookDelivery.id == parsed_delivery_id)
                .with_for_update()
            )
            if locked_delivery is None:
                raise ValueError("Partner webhook delivery not found.")
            if locked_delivery.status in {"delivered", "dead"}:
                return {
                    "delivery_id": str(locked_delivery.id),
                    "status": locked_delivery.status,
                }
            locked_delivery.attempts += 1
            locked_delivery.response_code = response_code
            locked_delivery.last_attempt_at = datetime.now(UTC)
            if delivered:
                locked_delivery.status = "delivered"
                locked_delivery.next_attempt_at = None
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="partner_webhook_delivered",
                    target_type="partner_webhook_delivery",
                    target_id=locked_delivery.id,
                    metadata={
                        "partner_webhook_id": str(locked_delivery.partner_webhook_id),
                        "event_type": locked_delivery.event_type,
                        "response_code": response_code,
                    },
                )
            else:
                locked_delivery.status = (
                    "dead"
                    if locked_delivery.attempts >= MAX_WEBHOOK_ATTEMPTS
                    else "failed"
                )
                locked_delivery.next_attempt_at = (
                    None
                    if locked_delivery.status == "dead"
                    else _next_retry_at(locked_delivery.attempts)
                )
                await write_audit(
                    db=db,
                    actor_id=None,
                    action=(
                        "partner_webhook_dead"
                        if locked_delivery.status == "dead"
                        else "partner_webhook_failed"
                    ),
                    target_type="partner_webhook_delivery",
                    target_id=locked_delivery.id,
                    metadata={
                        "partner_webhook_id": str(locked_delivery.partner_webhook_id),
                        "event_type": locked_delivery.event_type,
                        "response_code": response_code,
                        "attempts": locked_delivery.attempts,
                    },
                )
            final_status = locked_delivery.status
        return {"delivery_id": str(parsed_delivery_id), "status": final_status}


@app.task(bind=True)  # type: ignore[untyped-decorator]
def deliver_partner_webhook(self: Any, delivery_id: str) -> dict[str, str]:
    """Deliver one pending Partner webhook event with HMAC authentication."""
    log = logger.bind(
        module="developer",
        action="deliver_partner_webhook",
        task_id=self.request.id,
        delivery_id=delivery_id,
    )
    log.info("task_started")
    result = run_async(_deliver_partner_webhook(delivery_id))
    log.info("task_completed", result=result)
    return result


async def _retry_due_partner_webhooks() -> dict[str, int]:
    """Queue failed Partner webhook deliveries whose backoff has elapsed."""
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        result = await db.execute(
            select(PartnerWebhookDelivery.id).where(
                PartnerWebhookDelivery.status == "failed",
                PartnerWebhookDelivery.next_attempt_at <= now,
            )
        )
        delivery_ids = [str(delivery_id) for delivery_id in result.scalars().all()]
    for delivery_id in delivery_ids:
        deliver_partner_webhook.delay(delivery_id)
    return {"queued_count": len(delivery_ids)}


@app.task(bind=True)  # type: ignore[untyped-decorator]
def retry_due_partner_webhooks(self: Any) -> dict[str, int]:
    """Queue Partner webhook deliveries whose exponential backoff has elapsed."""
    log = logger.bind(
        module="developer",
        action="retry_due_partner_webhooks",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_retry_due_partner_webhooks())
    log.info("task_completed", result=result)
    return result
