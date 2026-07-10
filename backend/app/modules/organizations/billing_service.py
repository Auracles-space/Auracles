"""Organization billing services for operator-side payment method management."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.payment_router import select_provider
from app.integrations.stripe import StripeProviderError
from app.modules.auth.models import User
from app.modules.financials.schemas import (
    PaymentMethodDeleteResponse,
    PaymentMethodResponse,
    PaymentMethodSetupResponse,
    PaymentMethodsResponse,
)
from app.modules.organizations.models import Organization


async def _get_org_for_billing(db: AsyncSession, *, org_id: UUID) -> Organization:
    """Load one organization required for org-billing operations."""
    organization = await db.get(Organization, org_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )
    return organization


async def create_org_payment_method_setup(
    db: AsyncSession,
    redis: Redis,
    *,
    org_id: UUID,
    actor: User,
    totp_code: str,
) -> PaymentMethodSetupResponse:
    """Create or reuse the org Stripe customer and return a SetupIntent secret."""
    from app.modules.financials.service import _verify_sensitive_payment_method_change

    organization = await _get_org_for_billing(db, org_id=org_id)
    provider = select_provider(user_country=organization.country, currency="USD")
    if provider != "stripe":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        )

    await _verify_sensitive_payment_method_change(
        db=db,
        redis=redis,
        operator=actor,
        totp_code=totp_code,
    )

    customer_id = organization.stripe_customer_id
    try:
        if customer_id is None:
            customer = await stripe.create_customer(
                email=actor.email,
                name=organization.name,
                idempotency_key=f"stripe_customer:org:{organization.id}",
            )
            customer_id = customer.id
        setup_intent = await stripe.create_setup_intent(customer_id=customer_id)
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="create_org_payment_method_setup",
            user_id=actor.id,
        ).error("stripe_org_payment_method_setup_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        stored_org = await db.get(Organization, org_id)
        if stored_org is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found.",
            )
        if stored_org.stripe_customer_id is None:
            stored_org.stripe_customer_id = customer_id
        await write_audit(
            db=db,
            actor_id=actor.id,
            action="org_payment_method_added",
            target_type="organization",
            target_id=org_id,
            metadata={
                "provider": "stripe",
                "setup_intent_ref": f"****{setup_intent.id[-4:]}",
            },
        )

    logger.bind(
        module="financials",
        action="create_org_payment_method_setup",
        user_id=actor.id,
    ).info("org_payment_method_added")
    return PaymentMethodSetupResponse(
        provider="stripe",
        setup_intent_id=setup_intent.id,
        client_secret=setup_intent.client_secret,
    )


async def list_org_payment_methods(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> PaymentMethodsResponse:
    """Return safe metadata for the organization's provider-held payment methods."""
    organization = await _get_org_for_billing(db, org_id=org_id)
    customer_id = organization.stripe_customer_id
    if customer_id is None:
        return PaymentMethodsResponse(payment_methods=[])

    try:
        payment_methods = await stripe.list_payment_methods(customer_id=customer_id)
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="list_org_payment_methods",
        ).error("stripe_org_payment_method_list_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    return PaymentMethodsResponse(
        payment_methods=[
            PaymentMethodResponse(
                id=payment_method.id,
                provider="stripe",
                type=payment_method.type,
                brand=payment_method.brand,
                last4=payment_method.last4,
                exp_month=payment_method.exp_month,
                exp_year=payment_method.exp_year,
            )
            for payment_method in payment_methods
        ]
    )


async def delete_org_payment_method(
    db: AsyncSession,
    redis: Redis,
    *,
    org_id: UUID,
    actor: User,
    payment_method_id: str,
    totp_code: str,
) -> PaymentMethodDeleteResponse:
    """Detach an org-owned payment method after TOTP and ownership checks."""
    from app.modules.financials.service import (
        _masked_provider_ref,
        _verify_sensitive_payment_method_change,
    )

    organization = await _get_org_for_billing(db, org_id=org_id)
    customer_id = organization.stripe_customer_id
    if customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found.",
        )

    await _verify_sensitive_payment_method_change(
        db=db,
        redis=redis,
        operator=actor,
        totp_code=totp_code,
    )

    try:
        owned_methods = await stripe.list_payment_methods(customer_id=customer_id)
        if not any(method.id == payment_method_id for method in owned_methods):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment method not found.",
            )
        detached_id = await stripe.detach_payment_method(
            payment_method_id=payment_method_id,
        )
    except HTTPException:
        raise
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="delete_org_payment_method",
            user_id=actor.id,
        ).error("stripe_org_payment_method_detach_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=actor.id,
            action="org_payment_method_removed",
            target_type="organization",
            target_id=org_id,
            metadata={
                "provider": "stripe",
                "payment_method_ref": _masked_provider_ref(detached_id),
            },
        )

    logger.bind(
        module="financials",
        action="delete_org_payment_method",
        user_id=actor.id,
    ).info("org_payment_method_removed")
    return PaymentMethodDeleteResponse(
        provider="stripe",
        payment_method_id=detached_id,
        removed=True,
    )
