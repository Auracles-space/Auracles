"""Admin alert for transfers Paystack is holding for a one-time code.

With transfer OTP switched on for the Paystack account, every transfer stops
at status ``otp`` until someone enters the code sent to the business, and no
webhook follows. Payouts and platform withdrawals would otherwise sit at
"processing" with no explanation, so admins are told what is holding them and
how to switch the requirement off.

Entering the code is not offered as the remedy, because Paystack ends an
unanswered transfer about an hour after it was created and an alert is rarely
read in time. `app.workers.tasks.transfer_reconcile` settles what the provider
ended; the alert exists to get the setting changed so it stops recurring.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from loguru import logger

from app.modules.admin.notifications import notify_admins_review_pending

PAYSTACK_OTP_STATUS = "otp"


def alert_transfer_held_for_otp(
    *,
    notify: Callable[..., None] = notify_admins_review_pending,
    what: str,
    target_id: UUID,
    amount: Decimal,
    currency: str,
    link: str,
) -> None:
    """Tell every admin a transfer is waiting for a Paystack OTP.

    Args:
        notify: The admin notification function, passed by the calling module
            so its own (patchable) import is used.
        what: Human name of the transfer, e.g. "A contributor payout".
        target_id: The payout or withdrawal id, for dedupe and linking.
        amount: Transfer amount.
        currency: Transfer currency.
        link: Admin page where the transfer is listed.
    """
    logger.bind(
        module="financials", action="transfer_held_for_otp", target_id=str(target_id)
    ).warning("paystack_transfer_held_for_otp")
    notify(
        domain="paystack_transfer_otp",
        target_id=target_id,
        body=(
            f"{what} of {amount} {currency} is waiting for a Paystack one-time "
            "code and will not be sent until someone enters it. Paystack ends "
            "the transfer about an hour after it was created, and we then "
            "release the money so it can be requested again. To stop this "
            "happening, turn transfer OTP off on the Paystack account: clear "
            '"Confirm before sending" for transfers in the dashboard, or '
            "call /transfer/disable_otp and finalize it with the emailed code."
        ),
        link=link,
    )
