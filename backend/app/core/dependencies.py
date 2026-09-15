"""Shared FastAPI auth and RBAC dependencies."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError  # type: ignore[import-untyped]
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.shared.schemas.token import TokenPayload

bearer_scheme = HTTPBearer(auto_error=False)
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
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


def require_role(*allowed_roles: str) -> Callable[..., object]:
    """Build a dependency that enforces token role claims before route logic.

    Args:
        *allowed_roles: Role claims that grant access.
    """

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


async def require_step_up(
    user: Annotated[User, Depends(get_current_user)],
    redis: RedisClient,
) -> User:
    """Require an open step-up 2FA window before a sensitive write.

    Composed beside the role or organization-role gate on every endpoint in
    the step-up registry (2026-09-13 design): trust, money, identity, and
    privilege changes. The window is opened by ``POST /v1/auth/step-up``; this
    dependency never verifies a code itself.

    Args:
        user: The authenticated user.
        redis: Redis client holding step-up windows.

    Returns:
        The user when a window is open.

    Raises:
        HTTPException(403): ``totp_setup_required`` when 2FA is not enrolled,
            ``step_up_required`` when no window is open.
    """
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "totp_setup_required",
                # The authenticated 2FA enrolment page; /settings/security
                # never existed and 404'd for every user without 2FA.
                "onboarding_url": "/2fa-setup",
                "message": "Enable two-factor authentication before this action.",
            },
        )
    if not await auth_service.has_step_up(redis, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "step_up_required",
                "message": "Confirm with your authenticator app before continuing.",
            },
        )
    return user


def require_step_up_after(
    gate: Callable[..., object],
) -> Callable[..., object]:
    """Compose a role gate with the step-up check, role first.

    FastAPI runs route-level ``dependencies=[...]`` before parameter
    dependencies, so a bare ``require_step_up`` on a route would answer
    ``step_up_required`` to a caller who does not even hold the role, and the
    RBAC denial would never be audited. This wrapper resolves ``gate`` (a
    ``require_role``/``require_org_role`` dependency) first, then requires an
    open window for the user it returns.

    Args:
        gate: The role or organization-role dependency to run first.
    """

    async def checker(
        subject: Annotated[object, Depends(gate)],
        redis: RedisClient,
    ) -> User:
        """Return the user once both the gate and the step-up check pass.

        Role gates return the ``User``; organization-role gates return a
        context object carrying ``.user``. Both shapes are accepted here so
        one composer serves every router.
        """
        user = subject if isinstance(subject, User) else getattr(subject, "user", None)
        if not isinstance(user, User):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Step-up gate received no user.",
            )
        return await require_step_up(user=user, redis=redis)

    return checker


async def require_step_up_if_enrolled(
    user: Annotated[User, Depends(get_current_user)],
    redis: RedisClient,
) -> User:
    """Require an open step-up window only for users who have enrolled in 2FA.

    Used where demanding a factor the account does not possess would lock the
    user out of their own account: email change and GDPR account deletion.
    Enrolled users get the same ``step_up_required`` gate as everywhere else.
    """
    if not user.totp_enabled:
        return user
    return await require_step_up(user=user, redis=redis)


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
