"""Response schemas for the admin Treasury endpoints.

Amounts are major-unit decimals. No bank account numbers, recipient codes or
provider references appear here: the summary is aggregate figures only.

Maps to: platform treasury design §API.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
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
    platform_withdrawals: Decimal
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
    unreviewed_unrecognized_transfers: int


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


class PlatformWithdrawalRequest(BaseModel):
    """Request body for withdrawing platform money to the platform bank account.

    NGN only in v1; the currency is implied. Two decimal places at most.
    """

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class PlatformWithdrawalItem(BaseModel):
    """One platform withdrawal, with its destination shown as last four only."""

    id: UUID
    amount: Decimal
    currency: str
    status: str
    reference: str
    bank_name: str
    account_last4: str
    failure_reason: str | None
    requested_by: UUID
    requested_at: datetime
    completed_at: datetime | None
    failed_at: datetime | None


class PlatformWithdrawalsResponse(BaseModel):
    """Paginated platform withdrawal history, newest first."""

    withdrawals: list[PlatformWithdrawalItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class UnrecognizedTransferItem(BaseModel):
    """A transfer out of the platform balance that Auracles did not start."""

    id: UUID
    provider: str
    reference: str
    event_type: str
    amount: Decimal | None
    currency: str | None
    recipient_name: str | None
    recipient_bank: str | None
    recipient_last4: str | None
    acknowledged_by: UUID | None
    acknowledged_at: datetime | None
    created_at: datetime


class UnrecognizedTransfersResponse(BaseModel):
    """Unrecognized transfers, unreviewed first then newest first."""

    transfers: list[UnrecognizedTransferItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class FeeBackfillResponse(BaseModel):
    """Acknowledgement that the fee backfill was queued."""

    status: Literal["queued"]
