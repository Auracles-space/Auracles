"""Account-holder notifications for GDPR deletion requests.

Requesting deletion told the admin queue and nobody else, so the person whose
account was about to be erased got no acknowledgement, no date, and no mention
of the window they could still cancel in. These three helpers close that.

All three types are in `CRITICAL_NOTIFICATION_TYPES`, so a muted preference
cannot suppress them: the scheduled notice is the account holder's only
out-of-band signal if the deletion was started by someone who had their
session rather than by them.

Each is called after the transaction that recorded the request has committed,
and a queue failure is logged rather than raised — failing to send mail must
not roll back a deletion the user asked for.

Maps to: FR-GDPR (account deletion).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from loguru import logger

from app.modules.gdpr.schemas import AccountDeletionBlockedReason
from app.workers.tasks.project_notifications import dispatch_project_notification

# Where the account holder manages the request: cancel it, or see what is
# blocking it. Resolved against the route tree by the notification-link test.
_ACCOUNT_SETTINGS_LINK = "/settings/account"


def _dispatch(
    *,
    user_id: UUID,
    request_id: UUID,
    notification_type: str,
    title: str,
    body: str,
) -> None:
    """Queue one account-deletion notification, swallowing queue failures."""
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type=notification_type,
            title=title,
            body=body,
            payload={"request_id": str(request_id)},
            link=_ACCOUNT_SETTINGS_LINK,
            # Keyed on the request, so a Celery retry is idempotent while a
            # later request after a cancellation still notifies.
            dedupe_key=f"{notification_type}:{request_id}",
        )
    except Exception as exc:  # pragma: no cover - defensive queue guard
        logger.bind(
            module="gdpr",
            action="notify_account_deletion",
            user_id=str(user_id),
            notification_type=notification_type,
        ).error("notification_dispatch_failed", error=str(exc))


def notify_account_deletion_scheduled(
    *,
    user_id: UUID,
    request_id: UUID,
    scheduled_for: datetime,
) -> None:
    """Acknowledge a scheduled deletion and name the date it becomes final.

    Args:
        user_id: Account holder to notify.
        request_id: The deletion request this acknowledges.
        scheduled_for: When the erasure runs if nobody cancels it.
    """
    when = scheduled_for.strftime("%d %B %Y")
    _dispatch(
        user_id=user_id,
        request_id=request_id,
        notification_type="account_deletion_scheduled",
        title="Your account is scheduled for deletion",
        body=(
            f"We received your request to delete your Auracles account. It "
            f"will be erased on {when}. You can cancel any time before then "
            "in Settings. If you did not request this, cancel it now and "
            "change your password."
        ),
    )


def notify_account_deletion_blocked(
    *,
    user_id: UUID,
    request_id: UUID,
    reasons: list[AccountDeletionBlockedReason],
) -> None:
    """Tell the account holder what is standing in the way of deletion.

    Args:
        user_id: Account holder to notify.
        request_id: The blocked deletion request.
        reasons: Obligations that must clear first, in the order collected.
    """
    detail = "\n".join(f"- {reason.message}" for reason in reasons)
    _dispatch(
        user_id=user_id,
        request_id=request_id,
        notification_type="account_deletion_blocked",
        title="Your account cannot be deleted yet",
        body=(
            "We received your request to delete your Auracles account, but it "
            "is on hold until the following are resolved:\n"
            f"{detail}\n"
            "Request deletion again once they are clear."
        ),
    )


def notify_account_deletion_cancelled(
    *,
    user_id: UUID,
    request_id: UUID,
) -> None:
    """Confirm the scheduled deletion is off and the account stays.

    Args:
        user_id: Account holder to notify.
        request_id: The cancelled deletion request.
    """
    _dispatch(
        user_id=user_id,
        request_id=request_id,
        notification_type="account_deletion_cancelled",
        title="Account deletion cancelled",
        body=(
            "Your Auracles account will not be deleted. The scheduled erasure "
            "has been cancelled and your account is unchanged. If you did not "
            "cancel this yourself, change your password."
        ),
    )
