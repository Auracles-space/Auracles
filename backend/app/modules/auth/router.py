"""FastAPI router for auth registration and verification endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import (
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    clear_session_hint_cookie,
    set_refresh_cookie,
    set_session_hint_cookie,
)
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.network import client_ip
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.modules.auth import service
from app.modules.auth.models import User, UserRole
from app.modules.auth.schemas import (
    AddRoleRequest,
    CurrentUserResponse,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    RoleAssignmentResponse,
    TotpBackupCodesResponse,
    TotpCodeRequest,
    TotpLoginVerifyRequest,
    TotpSetupResponse,
    TotpStatusResponse,
    VerifyEmailRequest,
)
from app.modules.gdpr.dependencies import require_current_consent

router = APIRouter(prefix="/auth", tags=["Auth"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentConsentUser = Annotated[User, Depends(require_current_consent)]


def _client_ip(request: Request) -> str | None:
    """Return the originating client IP, honouring a trusted proxy header."""
    return client_ip(request)


def _set_session_hint_from_access_token(response: Response, access_token: str) -> None:
    """Set the readable route-hint cookie from freshly issued access claims."""
    payload = decode_access_token(access_token)
    set_session_hint_cookie(
        response=response,
        user_id=payload.sub,
        roles=payload.roles,
        totp_verified=payload.totp_verified,
    )


@router.post("/register", response_model=RegisterResponse)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Register a user and send an email verification link."""
    await service.register_user(
        db=db,
        redis=redis,
        request=payload,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    return RegisterResponse()


@router.post("/verify-email", response_model=RegisterResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Verify a user's email address with a one-time token."""
    await service.verify_email(
        db=db,
        redis=redis,
        token=payload.token,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    return RegisterResponse(message="Email verified.")


@router.post("/resend-verification", response_model=RegisterResponse)
async def resend_verification(
    payload: ResendVerificationRequest,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Resend an email verification link without revealing account existence."""
    await service.resend_verification(db=db, redis=redis, email=str(payload.email))
    return RegisterResponse()


@router.post("/forgot-password", response_model=RegisterResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Start password reset without revealing whether the account exists."""
    await service.forgot_password(
        db=db,
        redis=redis,
        email=str(payload.email),
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    return RegisterResponse(message="We've sent a password reset link to your email. Please check your inbox to reset your password.")


@router.post("/reset-password", response_model=RegisterResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Reset a password using a single-use token."""
    await service.reset_password(
        db=db,
        redis=redis,
        token=payload.token,
        new_password=payload.new_password.get_secret_value(),
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    return RegisterResponse(message="Password reset.")


@router.post("/login", response_model=LoginResponse, response_model_exclude_none=True)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
    redis: RedisClient,
) -> LoginResponse:
    """Authenticate a user and set the browser refresh cookie."""
    login_response, refresh_token = await service.login(
        db=db,
        redis=redis,
        email=str(payload.email),
        password=payload.password.get_secret_value(),
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    if refresh_token:
        set_refresh_cookie(response, refresh_token)
        if login_response.access_token is not None:
            _set_session_hint_from_access_token(response, login_response.access_token)
    return login_response


@router.post("/refresh", response_model=LoginResponse, response_model_exclude_none=True)
async def refresh(
    request: Request,
    response: Response,
    db: DatabaseSession,
    redis: RedisClient,
) -> LoginResponse:
    """Rotate the refresh cookie and return a new access token."""
    login_response, refresh_token = await service.refresh(
        db=db,
        redis=redis,
        token=request.cookies.get(REFRESH_COOKIE_NAME),
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    set_refresh_cookie(response, refresh_token)
    if login_response.access_token is not None:
        _set_session_hint_from_access_token(response, login_response.access_token)
    return login_response


@router.post("/logout", response_model=RegisterResponse)
async def logout(
    request: Request,
    response: Response,
    db: DatabaseSession,
    redis: RedisClient,
) -> RegisterResponse:
    """Revoke the current refresh token and clear the browser cookie."""
    await service.logout(
        db=db,
        redis=redis,
        token=request.cookies.get(REFRESH_COOKIE_NAME),
    )
    clear_refresh_cookie(response)
    clear_session_hint_cookie(response)
    return RegisterResponse(message="Logged out.")


@router.get("/me", response_model=CurrentUserResponse)
async def me(current_user: CurrentUser, db: DatabaseSession) -> CurrentUserResponse:
    """Return the authenticated user's public auth profile."""
    role_rows = (
        await db.execute(
            select(UserRole.role, UserRole.approved_at).where(
                UserRole.user_id == current_user.id
            )
        )
    ).all()
    roles = [
        role
        for role, approved_at in role_rows
        if role != "attestor" or approved_at is not None
    ]
    # Roles held but not yet usable (attestor awaiting admin approval). Surfaced
    # so the UI can prompt the user to complete or track their application.
    pending_roles = [
        role for role, approved_at in role_rows if approved_at is None
    ]
    return CurrentUserResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
        roles=roles,
        pending_roles=pending_roles,
        email_verified=current_user.email_verified,
        kyc_status=current_user.kyc_status,
        deactivated_at=current_user.deactivated_at,
        is_superadmin=current_user.is_superadmin,
    )


@router.post("/roles", response_model=RoleAssignmentResponse)
async def add_role(
    payload: AddRoleRequest,
    current_user: CurrentConsentUser,
    db: DatabaseSession,
) -> RoleAssignmentResponse:
    """Self-add a non-privileged role."""
    assigned_role = await service.add_self_role(
        db=db,
        user=current_user,
        role=payload.role,
    )
    return RoleAssignmentResponse(
        user_id=current_user.id,
        role=assigned_role.role,
        approved=assigned_role.approved_at is not None,
    )


@router.get("/2fa/status", response_model=TotpStatusResponse)
async def totp_status(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> TotpStatusResponse:
    """Report 2FA enablement and remaining backup-code count."""
    return await service.get_totp_status(db=db, user=current_user)


@router.post("/2fa/setup", response_model=TotpSetupResponse)
async def setup_totp(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> TotpSetupResponse:
    """Start TOTP setup for the authenticated user."""
    return await service.setup_totp(db=db, user=current_user)


@router.post(
    "/2fa/backup-codes/regenerate",
    response_model=TotpBackupCodesResponse,
)
async def regenerate_backup_codes(
    payload: TotpCodeRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> TotpBackupCodesResponse:
    """Issue a fresh set of backup codes after verifying a current code."""
    backup_codes = await service.regenerate_backup_codes(
        db=db,
        redis=redis,
        user=current_user,
        code=payload.code,
    )
    return TotpBackupCodesResponse(backup_codes=backup_codes)


@router.post("/2fa/verify", response_model=TotpStatusResponse)
async def verify_totp(
    payload: TotpCodeRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> TotpStatusResponse:
    """Enable TOTP after validating the current code."""
    enabled = await service.verify_totp_enable(
        db=db,
        redis=redis,
        user=current_user,
        code=payload.code,
    )
    return TotpStatusResponse(totp_enabled=enabled)


@router.post("/2fa/disable", response_model=TotpStatusResponse)
async def disable_totp(
    payload: TotpCodeRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> TotpStatusResponse:
    """Disable TOTP after validating a current code or backup code."""
    enabled = await service.disable_totp(
        db=db,
        redis=redis,
        user=current_user,
        code=payload.code,
    )
    return TotpStatusResponse(totp_enabled=enabled)


@router.post(
    "/2fa/verify-login",
    response_model=LoginResponse,
    response_model_exclude_none=True,
)
async def verify_totp_login(
    payload: TotpLoginVerifyRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
    redis: RedisClient,
) -> LoginResponse:
    """Trade a valid 2FA login challenge for browser session tokens."""
    login_response, refresh_token = await service.verify_totp_login(
        db=db,
        redis=redis,
        challenge_token=payload.challenge_token,
        code=payload.code,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    set_refresh_cookie(response, refresh_token)
    if login_response.access_token is not None:
        _set_session_hint_from_access_token(response, login_response.access_token)
    return login_response
