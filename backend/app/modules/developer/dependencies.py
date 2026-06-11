"""Developer platform route dependencies.

Developer API routes require both an approved `developer` role claim and an
active Developer account row. Keeping that gate in a dependency prevents later
service methods from each re-implementing account ownership checks.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.modules.auth.models import User
from app.modules.developer.models import DeveloperAccount

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
DeveloperUser = Annotated[User, Depends(require_role("developer"))]


async def require_active_developer_account(
    db: DatabaseSession,
    user: DeveloperUser,
) -> DeveloperAccount:
    """Return the current user's active Developer account or raise 403."""
    account = await db.scalar(
        select(DeveloperAccount).where(
            DeveloperAccount.user_id == user.id,
            DeveloperAccount.status == "active",
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active Developer account required.",
        )
    return account
