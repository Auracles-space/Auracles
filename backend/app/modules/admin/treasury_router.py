"""Admin Treasury endpoints.

Every admin may view Treasury; actions that move money are super-admin only
(treasury decision 9). Logic lives in ``financials.treasury``.

Maps to: platform treasury design §API.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import (
    DatabaseSession,
    require_role,
    require_step_up_after,
    require_superadmin,
)
from app.modules.admin.treasury_schemas import (
    PlatformBankAccountResponse,
    PlatformBankAccountSetRequest,
    TreasurySummaryResponse,
)
from app.modules.auth.models import User
from app.modules.financials import platform_bank_account, treasury

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
