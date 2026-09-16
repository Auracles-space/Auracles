"""Admin Treasury endpoints.

Every admin may view Treasury; actions that move money are super-admin only
(treasury decision 9). Logic lives in ``financials.treasury``.

Maps to: platform treasury design §API.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import DatabaseSession, require_role
from app.modules.admin.treasury_schemas import TreasurySummaryResponse
from app.modules.auth.models import User
from app.modules.financials import treasury

router = APIRouter(prefix="/admin/treasury", tags=["Admin Treasury"])

PlatformAdmin = Annotated[User, Depends(require_role("admin"))]


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
