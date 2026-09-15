"""Admin-review notification helpers.

Thin dispatch wrappers that queue a durable notification to every admin when
user-submitted work lands in an admin review queue. Services call these after
committing their own domain state; the fan-out to individual admin accounts
happens in the ``dispatch_admin_notification`` Celery task.
"""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.workers.tasks.admin_notifications import dispatch_admin_notification

_TITLE = "Item awaiting admin review"

# One title per review source, so an admin can tell an attestor application
# from a dispute in the notification list without opening it.
_DOMAIN_TITLES = {
    "account_deletion": "Account deletion needs review",
    "attestation": "Attestation needs manual assignment",
    "credential": "Credential awaiting verification",
    "developer_application": "Developer application submitted",
    "org_attestor_application": "Attestor application submitted",
    "org_kyb": "Business verification submitted",
    "payout": "Payout needs attention",
    "platform_balance": "Platform balance below floor",
    "project_dispute": "Project dispute raised",
    "refund": "Refund needs attention",
}


def notify_admins_review_pending(
    *,
    domain: str,
    target_id: UUID,
    body: str,
    link: str,
    title: str | None = None,
) -> None:
    """Queue one admin-review notification, fanned out to every admin account.

    Args:
        domain: Stable slug for the review source (e.g. ``developer_application``,
            ``credential``, ``org_attestor_application``, ``project_dispute``,
            ``attestation``). Carried in the payload for filtering and grouping.
        target_id: UUID of the record needing review; forms the dedupe key so a
            re-submitted or retried event never double-notifies an admin.
        body: Human-readable summary shown in the notification.
        link: Deep link to the admin surface that resolves the item.
        title: Optional notification title; defaults to the domain's title, or
            a generic review prompt for a domain without one.
    """
    try:
        dispatch_admin_notification.delay(
            notification_type="admin_review_pending",
            title=title or _DOMAIN_TITLES.get(domain, _TITLE),
            body=body,
            payload={"domain": domain, "target_id": str(target_id)},
            link=link,
            dedupe_key=f"admin_review_pending:{domain}:{target_id}",
        )
    except Exception as exc:
        # A broker hiccup must never roll back the committed domain action that
        # triggered the review; log and move on so the queue item still exists.
        logger.bind(
            module="admin",
            action="queue_admin_review_notification",
            domain=domain,
            target_id=target_id,
        ).error("admin_notification_dispatch_failed", error=str(exc))
