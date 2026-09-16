"""Response schemas for the admin Treasury endpoints.

Amounts are major-unit decimals. No bank account numbers, recipient codes or
provider references appear here: the summary is aggregate figures only.

Maps to: platform treasury design §API.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class TreasuryOwedToUsers(BaseModel):
    """Money in the balance that belongs to users (liabilities)."""

    held_escrow: Decimal
    contributor_balances: Decimal
    org_balances: Decimal
    partner_commissions: Decimal
    total: Decimal


class TreasuryOurMoney(BaseModel):
    """The platform's own share: commission earned less what it has paid for."""

    commission_framework_sales: Decimal
    commission_collections: Decimal
    commission_project_milestones: Decimal
    commission_attestation_fees: Decimal
    provider_fees: Decimal
    partner_commissions: Decimal
    total: Decimal


class TreasuryCurrencySummary(BaseModel):
    """One currency's Treasury figures.

    ``live_balance``, ``withdrawable`` and ``balance_gap`` are only set for the
    currency Paystack holds, and only when the balance lookup succeeded
    (``balance_unavailable`` is true when it did not).
    """

    currency: str
    withdrawable_here: bool
    owed_to_users: TreasuryOwedToUsers
    our_money: TreasuryOurMoney
    live_balance: Decimal | None
    withdrawable: Decimal | None
    balance_gap: Decimal | None
    balance_unavailable: bool


class TreasurySummaryResponse(BaseModel):
    """Treasury summary across every currency on the ledger."""

    currencies: list[TreasuryCurrencySummary]
    live_balance_fetched_at: datetime | None
