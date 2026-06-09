"""Pydantic schemas for financials endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PaymentMethodSetupRequest(BaseModel):
    """Request body for starting a provider-hosted payment method setup."""

    model_config = ConfigDict(extra="forbid")

    totp_code: str = Field(min_length=6, max_length=16)


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
    """Request body for removing a provider-held payment method."""

    model_config = ConfigDict(extra="forbid")

    totp_code: str = Field(min_length=6, max_length=16)


class PaymentMethodDeleteResponse(BaseModel):
    """Response body for a removed provider-held payment method."""

    provider: Literal["stripe"]
    payment_method_id: str
    removed: bool


PayoutProvider = Literal["stripe"]


class PayoutAccountOnboardRequest(BaseModel):
    """Request body for creating a provider-held payout destination."""

    model_config = ConfigDict(extra="forbid")

    provider: PayoutProvider
    country: str = Field(min_length=2, max_length=2)
    refresh_url: str = Field(min_length=1)
    return_url: str = Field(min_length=1)


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


class PayoutAccountsResponse(BaseModel):
    """Response body for listing active payout accounts."""

    payout_accounts: list[PayoutAccountResponse]


class PayoutAccountDeleteRequest(BaseModel):
    """Request body for soft-deleting a payout account."""

    model_config = ConfigDict(extra="forbid")

    totp_code: str = Field(min_length=6, max_length=16)


class PayoutAccountDeleteResponse(BaseModel):
    """Response body for a soft-deleted payout account."""

    payout_account_id: UUID
    deleted: bool
