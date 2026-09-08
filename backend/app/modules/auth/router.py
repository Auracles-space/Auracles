"""FastAPI router for auth registration and verification endpoints."""

import secrets
from typing import Annotated
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import Settings, get_settings
from app.core.cookies import (
    OAUTH_STATE_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    clear_oauth_state_cookie,
    clear_refresh_cookie,
    clear_session_hint_cookie,
    read_oauth_state_value,
    set_oauth_state_cookie,
    set_refresh_cookie,
    set_session_hint_cookie,
)
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.network import client_ip
from app.core.profile_images import resolve_profile_image_url
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.integrations.google_oauth import (
    GoogleOAuthError,
    build_authorization_url,
    exchange_code,
    fetch_google_jwks,
    generate_pkce_pair,
    generate_state,
    verify_id_token,
)
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
    TotpSetupRequest,
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
AppSettings = Annotated[Settings, Depends(get_settings)]


def _client_ip(request: Request) -> str | None:
    """Return the originating client IP, honouring a trusted proxy header."""
    return client_ip(request)


def _safe_next_path(next_path: str | None) -> str | None:
    """Return an in-app path safe to redirect to, or None.

    Only same-origin absolute paths are allowed. Protocol-relative (``//host``)
    and external (``https://...``) values are dropped so the OAuth round trip
    cannot be turned into an open redirect.
    """
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return None
    return next_path


GOOGLE_CALLBACK_PATH_FALLBACK = "/api/v1/auth/google/callback"


def _callback_path(settings: Settings) -> str:
    """Return the callback path appended to a frontend origin (from config)."""
    if settings.google_redirect_uri:
        path = urlsplit(settings.google_redirect_uri).path
        if path:
            return path
    return GOOGLE_CALLBACK_PATH_FALLBACK


def _request_frontend_origin(request: Request) -> str | None:
    """Best-effort origin of the frontend that initiated the request.

    Top-level GET navigations usually omit Origin but send Referer; behind the
    Vercel `/api` proxy the original host also arrives as x-forwarded-host.
    """
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        proto = request.headers.get("x-forwarded-proto", "https")
        return f"{proto}://{forwarded_host}"
    return None


def _resolve_redirect_uri(request: Request, settings: Settings) -> str:
    """Resolve the callback URL for the frontend this request came from.

    One backend can serve several frontends (prod + dev/preview). We pick the
    callback on the originating frontend — but only if that origin is in the
    CORS allowlist, so an attacker cannot steer the OAuth callback to an
    arbitrary host. Falls back to the configured GOOGLE_REDIRECT_URI.
    """
    allowed = {origin.rstrip("/") for origin in settings.cors_origin_list}
    origin = _request_frontend_origin(request)
    if origin and origin in allowed:
        return f"{origin}{_callback_path(settings)}"
    return settings.google_redirect_uri or ""


@router.get(
    "/google/start",
    summary="Begin Google sign-in",
    description=(
        "Start the Google OAuth authorization-code flow. Generates CSRF state "
        "and a PKCE pair, seals them in a short-lived HttpOnly cookie, and "
        "redirects the browser to Google's consent screen."
    ),
)
async def google_start(
    request: Request,
    settings: AppSettings,
    next: str | None = None,
    terms: bool = False,
) -> RedirectResponse:
    """Redirect the user to Google's consent screen.

    Generates a fresh CSRF ``state`` and PKCE pair, builds the consent URL, and
    seals ``state`` + the PKCE verifier (and any ``next`` path) into a signed,
    short-lived HttpOnly cookie the callback validates.

    Args:
        settings: Application settings (provides Google client config).
        next: Optional in-app path to resume after sign-in; non-local values
            are dropped to prevent open redirects.
        terms: Whether the user accepted the Terms before starting (set by the
            sign-up entry point); sealed into state and required to create a new
            account at the callback.

    Returns:
        A 302 redirect to Google's authorization endpoint.

    Raises:
        HTTPException(503): If Google OAuth credentials are not configured.
    """
    pkce = generate_pkce_pair()
    state = generate_state()
    redirect_uri = _resolve_redirect_uri(request, settings)
    try:
        authorization_url = build_authorization_url(
            state=state,
            code_challenge=pkce.challenge,
            redirect_uri=redirect_uri,
            settings=settings,
        )
    except GoogleOAuthError:
        logger.bind(module="auth", action="google_start").warning(
            "google_oauth_unconfigured"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is unavailable.",
        ) from None
    response = RedirectResponse(
        url=authorization_url,
        status_code=status.HTTP_302_FOUND,
    )
    set_oauth_state_cookie(
        response,
        state=state,
        verifier=pkce.verifier,
        next_path=_safe_next_path(next),
        terms_accepted=terms,
        redirect_uri=redirect_uri,
        settings=settings,
    )
    logger.bind(module="auth", action="google_start").info("google_login_started")
    return response


