"""Service logic for authenticated account settings."""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.security import generate_opaque_token, hash_token, verify_password
from app.integrations import persona
from app.integrations.persona import PersonaProviderError
from app.modules.auth import service as auth_service
from app.modules.auth.models import IdentityVerification, KycDocument, User
from app.modules.settings.schemas import (
    KycStatusResponse,
    KycVerificationSessionResponse,
    SessionResponse,
    SessionsResponse,
)
from app.workers.tasks.notifications import (
    send_email_change_alert,
    send_email_change_verification,
)

EMAIL_CHANGE_PREFIX = "ec_"
EMAIL_CHANGE_TTL_SECONDS = 86_400

# Cap identity-verification session starts to limit per-check provider cost
# from a single account: five new Persona inquiries per hour per user.
_kyc_session_limiter = RateLimiter("kyc_session", limit=5, window=3600)


def _email_change_key(token: str) -> str:
    """Build the Redis lookup key for a pending account email change."""
    return f"email_change:{hash_token(token)}"


def _redis_text(value: object) -> str:
    """Normalize Redis bytes/strings to text."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


async def start_identity_verification(
    db: AsyncSession,
    redis: Redis,
    user: User,
) -> KycVerificationSessionResponse:
    """Start a Persona identity-verification inquiry for the current user.

    Creates a Persona inquiry tagged with the user id, persists the mapping so
    the signed webhook can resolve the decision, marks the user ``pending``, and
    returns the hosted link the user opens to verify. Rate-limited to cap the
    per-check provider cost a single account can incur.

    Args:
        db: Async DB session.
        redis: Redis client for the rate-limit window.
        user: The authenticated user starting verification.

    Returns:
        The hosted Persona verification URL and inquiry id.

    Raises:
        HTTPException(409): If the user is already verified.
        HTTPException(429): If the per-user session window is exceeded.
        HTTPException(502): If Persona cannot create the inquiry.
    """
    if user.kyc_status == "verified":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity is already verified.",
        )

    await _kyc_session_limiter.check(cast(RedisCounter, redis), str(user.id))

    log = logger.bind(
        module="kyc",
        action="verification_started",
        user_id=user.id,
    )
    try:
        inquiry = await persona.create_inquiry(reference_id=str(user.id))
    except PersonaProviderError as exc:
        log.error("persona_inquiry_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Identity verification provider is unavailable.",
        ) from exc

    db.add(
        IdentityVerification(
            user_id=user.id,
            provider="persona",
            inquiry_id=inquiry.inquiry_id,
            status="created",
        )
    )
    user.kyc_status = "pending"
    await write_audit(
        db=db,
        actor_id=user.id,
        action="kyc_status_change",
        target_type="user",
        target_id=user.id,
        metadata={"status": "pending", "provider": "persona"},
    )
    await db.commit()
    log.info("verification_started")
    return KycVerificationSessionResponse(
        hosted_url=inquiry.hosted_url,
        inquiry_id=inquiry.inquiry_id,
    )


async def get_kyc_status(db: AsyncSession, user: User) -> KycStatusResponse:
    """Return the current user's KYC status and document metadata."""
    documents = (
        (
            await db.execute(
                select(KycDocument)
                .where(KycDocument.user_id == user.id)
                .order_by(desc(KycDocument.created_at))
            )
        )
        .scalars()
        .all()
    )
    return KycStatusResponse(kyc_status=user.kyc_status, documents=list(documents))


async def list_sessions(
    redis: Redis,
    user: User,
    current_refresh_token: str | None,
) -> SessionsResponse:
    """List active refresh-token sessions for the authenticated user."""
    sessions = await auth_service.list_refresh_sessions(
        redis=redis,
        user=user,
        current_token=current_refresh_token,
    )
    return SessionsResponse(
        sessions=[SessionResponse.model_validate(session) for session in sessions]
    )


async def revoke_session(
    db: AsyncSession,
    redis: Redis,
    user: User,
    session_id: str,
    current_refresh_token: str | None,
) -> bool:
    """Revoke a single refresh-token session owned by the authenticated user."""
    revoked = await auth_service.revoke_refresh_session(
        redis=redis,
        user=user,
        session_id=session_id,
    )
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    current = (
        auth_service.refresh_session_id(current_refresh_token) == session_id
        if current_refresh_token
        else False
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="session_revoked",
        target_type="session",
        target_id=user.id,
        metadata={"session_id": session_id, "current": current},
    )
    await db.commit()
    return current


async def revoke_other_sessions(
    db: AsyncSession,
    redis: Redis,
    user: User,
    current_refresh_token: str | None,
) -> int:
    """Revoke every user session except the current browser session."""
    revoked = await auth_service.revoke_other_refresh_sessions(
        redis=redis,
        user=user,
        current_token=current_refresh_token,
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="sessions_revoked",
        target_type="user",
        target_id=user.id,
        metadata={"revoked_count": revoked, "scope": "others"},
    )
    await db.commit()
    return revoked


async def request_email_change(
    db: AsyncSession,
    redis: Redis,
    user: User,
    new_email: str,
    password: str | None,
    totp_code: str | None,
) -> None:
    """Create a new-email verification token after re-authentication.

    Re-auth substitutes the factor the account actually has. Password accounts
    re-authenticate with the account password; passwordless (e.g. Google)
    accounts skip the password and rely on the new-address verification link as
    proof of intent. Accounts with 2FA enabled additionally step up with a
    TOTP/backup code. The current (old) address is notified for awareness.
    """
    normalized_email = auth_service.normalize_email(new_email)
    if normalized_email == user.email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already belongs to this account.",
        )
    existing = await db.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        )

    # Password accounts must re-authenticate; passwordless accounts have no
    # password to demand, so the new-address verification link is the factor.
    if user.password_hash is not None:
        if password is None or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password.",
            )
    # Step up with 2FA only when the account has it; never demand a factor the
    # account does not possess (that would lock the user out of email change).
    if user.totp_enabled:
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=user,
            code=totp_code,
        )

    previous_email = user.email
    token = f"{EMAIL_CHANGE_PREFIX}{generate_opaque_token()}"
    await redis.setex(
        _email_change_key(token),
        EMAIL_CHANGE_TTL_SECONDS,
        json.dumps({"user_id": str(user.id), "new_email": normalized_email}),
    )
    send_email_change_verification.delay(normalized_email, token)
    # Alert the existing address so an unauthorized change can be caught early.
    send_email_change_alert.delay(previous_email, normalized_email)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="email_change_requested",
        target_type="user",
        target_id=user.id,
        metadata={"new_email": normalized_email},
    )
    await db.commit()


async def confirm_email_change(
    db: AsyncSession,
    redis: Redis,
    token: str,
) -> UUID:
    """Confirm a new account email address and revoke all sessions."""
    if not token.startswith(EMAIL_CHANGE_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email-change token.",
        )

    key = _email_change_key(token)
    raw_record = await redis.get(key)
    if raw_record is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Email-change token expired or already used.",
        )

    record = json.loads(_redis_text(raw_record))
    user_id = UUID(str(record["user_id"]))
    new_email = str(record["new_email"])
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or user.deactivated_at is not None:
        await redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Email-change token expired or already used.",
        )

    if await db.scalar(select(User).where(User.email == new_email)) is not None:
        await redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        )

    user.email = new_email
    user.email_verified = True
    await auth_service.revoke_all_user_sessions(redis=redis, user=user)
    await redis.delete(key)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="email_changed",
        target_type="user",
        target_id=user.id,
        metadata={"new_email": new_email},
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        ) from exc
    return user.id
