"""Admin Treasury endpoints.

Every admin may view Treasury; actions that move money are super-admin only
(treasury decision 9). Logic lives in ``financials.treasury``.

Maps to: platform treasury design §API.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import (
    DatabaseSession,
    require_role,
    require_step_up_after,
    require_superadmin,
)
from app.modules.admin.treasury_schemas import (
    FeeBackfillResponse,
    PlatformBankAccountResponse,
    PlatformBankAccountSetRequest,
    PlatformWithdrawalItem,
    PlatformWithdrawalRequest,
    PlatformWithdrawalsResponse,
    TreasurySummaryResponse,
    UnrecognizedTransferItem,
    UnrecognizedTransfersResponse,
)
from app.modules.auth.models import User
from app.modules.financials import (
    platform_bank_account,
    platform_withdrawals,
    provider_fee_backfill,
    treasury,
    unrecognized_transfers,
)

router = APIRouter(prefix="/admin/treasury", tags=["Admin Treasury"])

PlatformAdmin = Annotated[User, Depends(require_role("admin"))]
SuperAdmin = Annotated[User, Depends(require_superadmin)]


@router.get(
    "/summary",
    response_model=TreasurySummaryResponse,
    summary="Platform treasury summary (platform admin)",
    description=(
        "Per currency: money owed to users, the platform's own money, the live "
        "Paystack balance, what can be withdrawn now, and the balance gap. "
        "Ledger figures are returned even when Paystack is unavailable."
    ),
)
async def admin_treasury_summary(
    admin: PlatformAdmin, db: DatabaseSession
) -> TreasurySummaryResponse:
    """Return the Treasury summary for every ledger currency."""
    del admin
    return await treasury.get_treasury_summary(db)


@router.get(
    "/bank-account",
    response_model=PlatformBankAccountResponse,
    summary="Platform bank account (platform admin)",
    description=(
        "The active platform bank account: bank, last four digits, the "
        "bank-confirmed account name, and when withdrawals to it open."
    ),
)
async def admin_platform_bank_account(
    admin: PlatformAdmin, db: DatabaseSession
) -> PlatformBankAccountResponse:
    """Return the active platform bank account, or null before one is set."""
    del admin
    return await platform_bank_account.get_platform_bank_account(db)


@router.put(
    "/bank-account",
    response_model=PlatformBankAccountResponse,
    dependencies=[Depends(require_step_up_after(require_superadmin))],
    summary="Set the platform bank account (super-admin)",
    description=(
        "Registers the account with Paystack and makes it the withdrawal "
        "destination after a 24-hour hold. Super-admin only, with step-up. "
        "Audited, and every admin is notified."
    ),
)
async def admin_set_platform_bank_account(
    payload: PlatformBankAccountSetRequest,
    admin: SuperAdmin,
    db: DatabaseSession,
) -> PlatformBankAccountResponse:
    """Set or replace the platform bank account."""
    return await platform_bank_account.set_platform_bank_account(
        db, actor_id=admin.id, payload=payload
    )


@router.get(
    "/withdrawals",
    response_model=PlatformWithdrawalsResponse,
    summary="Platform withdrawal history (platform admin)",
    description="Platform withdrawals newest first, with destination last four only.",
)
async def admin_platform_withdrawals(
    admin: PlatformAdmin,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PlatformWithdrawalsResponse:
    """Return platform withdrawal history."""
    del admin
    return await platform_withdrawals.list_platform_withdrawals(
        db, page=page, page_size=page_size
    )


@router.post(
    "/withdrawals",
    response_model=PlatformWithdrawalItem,
    status_code=202,
    dependencies=[Depends(require_step_up_after(require_superadmin))],
    summary="Withdraw platform money (super-admin)",
    description=(
        "Queues a transfer of platform money to the platform bank account. "
        "Refused above the withdrawable amount (402), below the minimum, while "
        "another withdrawal is in flight (409), or while the bank account is "
        "inside its 24-hour hold. Super-admin only, with step-up."
    ),
)
async def admin_request_platform_withdrawal(
    payload: PlatformWithdrawalRequest,
    admin: SuperAdmin,
    db: DatabaseSession,
) -> PlatformWithdrawalItem:
    """Request a platform withdrawal."""
    return await platform_withdrawals.request_platform_withdrawal(
        db, actor_id=admin.id, payload=payload
    )


@router.get(
    "/unrecognized-transfers",
    response_model=UnrecognizedTransfersResponse,
    summary="Transfers not started by Auracles (platform admin)",
    description=(
        "Provider transfers out of the platform balance that match no payout "
        "or platform withdrawal, unreviewed first."
    ),
)
async def admin_unrecognized_transfers(
    admin: PlatformAdmin,
    db: DatabaseSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UnrecognizedTransfersResponse:
    """Return unrecognized transfers."""
    del admin
    return await unrecognized_transfers.list_unrecognized_transfers(
        db, page=page, page_size=page_size
    )


@router.post(
    "/unrecognized-transfers/{transfer_id}/acknowledge",
    response_model=UnrecognizedTransferItem,
    summary="Mark an unrecognized transfer reviewed (super-admin)",
    description="Records that the super-admin investigated the transfer. Audited.",
)
async def admin_acknowledge_unrecognized_transfer(
    transfer_id: UUID,
    admin: SuperAdmin,
    db: DatabaseSession,
) -> UnrecognizedTransferItem:
    """Mark one unrecognized transfer reviewed."""
    return await unrecognized_transfers.acknowledge_unrecognized_transfer(
        db, transfer_id=transfer_id, actor_id=admin.id
    )


@router.post(
    "/fee-backfill",
    response_model=FeeBackfillResponse,
    status_code=202,
    dependencies=[Depends(require_step_up_after(require_superadmin))],
    summary="Backfill Paystack fees on past charges (super-admin)",
    description=(
        "Queues a one-off lookup of the fee Paystack kept on every settled "
        "charge that has no recorded fee. Safe to rerun. Super-admin only, "
        "with step-up. Audited when requested and when finished."
    ),
)
async def admin_request_fee_backfill(
    admin: SuperAdmin, db: DatabaseSession
) -> FeeBackfillResponse:
    """Queue the Paystack fee backfill."""
    await provider_fee_backfill.request_fee_backfill(db, actor_id=admin.id)
    return FeeBackfillResponse(status="queued")
