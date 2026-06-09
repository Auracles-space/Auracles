"""Pydantic schemas for financials endpoints."""

from typing import Literal

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
