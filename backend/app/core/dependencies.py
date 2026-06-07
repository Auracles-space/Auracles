"""Shared FastAPI auth and RBAC dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.auth.models import User
from app.shared.schemas.token import TokenPayload

bearer_scheme = HTTPBearer(auto_error=False)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]


async def get_current_user(
    db: DatabaseSession,
    credentials: BearerCredentials,
) -> User:
    """Load the authenticated user from a bearer access token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing access token.",
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        ) from exc

    user = await db.scalar(select(User).where(User.id == payload.sub))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )
    if user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    return user


async def get_current_token_payload(
    credentials: BearerCredentials,
) -> TokenPayload:
    """Decode bearer token claims without loading the user."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing access token.",
        )
    try:
        return decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        ) from exc


def require_role(*allowed_roles: str) -> Callable[..., object]:
    """Build a dependency that enforces token role claims before route logic."""

    async def checker(
        db: DatabaseSession,
        user: Annotated[User, Depends(get_current_user)],
        payload: Annotated[TokenPayload, Depends(get_current_token_payload)],
    ) -> User:
        """Return the current user when one of the allowed roles is present."""
        if not set(payload.roles).intersection(allowed_roles):
            await write_audit(
                db=db,
                actor_id=user.id,
                action="access_denied",
                target_type="rbac",
                target_id=user.id,
                metadata={
                    "required_roles": list(allowed_roles),
                    "token_roles": payload.roles,
                },
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return user

    return checker
