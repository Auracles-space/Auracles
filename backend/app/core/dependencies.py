"""Shared FastAPI auth and RBAC dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError  # type: ignore[import-untyped]
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import get_db
from app.core.security import decode_access_token
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.shared.schemas.token import TokenPayload

bearer_scheme = HTTPBearer(auto_error=False)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]


async def get_token_string(credentials: BearerCredentials) -> str:
    """Extract the raw token string from the Authorization header."""
    if credentials is not None:
        return credentials.credentials
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing access token.",
    )


async def get_token_string_allow_query(
    credentials: BearerCredentials,
    token: str | None = Query(
        None, description="Access token via query parameter for download links"
    ),
) -> str:
    """Extract the raw token from the Authorization header or query parameter.

    Query-parameter tokens exist only so browser-navigated redirect downloads
    (which cannot set headers) can authenticate. Wire this dependency solely
    to endpoints that 302 to a short-lived presigned URL — never to general
    API endpoints, so a leaked URL cannot be replayed against the wider API.
    """
    if credentials is not None:
        return credentials.credentials
    if token is not None:
        return token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing access token.",
    )


async def _load_user_from_token(db: AsyncSession, token: str) -> User:
    """Decode an access token and load its active, non-revoked user."""
    try:
        payload = decode_access_token(token)
    except (JWTError, ValidationError) as exc:
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
            detail={
                "error_code": "account_deactivated",
                "message": "Account is deactivated.",
            },
        )
    if user.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "account_suspended",
                "message": "Account is suspended.",
            },
        )
    if auth_service.is_access_token_revoked_for_user(user, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    return user


async def get_current_user(
    db: DatabaseSession,
    token: Annotated[str, Depends(get_token_string)],
) -> User:
    """Load the authenticated user from a bearer access token."""
    return await _load_user_from_token(db, token)


async def get_current_user_allow_query(
    db: DatabaseSession,
    token: Annotated[str, Depends(get_token_string_allow_query)],
) -> User:
    """Load the authenticated user, additionally accepting a query token.

    For browser-navigated redirect-download endpoints only; see
    `get_token_string_allow_query`.
    """
    return await _load_user_from_token(db, token)


def _decode_token_payload(token: str) -> TokenPayload:
    """Decode bearer token claims without loading the user."""
    try:
        return decode_access_token(token)
    except (JWTError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        ) from exc


async def get_current_token_payload(
    token: Annotated[str, Depends(get_token_string)],
) -> TokenPayload:
    """Decode bearer token claims without loading the user."""
    return _decode_token_payload(token)


async def get_current_token_payload_allow_query(
    token: Annotated[str, Depends(get_token_string_allow_query)],
) -> TokenPayload:
    """Decode token claims, additionally accepting a query token.

    For browser-navigated redirect-download endpoints only; see
    `get_token_string_allow_query`.
    """
    return _decode_token_payload(token)


def require_role(
    *allowed_roles: str,
    allow_query_token: bool = False,
) -> Callable[..., object]:
    """Build a dependency that enforces token role claims before route logic.

    Args:
        *allowed_roles: Role claims that grant access.
        allow_query_token: Accept the access token via ``?token=`` as well as
            the Authorization header. Reserve for redirect-download endpoints;
            see `get_token_string_allow_query`.
    """
    user_dependency = (
        get_current_user_allow_query if allow_query_token else get_current_user
    )
    payload_dependency = (
        get_current_token_payload_allow_query
        if allow_query_token
        else get_current_token_payload
    )

    async def checker(
        db: DatabaseSession,
        user: Annotated[User, Depends(user_dependency)],
        payload: Annotated[TokenPayload, Depends(payload_dependency)],
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
                detail={
                    "error_code": "role_required",
                    "onboarding_url": "/settings/onboarding",
                },
            )
        return user

    return checker


async def require_superadmin(
    db: DatabaseSession,
    user: Annotated[User, Depends(require_role("admin"))],
) -> User:
    """Require the authenticated admin to be the protected super-admin.

    Layered on top of the admin role check so platform-level controls (e.g.
    editing platform configuration) are reserved for the bootstrap super-admin.
    Denials are audited like any other RBAC rejection.

    Args:
        db: Async database session for the audit write.
        user: The authenticated admin from the role gate.

    Returns:
        The super-admin user when the flag is set.

    Raises:
        HTTPException(403): If the admin is not a super-admin.
    """
    if not user.is_superadmin:
        await write_audit(
            db=db,
            actor_id=user.id,
            action="access_denied",
            target_type="rbac",
            target_id=user.id,
            metadata={"required": "superadmin"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "superadmin_required"},
        )
    return user


async def require_kyc_verified(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require the authenticated user to have verified KYC status."""
    if user.kyc_status != "verified":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "kyc_required",
                "onboarding_url": "/settings/onboarding",
            },
        )
    return user


async def require_profile_complete(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require the authenticated user to have completed basic profile fields."""
    if not user.display_name.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "profile_required",
                "onboarding_url": "/settings/onboarding",
            },
        )
    return user
