"""Notification preference mapping and delivery-gate helpers.

Phase 5 settings preferences stay event-type based in storage, but expose
display categories for later Settings UI grouping. Delivery is opt-out:
missing preference rows still allow delivery.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import (
    NOTIFICATION_TYPE_ENUM,
    NotificationPreference,
)

DEFAULT_NOTIFICATION_CATEGORY: Final[str] = "account"
CRITICAL_NOTIFICATION_TYPES: Final[set[str]] = {
    "dispute_resolved_release",
    "dispute_resolved_refund",
    "dispute_resolved_split",
}
NOTIFICATION_TYPE_CATEGORY: Final[dict[str, str]] = {
    "project_created": "project",
    "project_extended": "project",
    "project_closed": "project",
    "proposal_submitted": "project",
    "proposal_accepted": "project",
    "proposal_rejected": "project",
    "proposal_withdrawn": "project",
    "proposal_expired": "project",
    "amendment_proposed": "project",
    "amendment_accepted": "project",
    "amendment_rejected": "project",
    "amendment_withdrawn": "project",
    "amendment_expired": "project",
    "milestone_created": "project",
    "milestone_updated": "project",
    "milestone_funded": "financial",
    "deliverable_submitted": "project",
    "deliverable_approved": "project",
    "deliverable_auto_approved": "project",
    "deliverable_revision_requested": "project",
    "dispute_raised": "project",
    "dispute_escalated": "project",
    "dispute_resolved_release": "financial",
    "dispute_resolved_refund": "financial",
    "dispute_resolved_split": "financial",
    "workspace_file_quarantined": "project",
    "attestation_requested": "attestation",
    "attestation_fee_funded": "attestation",
    "attestation_offer_received": "attestation",
    "attestation_assigned": "attestation",
    "attestation_accepted": "attestation",
    "attestation_declined": "attestation",
    "attestation_offer_expired": "attestation",
    "attestation_reassigned": "attestation",
    "attestation_needs_admin": "attestation",
    "attestation_report_submitted": "attestation",
    "attestation_published": "attestation",
    "attestation_rejected": "attestation",
    "attestation_released": "attestation",
    "attestation_disputed": "attestation",
    "attestation_dispute_resolved": "attestation",
    "attestation_refunded": "attestation",
    "api_rate_limit_threshold": "account",
    "saved_search_alert": "discovery",
}
NOTIFICATION_TYPE_LABELS: Final[dict[str, str]] = {
    notification_type: notification_type.replace("_", " ").title()
    for notification_type in NOTIFICATION_TYPE_ENUM.enums
}
NOTIFICATION_TYPE_DESCRIPTIONS: Final[dict[str, str]] = {
    notification_type: (
        f"Receive {NOTIFICATION_TYPE_LABELS[notification_type].lower()} updates."
    )
    for notification_type in NOTIFICATION_TYPE_ENUM.enums
}


def category_for_notification_type(notification_type: str) -> str:
    """Return the display category for one notification type.

    Unmapped types fail open to the account category so new enum labels still
    deliver until a follow-up mapping lands.
    """
    return NOTIFICATION_TYPE_CATEGORY.get(
        notification_type,
        DEFAULT_NOTIFICATION_CATEGORY,
    )


def _enabled_query(
    *,
    user_id: UUID,
    notification_type: str,
    channel: str,
) -> Select[tuple[bool]]:
    """Build the preference lookup for one user/type/channel triple."""
    return select(NotificationPreference.enabled).where(
        NotificationPreference.user_id == user_id,
        NotificationPreference.notification_type == notification_type,
        NotificationPreference.channel == channel,
    )


async def should_deliver(
    db: AsyncSession,
    *,
    user_id: UUID,
    notification_type: str,
    channel: str,
) -> bool:
    """Return whether one notification channel should be delivered.

    Critical notification types always bypass user preferences. All other types
    are opt-out: no stored row means enabled.
    """
    if notification_type in CRITICAL_NOTIFICATION_TYPES:
        return True

    enabled = await db.scalar(
        _enabled_query(
            user_id=user_id,
            notification_type=notification_type,
            channel=channel,
        )
    )
    return True if enabled is None else bool(enabled)
