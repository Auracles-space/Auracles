"""Business services for financial transactions and payouts."""

from __future__ import annotations

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials.schemas import (
    PaymentMethodDeleteResponse,
    PaymentMethodResponse,
    PaymentMethodSetupResponse,
    PaymentMethodsResponse,
)


def _masked_provider_ref(provider_ref: str) -> str:
    """Return a log-safe provider reference that preserves only the last chars."""
    return f"****{provider_ref[-4:]}" if len(provider_ref) > 4 else "****"


async def _verify_sensitive_payment_method_change(
    db: AsyncSession,
    redis: Redis,
    operator: User,
    totp_code: str,
) -> None:
    """Require a valid TOTP or backup code before changing payment methods."""
    await auth_service.verify_totp_for_sensitive_action(
        db=db,
        redis=redis,
        user=operator,
        code=totp_code,
    )
    await db.commit()


async def create_payment_method_setup(
    db: AsyncSession,
    redis: Redis,
    operator: User,
    *,
    totp_code: str,
) -> PaymentMethodSetupResponse:
    """Create/reuse a Stripe Customer and return a SetupIntent client secret."""
    operator_id = operator.id
    customer_id = operator.stripe_customer_id

    await _verify_sensitive_payment_method_change(
        db=db,
        redis=redis,
        operator=operator,
        totp_code=totp_code,
    )

    try:
        if customer_id is None:
            customer = await stripe.create_customer(
                email=operator.email,
                name=operator.display_name,
                idempotency_key=f"stripe_customer:{operator_id}",
            )
            customer_id = customer.id
        setup_intent = await stripe.create_setup_intent(customer_id=customer_id)
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="create_payment_method_setup",
            user_id=operator_id,
        ).error("stripe_payment_method_setup_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        if operator.stripe_customer_id is None:
            operator.stripe_customer_id = customer_id
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="payment_method_added",
            target_type="user",
            target_id=operator_id,
            metadata={
                "provider": "stripe",
                "setup_intent_ref": _masked_provider_ref(setup_intent.id),
            },
        )

    logger.bind(
        module="financials",
        action="create_payment_method_setup",
        user_id=operator_id,
    ).info("payment_method_added")
    return PaymentMethodSetupResponse(
        provider="stripe",
        setup_intent_id=setup_intent.id,
        client_secret=setup_intent.client_secret,
    )


async def list_payment_methods(
    db: AsyncSession,
    operator: User,
) -> PaymentMethodsResponse:
    """Return safe metadata for the Operator's provider-held payment methods."""
    del db
    customer_id = operator.stripe_customer_id
    if customer_id is None:
        return PaymentMethodsResponse(payment_methods=[])

    try:
        payment_methods = await stripe.list_payment_methods(customer_id=customer_id)
    except StripeProviderError as exc:
        logger.bind(
            module="financials",
            action="list_payment_methods",
            user_id=operator.id,
        ).error("stripe_payment_method_list_failed", error=str(exc))
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


async def delete_payment_method(
    db: AsyncSession,
    redis: Redis,
    operator: User,
    *,
    payment_method_id: str,
    totp_code: str,
) -> PaymentMethodDeleteResponse:
    """Detach a provider-held payment method after TOTP and ownership checks."""
    customer_id = operator.stripe_customer_id
    if customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment method not found.",
        )

    await _verify_sensitive_payment_method_change(
        db=db,
        redis=redis,
        operator=operator,
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
            action="delete_payment_method",
            user_id=operator.id,
        ).error("stripe_payment_method_detach_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await write_audit(
            db=db,
            actor_id=operator.id,
            action="payment_method_removed",
            target_type="user",
            target_id=operator.id,
            metadata={
                "provider": "stripe",
                "payment_method_ref": _masked_provider_ref(detached_id),
            },
        )

    logger.bind(
        module="financials",
        action="delete_payment_method",
        user_id=operator.id,
    ).info("payment_method_removed")
    return PaymentMethodDeleteResponse(
        provider="stripe",
        payment_method_id=detached_id,
        removed=True,
    )