def _set_session_hint_from_access_token(
    response: Response, access_token: str, *, persistent: bool = False
) -> None:
    """Set the readable route-hint cookie from freshly issued access claims.

    ``persistent`` must match the refresh cookie's lifetime so the hint and the
    refresh session expire together.
    """
    payload = decode_access_token(access_token)
    set_session_hint_cookie(
        response=response,
        user_id=payload.sub,
        roles=payload.roles,
        totp_verified=payload.totp_verified,
        persistent=persistent,
    )


def _frontend_base_url(settings: Settings, redirect_uri: str | None = None) -> str:
    """Return the frontend origin used to build post-login redirects.

    Derived from the callback's own origin — the exact frontend Google returned
    the user to (sealed in state) — so a single backend serving multiple
    frontends (prod + dev/preview) sends each user back to the origin they signed
    in from. Falls back to the configured GOOGLE_REDIRECT_URI, then CORS, then
    localhost.
    """
    candidate = redirect_uri or settings.google_redirect_uri
    if candidate:
        parts = urlsplit(candidate)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    origins = settings.cors_origin_list
    return origins[0] if origins else "http://localhost:3000"


def _role_landing_path(roles: list[str]) -> str:
    """Mirror the frontend getRoleLandingPath so Google sign-in lands like login.

    Sending users to a role landing (rather than the public home) means they
    arrive inside the authenticated shell, which restores the in-memory access
    token from the refresh cookie — so the header reflects the session.
    """
    if "admin" in roles:
        return "/admin"
    if "attestor" in roles:
        return "/attestor/assignments"
    if "operator" in roles:
        return "/explore"
    if "contributor" in roles:
        return "/dashboard"
    if "developer" in roles:
        return "/dashboard/developer"
    return "/settings/identity"


def _google_redirect_target(
    settings: Settings,
    needs_onboarding: bool,
    roles: list[str],
    next_path: object,
    redirect_uri: str | None = None,
) -> str:
    """Resolve where to send the browser after a successful Google sign-in.

    Roleless / new users go to onboarding; otherwise resume a safe in-app
    ``next`` path, falling back to the user's role landing (never the public
    home, which would render a logged-out header).
    """
    base = _frontend_base_url(settings, redirect_uri)
    if needs_onboarding:
        return f"{base}/settings/onboarding"
    safe_next = _safe_next_path(next_path if isinstance(next_path, str) else None)
    return f"{base}{safe_next or _role_landing_path(roles)}"


