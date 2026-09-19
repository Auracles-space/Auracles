"""Pydantic schemas for financials endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PaymentMethodSetupRequest(BaseModel):
    """Request body for starting a provider-hosted payment method setup.

    Intentionally empty: the endpoint is gated by an open step-up window.
    ``extra="forbid"`` still rejects stray fields such as a raw card number.
    """

    model_config = ConfigDict(extra="forbid")


class PaymentMethodSetupResponse(BaseModel):
    """Stripe SetupIntent data needed by the browser to attach a method."""

    provider: Literal["stripe"]
    setup_intent_id: str
    client_secret: str


class PaymentMethodResponse(BaseModel):
    """Safe provider-held payment method metadata returned to Operators."""

    id: str
    provider: Literal["stripe"]
    type: str
    brand: str | None
    last4: str | None
    exp_month: int | None
    exp_year: int | None


class PaymentMethodsResponse(BaseModel):
    """Response body for listing an Operator's saved payment methods."""

    payment_methods: list[PaymentMethodResponse]


class PaymentMethodDeleteRequest(BaseModel):
    """Request body for removing a provider-held payment method.

    Intentionally empty: the endpoint is gated by an open step-up window.
    """

    model_config = ConfigDict(extra="forbid")


class PaymentMethodDeleteResponse(BaseModel):
    """Response body for a removed provider-held payment method."""

    provider: Literal["stripe"]
    payment_method_id: str
    removed: bool


PayoutProvider = Literal["stripe", "paystack"]
SelfServeLicenseType = Literal["single_user", "team", "organizational"]


class PurchaseRequest(BaseModel):
    """Request body for starting self-serve Framework checkout."""

    model_config = ConfigDict(extra="forbid")

    license_type: SelfServeLicenseType
    country: str | None = Field(default=None, min_length=2, max_length=2)
    """ISO 3166-1 alpha-2 country of the payer, used to pick the payment rail.

    Optional: an omitted value routes to the default (Stripe) rail. Supplied
    per-request rather than read from the account because users carry no
    stored country — the same shape the individual payout onboarding uses.
    """


class PurchaseResponse(BaseModel):
    """Provider handoff data the browser needs to complete checkout.

    The two rails hand off differently and exactly one field is populated:
    Stripe returns a `client_secret` for in-page Elements, while Paystack
    returns an `authorization_url` the browser is redirected to.
    """

    transaction_id: UUID
    provider: Literal["stripe", "paystack"]
    client_secret: str | None = None
    authorization_url: str | None = None


class RefundResponse(BaseModel):
    """Response body for a successful self-serve purchase refund.

    `status` describes the purchase, not the provider's transfer of funds. A
    Stripe refund is terminal on return; a Paystack refund is accepted here
    and settles afterwards. In both cases the purchase is refunded and access
    is revoked from this point on.
    """

    transaction_id: UUID
    provider: Literal["stripe", "paystack"]
    refund_id: str
    status: Literal["refunded"]


class PurchaseHistoryItem(BaseModel):
    """Operator-facing purchase history row."""

    transaction_id: UUID
    framework_id: UUID
    framework_title: str
    amount: Decimal
    currency: str
    status: str
    provider: Literal["stripe", "paystack"]
    license_id: UUID | None
    license_type: str | None
    purchased_at: datetime


class PurchaseHistoryResponse(BaseModel):
    """Paginated response body for Operator purchase history."""

    items: list[PurchaseHistoryItem]
    total: int
    page: int
    page_size: int


class InvoiceGenerationResponse(BaseModel):
    """Response body returned while invoice PDF generation is queued."""

    transaction_id: UUID
    status: Literal["generating"]


