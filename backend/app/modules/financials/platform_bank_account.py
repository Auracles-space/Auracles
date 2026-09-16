"""Platform bank account for treasury withdrawals.

The platform's own money is withdrawn to exactly one bank account. Because
redirecting that account is the most valuable change an attacker could make,
setting it is super-admin only behind step-up (enforced by the router), every
change is audited and announced to all admins, and a new account cannot
receive a withdrawal for ``BANK_ACCOUNT_HOLD`` so a hijacked change can be
noticed and reversed first.

Maps to: platform treasury design, decision 3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import encrypt_payout_provider_account_id
from app.integrations import paystack
from app.integrations.paystack import PaystackProviderError
from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.admin.treasury_schemas import (
    PlatformBankAccountItem,
    PlatformBankAccountResponse,
    PlatformBankAccountSetRequest,
)
from app.modules.financials.models import PlatformBankAccount

BANK_ACCOUNT_HOLD = timedelta(hours=24)
# Paystack registers the recipient under this name; the bank-confirmed
# account name it returns is what admins check against.
_RECIPIENT_NAME = "Auracles platform"
_LOCK_KEY = "platform_treasury:bank_account"
_LAGOS = ZoneInfo("Africa/Lagos")


def _item(account: PlatformBankAccount) -> PlatformBankAccountItem:
    """Map a bank account row to its display-safe response."""
    return PlatformBankAccountItem(
        id=account.id,
        bank_name=account.bank_name,
        bank_code=account.bank_code,
        account_last4=account.account_last4,
        account_name=account.account_name,
        usable_from=account.usable_from,
        created_at=account.created_at,
    )


async def active_platform_bank_account(
    db: AsyncSession,
) -> PlatformBankAccount | None:
    """Return the active platform bank account row, if one is set."""
    account: PlatformBankAccount | None = await db.scalar(
        select(PlatformBankAccount).where(PlatformBankAccount.replaced_at.is_(None))
    )
    return account


async def get_platform_bank_account(db: AsyncSession) -> PlatformBankAccountResponse:
    """Return the active platform bank account for display.

    Args:
        db: Async session; read only.

    Returns:
        The active account, or ``bank_account: null`` before one is set.
    """
    account = await active_platform_bank_account(db)
    return PlatformBankAccountResponse(
        bank_account=_item(account) if account is not None else None
    )


async def _bank_name(bank_code: str) -> str:
    """Resolve a bank code to its name from Paystack's live bank list.

    Raises:
        HTTPException(502): Paystack could not list banks.
        HTTPException(422): The code is not a bank Paystack lists.
    """
    try:
        banks = await paystack.list_banks(country="nigeria")
    except PaystackProviderError as exc:
        logger.bind(module="financials", action="set_platform_bank_account").error(
            "platform_bank_list_failed", error=str(exc)
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payout provider is unavailable.",
        ) from exc
    for bank in banks:
        if bank.code == bank_code:
            return bank.name
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "error_code": "unknown_bank_code",
            "message": "Choose a bank from the list.",
        },
    )


async def set_platform_bank_account(
    db: AsyncSession,
    *,
    actor_id: UUID,
    payload: PlatformBankAccountSetRequest,
) -> PlatformBankAccountResponse:
    """Set or replace the platform bank account.

    Paystack resolves the account while creating the transfer recipient, so a
    rejected or unreachable provider stores nothing. The new row starts a
    fresh 24-hour hold even when replacing an account, because the risk is
    the change itself. All admins are notified only after commit.

    Args:
        db: Async session.
        actor_id: The super-admin making the change.
        payload: Ten-digit account number and Paystack bank code.

    Returns:
        The newly active account.

    Raises:
        HTTPException(422): Unknown bank code.
        HTTPException(502): Paystack rejected the account or was unreachable.
    """
    log = logger.bind(
        module="financials", action="set_platform_bank_account", user_id=actor_id
    )
    bank_name = await _bank_name(payload.bank_code)
    try:
        recipient = await paystack.create_transfer_recipient(
            name=_RECIPIENT_NAME,
            account_number=payload.account_number,
            bank_code=payload.bank_code,
            currency="NGN",
        )
    except PaystackProviderError as exc:
        log.error("platform_bank_recipient_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payout provider could not verify this account.",
        ) from exc

    last4 = payload.account_number[-4:]
    now = datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        # Serialize changes so two concurrent requests cannot both find the
        # same previous account and trip the one-active-row index.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": _LOCK_KEY},
        )
        previous = await active_platform_bank_account(db)
        previous_last4 = previous.account_last4 if previous is not None else None
        if previous is not None:
            previous.replaced_at = now
            await db.flush()
        account = PlatformBankAccount(
            provider="paystack",
            bank_code=payload.bank_code,
            bank_name=bank_name,
            account_last4=last4,
            account_name=recipient.account_name,
            recipient_code_encrypted=encrypt_payout_provider_account_id(
                recipient.recipient_code
            ),
            usable_from=now + BANK_ACCOUNT_HOLD,
            created_by=actor_id,
        )
        db.add(account)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="platform_bank_account_changed",
            target_type="platform_bank_account",
            target_id=account.id,
            metadata={
                "previous_last4": previous_last4,
                "new_last4": last4,
                "bank_code": payload.bank_code,
                "usable_from": account.usable_from.isoformat(),
            },
        )
        response = PlatformBankAccountResponse(bank_account=_item(account))

    log.info("platform_bank_account_changed", new_last4=f"****{last4}")
    usable_wat = account.usable_from.astimezone(_LAGOS).strftime("%d %b %Y %H:%M")
    notify_admins_review_pending(
        domain="platform_bank_account",
        target_id=account.id,
        body=(
            f"The platform bank account was changed to {bank_name} ****{last4}. "
            f"Withdrawals to it open at {usable_wat} WAT. If you did not expect "
            "this change, tell the super-admin now."
        ),
        link="/admin/treasury",
    )
    return response