@router.get(
    "/google/callback",
    summary="Complete Google sign-in",
    description=(
        "Handle Google's authorization-code redirect: verify CSRF state, "
        "exchange the code, verify the id_token, resolve or create the account, "
        "and issue a session before redirecting back into the app."
    ),
)
async def google_callback(
    request: Request,
    settings: AppSettings,
    db: DatabaseSession,
    redis: RedisClient,
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Complete the Google authorization-code flow and issue a session.

    Verifies the signed state cookie against the returned ``state`` (CSRF),
    exchanges the code with PKCE, verifies the id_token, then resolves the
    account and issues refresh + session-hint cookies. The access token is
    minted by the frontend via ``/auth/refresh`` after the redirect.

    Args:
        request: Incoming request (state cookie, client IP, user agent).
        settings: Application settings (Google config + cookie attributes).
        db: Async DB session.
        redis: Redis for refresh-token storage.
        state: CSRF state echoed back by Google.
        code: Authorization code (absent if the user denied consent).
        error: Google error code when the user denies or consent fails.

    Returns:
        A 302 redirect into the app (onboarding for new users, else resume).

    Raises:
        HTTPException(400): On state mismatch, denied consent, or any Google
            verification failure.
    """
    log = logger.bind(module="auth", action="google_callback")
    payload = read_oauth_state_value(
        request.cookies.get(OAUTH_STATE_COOKIE_NAME), settings=settings
    )
    cookie_state = str(payload.get("state", "")) if payload else ""
    if payload is None or not secrets.compare_digest(cookie_state, state):
        log.warning("oauth_state_invalid")
        await write_audit(
            db=db,
            actor_id=None,
            action="oauth_state_invalid",
            target_type="user",
            metadata={"provider": "google"},
            ip=_client_ip(request),
            ua=request.headers.get("user-agent"),
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sign-in state.",
        )

    if error or not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google sign-in was not completed.",
        )

    # The token exchange must reuse the exact redirect_uri from authorization.
    sealed_redirect = payload.get("redirect_uri")
    redirect_uri = str(sealed_redirect) if isinstance(sealed_redirect, str) else None
    try:
        tokens = await exchange_code(
            code=code,
            code_verifier=str(payload.get("verifier", "")),
            redirect_uri=redirect_uri,
            settings=settings,
        )
        jwks = await fetch_google_jwks(settings=settings)
        claims = verify_id_token(
            str(tokens.get("id_token", "")), settings=settings, jwks=jwks
        )
    except GoogleOAuthError as exc:
        log.warning(
            "google_login_failure",
            error=str(exc),
            cause=str(exc.__cause__) if exc.__cause__ else None,
        )
        # DEBUG(non-prod): expose the underlying reason to diagnose setup.
        detail = "Could not complete Google sign-in."
        if settings.environment != "production":
            detail = f"{detail} [{exc}]"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from None

    result = await service.complete_google_login(
        db=db,
        redis=redis,
        claims=claims,
        terms_accepted=bool(payload.get("terms_accepted")),
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )

    next_value = payload.get("next")
    next_path = _safe_next_path(next_value if isinstance(next_value, str) else None)

    # A 2FA-enabled user must clear TOTP before any session cookie is granted;
    # send them to the same challenge page the password flow uses.
    if result.requires_2fa:
        params = {"challenge": result.challenge_token or ""}
        if next_path:
            params["next"] = next_path
        challenge_url = (
            f"{_frontend_base_url(settings, redirect_uri)}"
            f"/2fa-challenge?{urlencode(params)}"
        )
        response = RedirectResponse(
            url=challenge_url, status_code=status.HTTP_302_FOUND
        )
        clear_oauth_state_cookie(response, settings=settings)
        return response

    assert result.access_token is not None and result.refresh_token is not None
    response = RedirectResponse(
        url=_google_redirect_target(
            settings,
            result.needs_onboarding,
            result.roles,
            next_path,
            redirect_uri,
        ),
        status_code=status.HTTP_302_FOUND,
    )
    set_refresh_cookie(response, result.refresh_token, settings=settings)
    _set_session_hint_from_access_token(response, result.access_token)
    clear_oauth_state_cookie(response, settings=settings)
    return response


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
    return RegisterResponse(
        message=(
            "We've sent a password reset link to your email. "
            "Please check your inbox to reset your password."
        )
    )


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
    login_response, refresh_token, remember_me = await service.login(
        db=db,
        redis=redis,
        email=str(payload.email),
        password=payload.password.get_secret_value(),
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
        remember_me=payload.remember_me,
    )
    if refresh_token:
        set_refresh_cookie(response, refresh_token, persistent=remember_me)
        if login_response.access_token is not None:
            _set_session_hint_from_access_token(
                response, login_response.access_token, persistent=remember_me
            )
    return login_response


@router.post("/refresh", response_model=LoginResponse, response_model_exclude_none=True)
async def refresh(
    request: Request,
    response: Response,
    db: DatabaseSession,
    redis: RedisClient,
) -> LoginResponse:
    """Rotate the refresh cookie and return a new access token."""
    login_response, refresh_token, remember_me = await service.refresh(
        db=db,
        redis=redis,
        token=request.cookies.get(REFRESH_COOKIE_NAME),
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    set_refresh_cookie(response, refresh_token, persistent=remember_me)
    if login_response.access_token is not None:
        _set_session_hint_from_access_token(
            response, login_response.access_token, persistent=remember_me
        )
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
    roles = list(dict.fromkeys(roles))
    # Roles held but not yet usable (attestor awaiting admin approval). Surfaced
    # so the UI can prompt the user to complete or track their application.
    #
    # Subtracting the active roles is what makes "pending" mean pending. Only
    # attestor is gated on approval, so a null ``approved_at`` on any other role
    # carries no meaning — reporting it here described working roles as awaiting
    # approval and let the two lists overlap, which callers then had to undo.
    active_roles = set(roles)
    pending_roles = list(
        dict.fromkeys(
            role
            for role, approved_at in role_rows
            if approved_at is None and role not in active_roles
        )
    )
    return CurrentUserResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        avatar_url=resolve_profile_image_url(current_user.avatar_url),
        roles=roles,
        pending_roles=pending_roles,
        email_verified=current_user.email_verified,
        kyc_status=current_user.kyc_status,
        deactivated_at=current_user.deactivated_at,
        is_superadmin=current_user.is_superadmin,
        has_password=current_user.password_hash is not None,
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
    payload: TotpSetupRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> TotpSetupResponse:
    """Start TOTP setup for the authenticated user.

    Requires the account password when the account has one: enrollment
    replaces the second factor and discards existing backup codes.
    """
    return await service.setup_totp(
        db=db,
        user=current_user,
        password=payload.password,
    )


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
    login_response, refresh_token, remember_me = await service.verify_totp_login(
        db=db,
        redis=redis,
        challenge_token=payload.challenge_token,
        code=payload.code,
        ip=_client_ip(request),
        ua=request.headers.get("user-agent"),
    )
    set_refresh_cookie(response, refresh_token, persistent=remember_me)
    if login_response.access_token is not None:
        _set_session_hint_from_access_token(
            response, login_response.access_token, persistent=remember_me
        )
    return login_response