class PayoutAccountOnboardRequest(BaseModel):
    """Request body for creating a provider-held payout destination.

    The two rails collect different things. Stripe Connect runs hosted
    onboarding, so it needs only the redirect URLs and never sees a bank
    detail here. Paystack has no hosted flow — the Contributor's NUBAN account
    number and bank code are submitted directly and registered as a transfer
    recipient, which is also what verifies the account exists.
    """

    model_config = ConfigDict(extra="forbid")

    provider: PayoutProvider
    country: str = Field(min_length=2, max_length=2)
    # Stripe-only: Paystack returns no onboarding URL to redirect back from.
    refresh_url: str | None = Field(default=None, min_length=1)
    return_url: str | None = Field(default=None, min_length=1)
    # Paystack-only. NUBAN numbers are fixed-length; the bank code comes from
    # GET /financials/payout-accounts/banks, never from a hardcoded list.
    account_number: str | None = Field(default=None, min_length=10, max_length=10)
    bank_code: str | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def provider_has_the_fields_its_rail_requires(self) -> PayoutAccountOnboardRequest:
        """Reject a payload missing the fields its chosen rail cannot work without.

        Caught here rather than in the service so an incomplete request is a
        422 from the schema instead of a provider call that fails halfway and
        leaves an orphan account at Stripe or Paystack.
        """
        if self.provider == "paystack":
            if not self.account_number or not self.bank_code:
                raise ValueError(
                    "Paystack payout accounts require account_number and bank_code."
                )
        elif not self.refresh_url or not self.return_url:
            raise ValueError(
                "Stripe payout accounts require refresh_url and return_url."
            )
        return self


class PayoutAccountResolveRequest(BaseModel):
    """Request body for checking a NUBAN against the bank before saving it."""

    model_config = ConfigDict(extra="forbid")

    account_number: str = Field(min_length=10, max_length=10)
    bank_code: str = Field(min_length=1, max_length=10)


class PayoutAccountResolveResponse(BaseModel):
    """The name the bank holds for a NUBAN, shown back for confirmation.

    Carries the name alone. The lookup registers nothing, so there is no
    account id to return and nothing to clean up if the name is wrong.
    """

    account_name: str


class PayoutBank(BaseModel):
    """A bank a Contributor payout account can be held at."""

    name: str
    code: str


class PayoutBanksResponse(BaseModel):
    """Response body listing banks available for payout onboarding."""

    banks: list[PayoutBank]


class PayoutAccountResponse(BaseModel):
    """Safe Contributor payout-account metadata."""

    id: UUID
    provider: PayoutProvider
    account_type: str
    provider_account_ref: str
    is_default: bool
    verified_at: datetime | None
    created_at: datetime


class PayoutAccountOnboardResponse(BaseModel):
    """Response body for a provider payout-account onboarding request."""

    provider: PayoutProvider
    onboarding_url: str | None
    payout_account: PayoutAccountResponse
    account_name: str | None = None
    """Bank-confirmed account holder name. Paystack rail only.

    Returned at onboarding rather than stored, because this is the moment it
    matters: it is how a Contributor catches a mistyped account number before
    any money is addressed to it. Paystack resolves the name against the bank
    while registering the transfer recipient, so it costs no extra call.
    """


class PayoutAccountsResponse(BaseModel):
    """Response body for listing active payout accounts."""

    payout_accounts: list[PayoutAccountResponse]


class PayoutAccountDeleteRequest(BaseModel):
    """Request body for soft-deleting a payout account.

    Intentionally empty: the endpoint is gated by an open step-up window.
    """

    model_config = ConfigDict(extra="forbid")


class PayoutAccountDeleteResponse(BaseModel):
    """Response body for a soft-deleted payout account."""

    payout_account_id: UUID
    deleted: bool


class EarningsResponse(BaseModel):
    """Contributor earnings summary in a single settlement currency."""

    currency: str
    gross_revenue: Decimal
    pending_clearance: Decimal
    available_balance: Decimal
    commission_rate: Decimal
    minimum_payout: Decimal


class PayoutEligibilityReason(BaseModel):
    """One unmet org payout condition and where it can be fixed.

    ``action_path`` is an app path (starting with ``/``) to the surface that
    clears the condition, or ``None`` when nothing the owner can do resolves it
    directly (suspension, an in-flight payout, a balance under the minimum).
    """

    code: Literal[
        "org_suspended",
        "kyb_not_verified",
        "no_payout_capability",
        "tax_document_missing",
        "payout_in_progress",
        "no_verified_payout_account",
        "below_minimum_payout",
    ]
    message: str
    action_path: str | None


