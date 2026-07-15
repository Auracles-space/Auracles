"""Notification preference mapping, matrix building, and delivery gates.

Phase 5 settings preferences stay event-type based in storage, but expose
display categories for later Settings UI grouping. Delivery is opt-out:
missing preference rows still allow delivery.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Final
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.notifications.models import (
    NOTIFICATION_CATEGORY_ENUM,
    NOTIFICATION_CHANNEL_ENUM,
    NOTIFICATION_TYPE_ENUM,
    NotificationPreference,
)
from app.modules.notifications.schemas import (
    NotificationPreferenceCategory,
    NotificationPreferenceChannelItem,
    NotificationPreferenceItem,
    NotificationPreferencesResponse,
    NotificationPreferenceUpdateItem,
)

DEFAULT_NOTIFICATION_CATEGORY: Final[str] = "account"
CRITICAL_NOTIFICATION_TYPES: Final[set[str]] = {
    "milestone_funded",
    "deliverable_approved",
    "deliverable_auto_approved",
    "attestation_fee_funded",
    "attestation_released",
    "attestation_refunded",
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
    "milestone_plan_finalized": "project",
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
    "attestation_annual_summary_ready": "attestation",
    "api_rate_limit_threshold": "account",
    "saved_search_alert": "discovery",
    "kyc_verified": "account",
    "kyc_rejected": "account",
    "org_invitation_received": "account",
    "org_invitation_accepted": "account",
    "org_invitation_declined": "account",
    "org_attestor_trial_nominated": "account",
    "org_attestor_trial_assigned": "account",
    "org_attestor_needs_info": "account",
    "org_attestor_approved": "account",
    "org_attestor_rejected": "account",
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
NOTIFICATION_CATEGORY_LABELS: Final[dict[str, str]] = {
    category: category.replace("_", " ").title()
    for category in NOTIFICATION_CATEGORY_ENUM.enums
}

# Event types kept in the enum for internal/audit use but hidden from the user
# preference matrix: each either notifies the actor about their own action
# (project_created), is workspace-timeline noise rather than inbox-worthy
# (milestone_created/updated), or duplicates an event the user is already
# notified about (attestation_published/rejected are covered by
# attestation_report_submitted). Showing toggles for these would be dead
# controls, so they are excluded from the displayed matrix.
HIDDEN_NOTIFICATION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "project_created",
        "milestone_created",
        "milestone_updated",
        "attestation_published",
        "attestation_rejected",
    }
)


def displayed_notification_types() -> list[str]:
    """Return user-facing notification types in enum order, hiding dead toggles."""
    return [
        notification_type
        for notification_type in NOTIFICATION_TYPE_ENUM.enums
        if notification_type not in HIDDEN_NOTIFICATION_TYPES
    ]


def category_for_notification_type(notification_type: str) -> str:
    """Return the display category for one notification type.

    Unmapped types fail open to the account category so new enum labels still
    deliver until a follow-up mapping lands.
    """
    return NOTIFICATION_TYPE_CATEGORY.get(
        notification_type,
        DEFAULT_NOTIFICATION_CATEGORY,
    )


def _channel_items(
    *,
    notification_type: str,
    enabled_by_channel: dict[str, bool],
) -> list[NotificationPreferenceChannelItem]:
    """Build ordered channel items for one notification type."""
    locked = notification_type in CRITICAL_NOTIFICATION_TYPES
    return [
        NotificationPreferenceChannelItem(
            channel=channel,
            enabled=True if locked else enabled_by_channel.get(channel, True),
            locked=locked,
        )
        for channel in NOTIFICATION_CHANNEL_ENUM.enums
    ]


def _validate_notification_type(notification_type: str) -> None:
    """Reject notification types that are not part of the product enum."""
    if notification_type not in NOTIFICATION_TYPE_ENUM.enums:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unsupported notification type: {notification_type}.",
        )


def _validate_channel(channel: str) -> None:
    """Reject channels that are not part of the stored preference enum."""
    if channel not in NOTIFICATION_CHANNEL_ENUM.enums:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unsupported notification channel: {channel}.",
        )


async def build_preference_matrix(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> NotificationPreferencesResponse:
    """Return the effective grouped preference matrix for one user."""
    rows = (
        (
            await db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )

    enabled_lookup = {
        (row.notification_type, row.channel): bool(row.enabled) for row in rows
    }
    grouped_preferences: dict[str, list[NotificationPreferenceItem]] = defaultdict(list)

    for notification_type in displayed_notification_types():
        category = category_for_notification_type(notification_type)
        grouped_preferences[category].append(
            NotificationPreferenceItem(
                notification_type=notification_type,
                label=NOTIFICATION_TYPE_LABELS[notification_type],
                description=NOTIFICATION_TYPE_DESCRIPTIONS[notification_type],
                channels=_channel_items(
                    notification_type=notification_type,
                    enabled_by_channel={
                        channel: enabled_lookup.get((notification_type, channel), True)
                        for channel in NOTIFICATION_CHANNEL_ENUM.enums
                    },
                ),
            )
        )

    return NotificationPreferencesResponse(
        categories=[
            NotificationPreferenceCategory(
                category=category,
                label=NOTIFICATION_CATEGORY_LABELS[category],
                preferences=grouped_preferences.get(category, []),
            )
            for category in NOTIFICATION_CATEGORY_ENUM.enums
        ]
    )


async def update_preferences(
    db: AsyncSession,
    *,
    user_id: UUID,
    updates: list[NotificationPreferenceUpdateItem],
) -> NotificationPreferencesResponse:
    """Upsert owner-scoped notification preferences and return the new matrix."""
    deduped_updates: dict[tuple[str, str], NotificationPreferenceUpdateItem] = {}
    for update in updates:
        _validate_notification_type(update.notification_type)
        _validate_channel(update.channel)
        if (
            update.notification_type in CRITICAL_NOTIFICATION_TYPES
            and update.enabled is False
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Critical notification preferences cannot be disabled.",
            )
        deduped_updates[(update.notification_type, update.channel)] = update

    try:
        for update in deduped_updates.values():
            statement = (
                pg_insert(NotificationPreference)
                .values(
                    user_id=user_id,
                    notification_type=update.notification_type,
                    category=category_for_notification_type(update.notification_type),
                    channel=update.channel,
                    enabled=update.enabled,
                )
                .on_conflict_do_update(
                    constraint="uq_notification_preferences_user_type_channel",
                    set_={
                        "category": category_for_notification_type(
                            update.notification_type
                        ),
                        "enabled": update.enabled,
                    },
                )
            )
            await db.execute(statement)

        await write_audit(
            db=db,
            actor_id=user_id,
            action="notification_preferences_updated",
            target_type="user",
            target_id=user_id,
            metadata={
                "updated_count": len(deduped_updates),
                "keys": [
                    f"{notification_type}:{channel}"
                    for notification_type, channel in deduped_updates
                ],
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return await build_preference_matrix(db=db, user_id=user_id)


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
