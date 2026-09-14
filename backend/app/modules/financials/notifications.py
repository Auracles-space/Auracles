"""Post-commit notifications for individual payees on the money path.

Organization payout notices live in ``app.modules.organizations.notifications``.
This module covers people paid directly, starting with a failed bank payout on
a Stripe connected account: the payee must hear what went wrong and that the
money is safe, or they see nothing arrive and cannot fix it.
"""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.workers.tasks.project_notifications import dispatch_project_notification


def notify_bank_payout_failed(
    user_id: UUID,
    *,
    payout_account_id: UUID,
    provider_ref: str | None,
    failure_message: str | None,
) -> None:
    """Tell a payee their bank payout failed, why, and that funds are safe.

    Args:
        user_id: The payee who owns the connected payout account.
        payout_account_id: The account the failure was recorded against.
        provider_ref: Stripe payout id, used to deduplicate redeliveries.
        failure_message: The bank's reason, when Stripe supplied one.
    """
    reason = f" Reason: {failure_message}" if failure_message else ""
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type="payout_failed",
            title="Your bank payout failed",
            body=(
                "Stripe could not pay out to your bank account."
                f"{reason} The money is safe in your Stripe balance and will be "
                "included in your next payout once your bank details are updated."
            ),
            payload={"payout_account_id": str(payout_account_id)},
            link="/dashboard/financials",
            dedupe_key=f"payout_failed:{payout_account_id}:{provider_ref or 'unknown'}",
        )
    except Exception as exc:  # pragma: no cover - defensive queue guard
        logger.bind(
            module="financials",
            action="notify_bank_payout_failed",
            user_id=str(user_id),
        ).error("notification_dispatch_failed", error=str(exc))
