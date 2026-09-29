"""Post-commit notifications for individual payees on the money path.

Organization payout notices live in ``app.modules.organizations.notifications``.
This module covers people paid directly. An org heard when its payout was
requested, completed or failed; a person paid directly heard nothing at all,
because outcome notices were gated on the payout having an `org_id`. On
Paystack a transfer settles straight to the bank, defers on an underfunded
balance, or is abandoned on a held transfer, so the payee had no way to learn
which had happened to their money.

Every notifier here is called after the webhook transaction commits and must
never raise: the settlement has already happened, and failing the webhook would
invite the provider to redeliver it.
"""

from __future__ import annotations

from uuid import UUID

from decimal import Decimal

from loguru import logger

from app.modules.organizations.notifications import format_money
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


def notify_payout_completed(
    user_id: UUID,
    *,
    payout_id: UUID,
    amount: Decimal,
    currency: str,
) -> None:
    """Tell a payee their payout reached their bank.

    The one event on the money path a payee cannot observe for themselves —
    they see a balance change at their bank, or they wait and wonder.

    Args:
        user_id: The person being paid.
        payout_id: Payout that just completed, used to deduplicate redeliveries.
        amount: Net amount paid, in major units.
        currency: ISO 4217 code the payout settled in.
    """
    _dispatch(
        action="notify_payout_completed",
        user_id=user_id,
        notification_type="payout_completed",
        title="Your payout has been paid",
        body=(
            f"{format_money(amount, currency)} has been sent to your bank "
            "account. Your bank decides when it appears on your statement."
        ),
        payout_id=payout_id,
    )


def notify_payout_failed(
    user_id: UUID,
    *,
    payout_id: UUID,
    amount: Decimal,
    currency: str,
    failure_reason: str | None,
) -> None:
    """Tell a payee their payout did not go through, and why.

    Args:
        user_id: The person being paid.
        payout_id: Payout that failed, used to deduplicate redeliveries.
        amount: Net amount attempted, in major units.
        currency: ISO 4217 code the payout was denominated in.
        failure_reason: Provider message when one was supplied. Paystack does
            not always give one, so the notice has to stand without it.
    """
    reason = f" Reason: {failure_reason}." if failure_reason else ""
    _dispatch(
        action="notify_payout_failed",
        user_id=user_id,
        notification_type="payout_failed",
        title="Your payout could not be paid",
        body=(
            f"{format_money(amount, currency)} could not be sent to your bank "
            f"account.{reason} The money has been returned to your available "
            "balance and you can request it again."
        ),
        payout_id=payout_id,
    )


def _dispatch(
    *,
    action: str,
    user_id: UUID,
    notification_type: str,
    title: str,
    body: str,
    payout_id: UUID,
) -> None:
    """Queue one payout notice, swallowing a broker failure.

    Args:
        action: Log tag naming the caller.
        user_id: Recipient.
        notification_type: Registered notification label.
        title: Notification heading.
        body: Notification text.
        payout_id: Deduplication key source.
    """
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type=notification_type,
            title=title,
            body=body,
            payload={"payout_id": str(payout_id)},
            link="/dashboard/financials",
            dedupe_key=f"{notification_type}:{payout_id}",
        )
    except Exception as exc:  # pragma: no cover - defensive queue guard
        logger.bind(
            module="financials",
            action=action,
            user_id=str(user_id),
        ).error("notification_dispatch_failed", error=str(exc))