class PayoutEligibility(BaseModel):
    """Whether an organization can request a payout right now, and why not."""

    eligible: bool
    reasons: list[PayoutEligibilityReason]


class OrgEarningsResponse(EarningsResponse):
    """Organization earnings plus the payout eligibility checklist (Slice C)."""

    payout_eligibility: PayoutEligibility


class OrgPayoutHistoryItem(BaseModel):
    """One organization payout in the owner-facing history.

    ``amount`` is the net amount requested (what reaches the payout account).
    """

    id: UUID
    amount: Decimal
    currency: str
    status: str
    provider: str
    requested_at: datetime
    completed_at: datetime | None
    failure_reason: str | None


class OrgPayoutHistoryResponse(BaseModel):
    """Paginated organization payout history, newest first."""

    payouts: list[OrgPayoutHistoryItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class OrgPurchaseListItem(BaseModel):
    """One Framework purchase the organization attempted, with its outcome."""

    transaction_id: UUID
    framework_id: UUID | None
    framework_title: str | None
    amount: Decimal
    currency: str
    status: str
    failure_reason: str | None
    created_at: datetime


class OrgPurchasesResponse(BaseModel):
    """Organization Framework purchases, newest first."""

    purchases: list[OrgPurchaseListItem]


class PayoutRequest(BaseModel):
    """Request body for a Contributor payout request."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    payout_account_id: UUID


class PayoutResponse(BaseModel):
    """Contributor-facing payout request and processing status.

    `delay_reason` explains a payout that is still waiting on something the
    beneficiary cannot influence, so a long `pending` can be read rather than
    guessed at. It is null in the ordinary case, including while a payout is
    merely new.
    """

    id: UUID
    payout_account_id: UUID
    amount: Decimal
    currency: str
    commission_deducted: Decimal
    net_amount: Decimal
    status: str
    provider_ref: str | None
    delay_reason: str | None = None
    initiated_at: datetime
    completed_at: datetime | None


class PayoutsResponse(BaseModel):
    """Response body for Contributor payout history."""

    payouts: list[PayoutResponse]


class OrgPayoutAccountOnboardRequest(BaseModel):
    """Request body for onboarding an organization payout destination.

    The organization's registered ``country`` is authoritative for provider
    routing, so — unlike the individual request — no country is accepted here.
    Which fields are required follows from that country: the Stripe rail needs
    only redirect URLs, while Paystack has no hosted flow and needs the org's
    NUBAN account number and bank code.
    """

    model_config = ConfigDict(extra="forbid")

    provider: PayoutProvider
    # Stripe-only: Paystack returns no onboarding URL to redirect back from.
    refresh_url: str | None = Field(default=None, min_length=1)
    return_url: str | None = Field(default=None, min_length=1)
    # Paystack-only. Bank codes come from the payout banks endpoint.
    account_number: str | None = Field(default=None, min_length=10, max_length=10)
    bank_code: str | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def provider_has_the_fields_its_rail_requires(
        self,
    ) -> OrgPayoutAccountOnboardRequest:
        """Reject a payload missing the fields its chosen rail cannot work without."""
        if self.provider == "paystack":
            if not self.account_number or not self.bank_code:
                raise ValueError(
                    "Paystack payout accounts require account_number and bank_code."
                )
        elif not self.refresh_url or not self.return_url:
            raise ValueError(
                "Stripe payout accounts require refresh_url and return_url."
            )
        return self


class OrgInvoiceListItem(BaseModel):
    """One org-attested invoice's non-sensitive metadata for list views."""

    id: UUID
    invoice_number: str
    doc_type: str
    issue_date: datetime
    currency: str
    total: Decimal
    source_ref_type: str
    source_ref_id: UUID
    direction: str


class OrgInvoicesResponse(BaseModel):
    """Response body for an organization's issued invoice list."""

    invoices: list[OrgInvoiceListItem]
