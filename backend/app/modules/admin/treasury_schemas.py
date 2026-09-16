"""Response schemas for the admin Treasury endpoints.

Amounts are major-unit decimals. No bank account numbers, recipient codes or
provider references appear here: the summary is aggregate figures only.

Maps to: platform treasury design §API.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class PlatformBankAccountSetRequest(BaseModel):
    """Request body for setting or replacing the platform bank account.

    The bank code must come from Paystack's bank list; the account number is
    a ten-digit NUBAN and is never stored — only its last four digits.
    """

    model_config = ConfigDict(extra="forbid")

    account_number: str = Field(pattern=r"^[0-9]{10}$")
    bank_code: str = Field(min_length=1, max_length=20)


class PlatformBankAccountItem(BaseModel):
    """Display-safe view of the active platform bank account."""

    id: UUID
    bank_name: str
    bank_code: str
    account_last4: str
    account_name: str | None
    usable_from: datetime
    created_at: datetime


class PlatformBankAccountResponse(BaseModel):
    """The active platform bank account, or null before one is set."""

    bank_account: PlatformBankAccountItem | None
