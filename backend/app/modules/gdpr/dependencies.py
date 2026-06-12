"""FastAPI dependencies for GDPR consent gates."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.gdpr import consent_service

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_current_consent(
    user: CurrentUser,
    db: DatabaseSession,
) -> User:
    """Require acceptance of the current legal document versions."""
    missing_documents = await consent_service.get_missing_current_consents(
        db=db,
        user_id=user.id,
    )
    if missing_documents:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "consent_required",
                "onboarding_url": "/settings/consent",
                "missing_documents": missing_documents,
            },
        )
    return user
