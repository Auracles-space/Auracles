"""FastAPI dependencies for Attestation-specific access rules."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.modules.attestation.models import AttestorProfile
from app.modules.auth.models import User

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


async def require_approved_attestor(
    db: DatabaseSession,
    user: Annotated[User, Depends(require_role("attestor"))],
) -> User:
    """Require an authenticated Attestor with an active approved profile."""
    profile_id = await db.scalar(
        select(AttestorProfile.id).where(
            AttestorProfile.user_id == user.id,
            AttestorProfile.active.is_(True),
        )
    )
    if profile_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approved Attestor profile required.",
        )
    return user
