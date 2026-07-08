"""Auth service layer for registration and email verification.

This module also centralizes session-state enforcement decisions such as
account deactivation, suspension, and access-token revocation cutoffs.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from base64 import b64encode
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

import pyotp
import qrcode
from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.security import (
    create_access_token,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.integrations.google_oauth import GoogleClaims
from app.modules.auth.models import OAuthAccount, User, UserBackupCode, UserRole
from app.modules.auth.schemas import (
    LoginResponse,
    RegisterRequest,
    TotpSetupResponse,
    TotpStatusResponse,
)
from app.modules.gdpr import consent_service
from app.shared.schemas.token import TokenPayload
from app.workers.tasks.notifications import (
    send_new_device_email,
    send_password_reset_email,
    send_verification_email,
)

VERIFY_EMAIL_PREFIX = "ev_"
VERIFY_EMAIL_TTL_SECONDS = 86_400
PASSWORD_RESET_PREFIX = "pr_"
PASSWORD_RESET_TTL_SECONDS = 900
RESEND_VERIFICATION_LIMITER = RateLimiter(
    namespace="resend_verification",
    limit=3,
    window=3_600,
)
LOGIN_IP_LIMITER = RateLimiter(namespace="login_ip", limit=20, window=60)
FORGOT_PASSWORD_IP_LIMITER = RateLimiter(
    namespace="forgot_password_ip",
    limit=10,
    window=3_600,
)
FORGOT_PASSWORD_EMAIL_LIMITER = RateLimiter(
    namespace="forgot_password_email",
    limit=3,
    window=3_600,
)
RESET_PASSWORD_IP_LIMITER = RateLimiter(
    namespace="reset_password_ip",
    limit=10,
    window=3_600,
)
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 900
REFRESH_TOKEN_TTL_SECONDS = 2_592_000
KNOWN_DEVICE_TTL_SECONDS = 2_592_000
TOTP_CHALLENGE_TTL_SECONDS = 300
TOTP_FAILURE_LIMIT = 5
TOTP_FAILURE_WINDOW_SECONDS = 300
TOTP_ISSUER_NAME = "Auracles"


def normalize_email(email: str) -> str:
    """Normalize email addresses before persistence and lookup."""
    return email.strip().lower()


def _verification_key(token: str) -> str:
    """Build the Redis lookup key for a verification token."""
    return f"email_verify:{hash_token(token)}"


def _password_reset_key(token: str) -> str:
    """Build the Redis lookup key for a password reset token."""
    return f"password_reset:{hash_token(token)}"


def _refresh_key(token: str) -> str:
    """Build the Redis lookup key for a refresh token."""
    return f"refresh:{hash_token(token)}"


def refresh_session_id(token: str) -> str:
    """Return the stable public session id for a refresh token."""
    return hash_token(token)


def _refresh_key_from_session_id(session_id: str) -> str:
    """Build the Redis refresh key from a public session id."""
    return f"refresh:{session_id}"


def _used_refresh_key(token: str) -> str:
    """Build the Redis replay-detection key for a used refresh token."""
    return f"refresh_used:{hash_token(token)}"


def _family_key(family_id: str) -> str:
    """Build the Redis set key tracking a refresh-token family."""
    return f"refresh_family:{family_id}"


def _user_refresh_key(user_id: UUID) -> str:
    """Build the Redis set key tracking all refresh tokens for a user."""
    return f"refresh_user:{user_id}"


def _known_devices_key(user_id: UUID) -> str:
    """Build the Redis set key tracking known device fingerprints."""
    return f"known_devices:{user_id}"


def _login_failure_key(email: str) -> str:
    """Build the Redis failed-login counter key."""
    return f"login_failure:{email}"


def _totp_challenge_key(token: str) -> str:
    """Build the Redis key for a pending 2FA login challenge."""
    return f"2fa_challenge:{hash_token(token)}"


def _totp_failure_key(user_id: UUID) -> str:
    """Build the Redis failed-2FA counter key."""
    return f"2fa_failure:{user_id}"


def _backup_code_hash(code: str) -> str:
    """Normalize and hash a backup code for lookup."""
    return hash_token(code.strip().lower())


def _ip_device_prefix(ip: str | None) -> str:
    """Return the IPv4 /24 prefix used for coarse device fingerprinting."""
    if ip is None:
        return "unknown"
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(parsed, ipaddress.IPv4Address):
        octets = ip.split(".")
        return ".".join(octets[:3])
    return parsed.exploded


def _device_fingerprint(ip: str | None, ua: str | None) -> str:
    """Hash coarse network and user-agent data into a device fingerprint."""
    raw = f"{_ip_device_prefix(ip)}:{ua or 'unknown'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _redis_text(value: Any) -> str:
    """Normalize Redis bytes/strings to text for JSON parsing and key work."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def access_token_issued_at_ms(payload: TokenPayload) -> int:
    """Return the access-token issued-at time in milliseconds."""
    if payload.iat_ms is not None:
        return payload.iat_ms
    return payload.iat * 1000


def is_access_token_revoked_for_user(user: User, payload: TokenPayload) -> bool:
    """Return whether a user-level cutoff invalidates one access token."""
    if user.access_revoked_before is None:
        return False
    revoked_before_ms = int(user.access_revoked_before.timestamp() * 1000)
    return access_token_issued_at_ms(payload) < revoked_before_ms


def _session_id_from_refresh_key(key: str) -> str:
    """Extract the public session id from a Redis refresh key."""
    return key.split(":", 1)[1]


def _qr_png_base64(provisioning_uri: str) -> str:
    """Render an otpauth provisioning URI as a base64 PNG."""
    image = qrcode.make(provisioning_uri)
    buffer = BytesIO()
    image.save(buffer)
    return b64encode(buffer.getvalue()).decode("ascii")


async def _ensure_totp_not_locked(redis: Redis, user_id: UUID) -> None:
    """Reject verification when recent wrong-code attempts exceeded the limit."""
    attempts = int(await redis.get(_totp_failure_key(user_id)) or "0")
    if attempts >= TOTP_FAILURE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many 2FA attempts.",
        )


async def _record_totp_failure(redis: Redis, user_id: UUID) -> None:
    """Increment the wrong-code counter for a user."""
    key = _totp_failure_key(user_id)
    attempts = await redis.incr(key)
    if attempts == 1 or await redis.ttl(key) < 0:
        await redis.expire(key, TOTP_FAILURE_WINDOW_SECONDS)


async def _clear_totp_failures(redis: Redis, user_id: UUID) -> None:
    """Clear the wrong-code counter after successful verification."""
    await redis.delete(_totp_failure_key(user_id))


async def _load_active_roles(db: AsyncSession, user_id: UUID) -> list[str]:
    """Load roles that should be encoded into access tokens."""
    rows = (
        await db.execute(
            select(UserRole.role, UserRole.approved_at).where(
                UserRole.user_id == user_id
            )
        )
    ).all()
    return [
        role
        for role, approved_at in rows
        if role != "attestor" or approved_at is not None
    ]


async def _store_refresh_token(
    redis: Redis,
    token: str,
    user_id: UUID,
    family_id: str,
    ip: str | None,
    ua: str | None,
    totp_verified: bool = False,
) -> None:
    """Store refresh-token metadata and index it by family."""
    now = datetime.now(UTC).isoformat()
    key = _refresh_key(token)
    record = {
        "user_id": str(user_id),
        "family_id": family_id,
        "issued_at": now,
        "last_seen": now,
        "ip": ip,
        "user_agent": ua,
        "totp_verified": totp_verified,
    }
    await redis.setex(key, REFRESH_TOKEN_TTL_SECONDS, json.dumps(record))
    await cast(Awaitable[int], redis.sadd(_family_key(family_id), key))
    await redis.expire(_family_key(family_id), REFRESH_TOKEN_TTL_SECONDS)
    await cast(Awaitable[int], redis.sadd(_user_refresh_key(user_id), key))
    await redis.expire(_user_refresh_key(user_id), REFRESH_TOKEN_TTL_SECONDS)


async def list_refresh_sessions(
    redis: Redis,
    user: User,
    current_token: str | None,
) -> list[dict[str, Any]]:
    """Return active refresh-token sessions for the authenticated user."""
    user_key = _user_refresh_key(user.id)
    current_id = refresh_session_id(current_token) if current_token else None
    sessions: list[dict[str, Any]] = []
    members = await cast(Awaitable[set[Any]], redis.smembers(user_key))

    for member in members:
        key = _redis_text(member)
        raw_record = await redis.get(key)
        if raw_record is None:
            await cast(Awaitable[int], redis.srem(user_key, key))
            continue
        record = json.loads(_redis_text(raw_record))
        if str(record.get("user_id")) != str(user.id):
            continue
        session_id = _session_id_from_refresh_key(key)
        sessions.append(
            {
                "id": session_id,
                "ip": record.get("ip"),
                "user_agent": record.get("user_agent"),
                "last_seen": record.get("last_seen"),
                "created_at": record.get("issued_at"),
                "current": session_id == current_id,
            }
        )

    return sorted(sessions, key=lambda item: str(item["created_at"]), reverse=True)


async def revoke_refresh_session(
    redis: Redis,
    user: User,
    session_id: str,
) -> bool:
    """Revoke one refresh-token session owned by the authenticated user."""
    key = _refresh_key_from_session_id(session_id)
    raw_record = await redis.get(key)
    if raw_record is None:
        return False

    record = json.loads(_redis_text(raw_record))
    if str(record.get("user_id")) != str(user.id):
        return False

    await cast(Awaitable[int], redis.srem(_family_key(str(record["family_id"])), key))
    await cast(Awaitable[int], redis.srem(_user_refresh_key(user.id), key))
    await redis.delete(key)
    return True


async def revoke_other_refresh_sessions(
    redis: Redis,
    user: User,
    current_token: str | None,
) -> int:
    """Revoke every user refresh session except the current browser session."""
    current_id = refresh_session_id(current_token) if current_token else None
    removed = 0
    for session in await list_refresh_sessions(redis, user, current_token):
        if session["id"] == current_id:
            continue
        removed += int(await revoke_refresh_session(redis, user, str(session["id"])))
    return removed


async def revoke_all_user_sessions(redis: Redis, user: User) -> None:
    """Revoke every refresh-token session for a user."""
    await _revoke_user_sessions(redis, user.id)


async def _revoke_family(redis: Redis, family_id: str) -> None:
    """Delete every refresh token in a replay-suspect family."""
    family_key = _family_key(family_id)
    members = await cast(Awaitable[set[Any]], redis.smembers(family_key))
    keys = [str(member) for member in members]
    if keys:
        await redis.delete(*keys)
    await redis.delete(family_key)


async def _revoke_user_sessions(redis: Redis, user_id: UUID) -> None:
    """Delete every refresh token tracked for a user."""
    user_key = _user_refresh_key(user_id)
    members = await cast(Awaitable[set[Any]], redis.smembers(user_key))
    keys = [str(member) for member in members]
    for key in keys:
        raw_record = await redis.get(key)
        if raw_record is not None:
            record = json.loads(_redis_text(raw_record))
            await cast(
                Awaitable[int],
                redis.srem(_family_key(str(record["family_id"])), key),
            )
    if keys:
        await redis.delete(*keys)
    await redis.delete(user_key)


async def _record_new_device_if_needed(
    db: AsyncSession,
    redis: Redis,
    user: User,
    ip: str | None,
    ua: str | None,
) -> None:
    """Dispatch a notification when a login fingerprint is new for the user."""
    key = _known_devices_key(user.id)
    fingerprint = _device_fingerprint(ip, ua)
    known = await cast(Awaitable[set[Any]], redis.smembers(key))
    if fingerprint not in {str(member) for member in known}:
        send_new_device_email.delay(user.email, ip, ua)
        await write_audit(
            db=db,
            actor_id=user.id,
            action="new_device_login",
            target_type="user",
            target_id=user.id,
            metadata={"device_fingerprint": fingerprint},
            ip=ip,
            ua=ua,
        )
    await cast(Awaitable[int], redis.sadd(key, fingerprint))
    await redis.expire(key, KNOWN_DEVICE_TTL_SECONDS)


async def register_user(
    db: AsyncSession,
    redis: Redis,
    request: RegisterRequest,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    """Register a user and dispatch an email verification token."""
    email = normalize_email(str(request.email))
    log = logger.bind(module="auth", action="register_user")

    user = User(
        email=email,
        password_hash=hash_password(request.password.get_secret_value()),
        display_name=request.display_name.strip(),
    )

    try:
        async with db.begin():
            db.add(user)
            await db.flush()
            for role in request.roles:
                db.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=None if role == "attestor" else datetime.now(UTC),
                    )
                )
            await write_audit(
                db=db,
                actor_id=user.id,
                action="register_success",
                target_type="user",
                target_id=user.id,
                metadata={"roles": list(request.roles)},
                ip=ip,
                ua=ua,
            )
            await consent_service.record_current_consents(
                db=db,
                user_id=user.id,
                ip=ip,
                ua=ua,
            )
    except IntegrityError:
        await db.rollback()
        log.info("register_duplicate_attempt", email=email)
        await write_audit(
            db=db,
            actor_id=None,
            action="register_duplicate_attempt",
            target_type="user",
            metadata={"email": email},
            ip=ip,
            ua=ua,
        )
        await db.commit()
        return

    token = f"{VERIFY_EMAIL_PREFIX}{generate_opaque_token()}"
    await redis.setex(_verification_key(token), VERIFY_EMAIL_TTL_SECONDS, str(user.id))
    send_verification_email.delay(email, token)
    log.bind(user_id=user.id).info("register_success")


async def verify_email(
    db: AsyncSession,
    redis: Redis,
    token: str,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    """Verify an email address using a Redis-backed one-time token."""
    if not token.startswith(VERIFY_EMAIL_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token.",
        )

    key = _verification_key(token)
    user_id = await redis.get(key)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Verification token expired or already used.",
        )

    parsed_user_id = UUID(str(user_id))
    async with db.begin():
        user = await db.scalar(select(User).where(User.id == parsed_user_id))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification token.",
            )
        user.email_verified = True
        await write_audit(
            db=db,
            actor_id=user.id,
            action="email_verified",
            target_type="user",
            target_id=user.id,
            ip=ip,
            ua=ua,
        )

    await redis.delete(key)


async def resend_verification(
    db: AsyncSession,
    redis: Redis,
    email: str,
) -> None:
    """Resend verification when the user exists and remains unverified."""
    normalized_email = normalize_email(email)
    await RESEND_VERIFICATION_LIMITER.check(cast(RedisCounter, redis), normalized_email)
    user = await db.scalar(select(User).where(User.email == normalized_email))
    if user is None or user.email_verified:
        return

    token = f"{VERIFY_EMAIL_PREFIX}{generate_opaque_token()}"
    await redis.setex(_verification_key(token), VERIFY_EMAIL_TTL_SECONDS, str(user.id))
    send_verification_email.delay(normalized_email, token)


async def forgot_password(
    db: AsyncSession,
    redis: Redis,
    email: str,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    """Start a no-enumeration password reset flow."""
    normalized_email = normalize_email(email)
    await FORGOT_PASSWORD_IP_LIMITER.check(cast(RedisCounter, redis), ip or "unknown")
    await FORGOT_PASSWORD_EMAIL_LIMITER.check(
        cast(RedisCounter, redis),
        normalized_email,
    )
    user = await db.scalar(select(User).where(User.email == normalized_email))
    if user is None or user.deactivated_at is not None:
        return

    token = f"{PASSWORD_RESET_PREFIX}{generate_opaque_token()}"
    await redis.setex(
        _password_reset_key(token),
        PASSWORD_RESET_TTL_SECONDS,
        str(user.id),
    )
    send_password_reset_email.delay(normalized_email, token)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="password_reset_requested",
        target_type="user",
        target_id=user.id,
        ip=ip,
        ua=ua,
    )
    await db.commit()


async def reset_password(
    db: AsyncSession,
    redis: Redis,
    token: str,
    new_password: str,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    """Consume a password reset token and revoke the user's sessions."""
    await RESET_PASSWORD_IP_LIMITER.check(cast(RedisCounter, redis), ip or "unknown")
    if not token.startswith(PASSWORD_RESET_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid password reset token.",
        )

    key = _password_reset_key(token)
    raw_user_id = await redis.get(key)
    if raw_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Password reset token expired or already used.",
        )

    user_id = UUID(str(raw_user_id))
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or user.deactivated_at is not None:
        await redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Password reset token expired or already used.",
        )

    user.password_hash = hash_password(new_password)
    await _revoke_user_sessions(redis, user.id)
    await redis.delete(key)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="password_reset",
        target_type="user",
        target_id=user.id,
        ip=ip,
        ua=ua,
    )
    await db.commit()


async def login(
    db: AsyncSession,
    redis: Redis,
    email: str,
    password: str,
    ip: str | None = None,
    ua: str | None = None,
) -> tuple[LoginResponse, str]:
    """Authenticate a verified user and issue access plus refresh tokens."""
    normalized_email = normalize_email(email)
    await LOGIN_IP_LIMITER.check(cast(RedisCounter, redis), ip or "unknown")
    failure_key = _login_failure_key(normalized_email)
    if int(await redis.get(failure_key) or "0") >= LOGIN_FAILURE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts.",
        )

    user = await db.scalar(select(User).where(User.email == normalized_email))
    if (
        user is None
        or user.password_hash is None
        or not verify_password(password, user.password_hash)
    ):
        attempts = await redis.incr(failure_key)
        if attempts == 1 or await redis.ttl(failure_key) < 0:
            await redis.expire(failure_key, LOGIN_FAILURE_WINDOW_SECONDS)
        await write_audit(
            db=db,
            actor_id=user.id if user else None,
            action="login_failure",
            target_type="user",
            target_id=user.id if user else None,
            metadata={"reason": "invalid_credentials"},
            ip=ip,
            ua=ua,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )
    if user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    if user.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended.",
        )

    await redis.delete(failure_key)
    await _record_new_device_if_needed(db, redis, user, ip, ua)
    if user.totp_enabled:
        challenge_token = generate_opaque_token()
        await redis.setex(
            _totp_challenge_key(challenge_token),
            TOTP_CHALLENGE_TTL_SECONDS,
            str(user.id),
        )
        await db.commit()
        return LoginResponse(
            requires_2fa=True,
            challenge_token=challenge_token,
        ), ""

    roles = await _load_active_roles(db, user.id)
    access_token = create_access_token(
        user_id=user.id,
        roles=roles,
        totp_verified=False,
    )
    refresh_token = generate_opaque_token()
    family_id = str(uuid4())
    await _store_refresh_token(
        redis,
        refresh_token,
        user.id,
        family_id,
        ip,
        ua,
        totp_verified=False,
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="login_success",
        target_type="user",
        target_id=user.id,
        ip=ip,
        ua=ua,
    )
    await db.commit()
    return LoginResponse(access_token=access_token), refresh_token


GOOGLE_PROVIDER = "google"


@dataclass(frozen=True)
class GoogleLoginResult:
    """Outcome of a Google sign-in: the issued session or a pending 2FA step."""

    user: User
    needs_onboarding: bool
    roles: list[str]
    access_token: str | None = None
    refresh_token: str | None = None
    requires_2fa: bool = False
    challenge_token: str | None = None


def _display_name_from_claims(claims: GoogleClaims) -> str:
    """Derive a non-empty display name (<=100 chars) from Google claims."""
    name = (claims.name or "").strip()
    if not name:
        name = claims.email.split("@", 1)[0]
    return name[:100]


async def complete_google_login(
    db: AsyncSession,
    redis: Redis,
    claims: GoogleClaims,
    terms_accepted: bool = False,
    ip: str | None = None,
    ua: str | None = None,
) -> GoogleLoginResult:
    """Resolve (or create) the account for verified Google claims and issue a session.

    Resolution order: existing Google link -> verified-email auto-link ->
    new passwordless user. An unverified Google email never auto-links
    (account-linking trust). Deactivated/suspended accounts are refused before
    any write occurs.

    Args:
        db: Async DB session.
        redis: Redis for refresh-token storage.
        claims: Verified Google identity claims (sub, email, email_verified, name).
        ip: Originating client IP for audit.
        ua: Originating user agent for audit.

    Returns:
        GoogleLoginResult with the user, freshly issued tokens, and whether the
        user still needs onboarding (no active role).

    Raises:
        HTTPException(400): If the Google email is unverified but matches an
            existing account (cannot safely auto-link), a link is orphaned, or a
            new account would be created without accepting the Terms.
        HTTPException(403): If the resolved account is deactivated or suspended.
    """
    normalized_email = normalize_email(claims.email)
    log = logger.bind(module="auth", action="complete_google_login")

    link = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == GOOGLE_PROVIDER,
            OAuthAccount.provider_id == claims.sub,
        )
    )

    user: User | None
    action: str
    if link is not None:
        user = await db.get(User, link.user_id)
        if user is None:  # defensive: orphaned link row
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not complete Google sign-in (orphaned link).",
            )
        action = "google_login_success"
    else:
        user = await db.scalar(select(User).where(User.email == normalized_email))
        if user is not None and not claims.email_verified:
            # An unverified Google email could be attacker-controlled; never link.
            await write_audit(
                db=db,
                actor_id=user.id,
                action="google_login_failure",
                target_type="user",
                target_id=user.id,
                metadata={"reason": "unverified_email_link_attempt"},
                ip=ip,
                ua=ua,
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not complete Google sign-in (email unverified).",
            )
        action = (
            "google_account_linked" if user is not None else "google_account_created"
        )

    # Refuse blocked accounts before writing the link / creating the user.
    if user is not None and user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    if user is not None and user.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended.",
        )

    if action == "google_account_created":
        # A new account must accept the Terms + Privacy Policy, exactly as the
        # email/password registration form requires before creating an account.
        if not terms_accepted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You must accept the Terms of Service and Privacy Policy.",
            )
        user = User(
            email=normalized_email,
            password_hash=None,
            display_name=_display_name_from_claims(claims),
            email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(
            OAuthAccount(
                user_id=user.id, provider=GOOGLE_PROVIDER, provider_id=claims.sub
            )
        )
        await consent_service.record_current_consents(
            db=db, user_id=user.id, ip=ip, ua=ua
        )
    elif action == "google_account_linked":
        assert user is not None
        db.add(
            OAuthAccount(
                user_id=user.id, provider=GOOGLE_PROVIDER, provider_id=claims.sub
            )
        )

    assert user is not None
    roles = await _load_active_roles(db, user.id)

    # Google proves the first factor; a user who turned on TOTP must still clear
    # it before a session issues. Mirror the password-login 2FA challenge — the
    # account link/creation persists, but no tokens are minted yet.
    if user.totp_enabled:
        challenge_token = generate_opaque_token()
        await redis.setex(
            _totp_challenge_key(challenge_token),
            TOTP_CHALLENGE_TTL_SECONDS,
            str(user.id),
        )
        await write_audit(
            db=db,
            actor_id=user.id,
            action=action,
            target_type="user",
            target_id=user.id,
            metadata={"provider": GOOGLE_PROVIDER, "requires_2fa": True},
            ip=ip,
            ua=ua,
        )
        await db.commit()
        log.info("google_login_2fa_required", user_id=str(user.id))
        return GoogleLoginResult(
            user=user,
            needs_onboarding=len(roles) == 0,
            roles=roles,
            requires_2fa=True,
            challenge_token=challenge_token,
        )

    access_token = create_access_token(
        user_id=user.id, roles=roles, totp_verified=False
    )
    refresh_token = generate_opaque_token()
    family_id = str(uuid4())
    await _store_refresh_token(
        redis, refresh_token, user.id, family_id, ip, ua, totp_verified=False
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action=action,
        target_type="user",
        target_id=user.id,
        metadata={"provider": GOOGLE_PROVIDER},
        ip=ip,
        ua=ua,
    )
    await db.commit()
    log.info("google_login_completed", user_id=str(user.id))
    return GoogleLoginResult(
        user=user,
        needs_onboarding=len(roles) == 0,
        roles=roles,
        access_token=access_token,
        refresh_token=refresh_token,
    )


async def refresh(
    db: AsyncSession,
    redis: Redis,
    token: str | None,
    ip: str | None = None,
    ua: str | None = None,
) -> tuple[LoginResponse, str]:
    """Rotate a refresh token and issue a new access token."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token.",
        )

    key = _refresh_key(token)
    raw_record = await redis.get(key)
    if raw_record is None:
        used_family_id = await redis.get(_used_refresh_key(token))
        if used_family_id is not None:
            family_id_str = str(used_family_id)
            # Resolve user from any remaining family member before revocation so
            # the audit row carries actor_id when possible; the family is then
            # revoked and a CRITICAL-level security event is persisted (spec
            # Phase 1 Slice 4: refresh_token_reuse_detected).
            actor_id: UUID | None = None
            token_suffix = _refresh_key(token)[-12:]
            family_members = await cast(
                Awaitable[set[Any]],
                redis.smembers(_family_key(family_id_str)),
            )
            for member in family_members:
                member_key = str(member)
                member_record = await redis.get(member_key)
                if member_record is None:
                    continue
                try:
                    actor_id = UUID(json.loads(_redis_text(member_record))["user_id"])
                    break
                except (KeyError, ValueError):
                    continue
            await _revoke_family(redis, family_id_str)
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="refresh_token_reuse_detected",
                target_type="user" if actor_id else "system",
                target_id=actor_id,
                metadata={
                    "family_id": family_id_str,
                    "token_key_suffix": token_suffix,
                    "family_revoked": True,
                },
                ip=ip,
                ua=ua,
            )
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        )

    record = json.loads(_redis_text(raw_record))
    user_id = UUID(record["user_id"])
    family_id = str(record["family_id"])
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or user.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        )
    if user.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended.",
        )

    roles = await _load_active_roles(db, user.id)
    access_token = create_access_token(
        user_id=user.id,
        roles=roles,
        totp_verified=bool(record.get("totp_verified", False)),
    )
    new_refresh_token = generate_opaque_token()
    await redis.delete(key)
    await cast(Awaitable[int], redis.srem(_family_key(family_id), key))
    await cast(Awaitable[int], redis.srem(_user_refresh_key(user.id), key))
    await redis.setex(_used_refresh_key(token), REFRESH_TOKEN_TTL_SECONDS, family_id)
    await _store_refresh_token(
        redis,
        new_refresh_token,
        user.id,
        family_id,
        ip,
        ua,
        totp_verified=bool(record.get("totp_verified", False)),
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="token_refresh",
        target_type="user",
        target_id=user.id,
        ip=ip,
        ua=ua,
    )
    await db.commit()
    return LoginResponse(access_token=access_token), new_refresh_token


async def logout(
    db: AsyncSession,
    redis: Redis,
    token: str | None,
) -> None:
    """Revoke the current refresh token if one was provided."""
    if token is None:
        return
    key = _refresh_key(token)
    raw_record = await redis.get(key)
    if raw_record is not None:
        record = json.loads(_redis_text(raw_record))
        await cast(
            Awaitable[int],
            redis.srem(_family_key(str(record["family_id"])), key),
        )
        await cast(
            Awaitable[int],
            redis.srem(_user_refresh_key(UUID(record["user_id"])), key),
        )
        await write_audit(
            db=db,
            actor_id=UUID(record["user_id"]),
            action="logout",
            target_type="user",
            target_id=UUID(record["user_id"]),
        )
        await db.commit()
    await redis.delete(key)


async def add_self_role(
    db: AsyncSession,
    user: User,
    role: str,
) -> UserRole:
    """Let a user add Contributor or Operator role to their account."""
    if role == "attestor":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Attestor access is granted through an organization; "
                "it cannot be self-selected."
            ),
        )
    if role not in {"contributor", "operator"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported role.",
        )

    existing = await db.scalar(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role == role)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role already assigned.",
        )

    assigned_role = UserRole(
        user_id=user.id,
        role=role,
        approved_at=datetime.now(UTC),
    )
    db.add(assigned_role)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="role_assigned",
        target_type="user",
        target_id=user.id,
        metadata={"role": role, "self_assigned": True},
    )
    await db.commit()
    return assigned_role


async def setup_totp(db: AsyncSession, user: User) -> TotpSetupResponse:
    """Start TOTP enrollment and return one-time recovery material."""
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA is already enabled.",
        )

    secret = pyotp.random_base32()
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name=TOTP_ISSUER_NAME,
    )
    backup_codes = generate_backup_codes()
    user.totp_secret = encrypt_totp_secret(secret)

    # Regenerating setup material replaces any previous unverified backup codes.
    await db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == user.id))
    for code in backup_codes:
        db.add(UserBackupCode(user_id=user.id, code_hash=_backup_code_hash(code)))

    await db.commit()
    return TotpSetupResponse(
        provisioning_uri=provisioning_uri,
        qr_png_base64=_qr_png_base64(provisioning_uri),
        backup_codes=backup_codes,
    )


async def verify_totp_enable(
    db: AsyncSession,
    redis: Redis,
    user: User,
    code: str,
) -> bool:
    """Enable TOTP after the user proves possession of the current code."""
    if user.totp_secret is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA setup has not been started.",
        )
    await _ensure_totp_not_locked(redis, user.id)
    secret = decrypt_totp_secret(user.totp_secret)
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        await _record_totp_failure(redis, user.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid 2FA code.",
        )

    user.totp_enabled = True
    await _clear_totp_failures(redis, user.id)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="2fa_enabled",
        target_type="user",
        target_id=user.id,
    )
    await db.commit()
    return True


async def _consume_backup_code(
    db: AsyncSession,
    user: User,
    code: str,
) -> bool:
    """Mark a matching backup code as used when available."""
    backup_code = await db.scalar(
        select(UserBackupCode).where(
            UserBackupCode.user_id == user.id,
            UserBackupCode.code_hash == _backup_code_hash(code),
            UserBackupCode.used_at.is_(None),
        )
    )
    if backup_code is None:
        return False
    backup_code.used_at = datetime.now(UTC)
    return True


async def _verify_totp_or_backup_code(
    db: AsyncSession,
    user: User,
    code: str,
) -> bool:
    """Accept either a current TOTP code or an unused backup code."""
    if user.totp_secret is not None:
        secret = decrypt_totp_secret(user.totp_secret)
        if pyotp.TOTP(secret).verify(code, valid_window=1):
            return True
    return await _consume_backup_code(db, user, code)


async def verify_totp_for_sensitive_action(
    db: AsyncSession,
    redis: Redis,
    user: User,
    code: str | None,
) -> None:
    """Require and verify TOTP or backup code for sensitive settings changes."""
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enable two-factor authentication before this action.",
        )
    if code is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Confirm with your authenticator app before continuing.",
        )

    await _ensure_totp_not_locked(redis, user.id)
    if not await _verify_totp_or_backup_code(db, user, code):
        await _record_totp_failure(redis, user.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid 2FA code.",
        )
    await _clear_totp_failures(redis, user.id)


async def disable_totp(
    db: AsyncSession,
    redis: Redis,
    user: User,
    code: str,
) -> bool:
    """Disable TOTP after verifying the current code or a backup code."""
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA is not enabled.",
        )
    await _ensure_totp_not_locked(redis, user.id)
    if not await _verify_totp_or_backup_code(db, user, code):
        await _record_totp_failure(redis, user.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid 2FA code.",
        )

    user.totp_enabled = False
    user.totp_secret = None
    await db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == user.id))
    await _clear_totp_failures(redis, user.id)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="2fa_disabled",
        target_type="user",
        target_id=user.id,
    )
    await db.commit()
    return False


async def _count_unused_backup_codes(db: AsyncSession, user: User) -> int:
    """Return how many unused backup codes the user has remaining."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(UserBackupCode)
            .where(
                UserBackupCode.user_id == user.id,
                UserBackupCode.used_at.is_(None),
            )
        )
    ) or 0


async def get_totp_status(db: AsyncSession, user: User) -> TotpStatusResponse:
    """Report TOTP enablement and the count of unused backup codes.

    Used by the account UI to decide between first-time setup, re-enrollment on
    a new device, and the backup-code recovery surface.
    """
    return TotpStatusResponse(
        totp_enabled=user.totp_enabled,
        backup_codes_remaining=await _count_unused_backup_codes(db, user),
    )


async def regenerate_backup_codes(
    db: AsyncSession,
    redis: Redis,
    user: User,
    code: str,
) -> list[str]:
    """Replace the user's backup codes after verifying a TOTP or backup code.

    Lets a user restock recovery codes (e.g. after using several to recover a
    lost device) without disabling 2FA. Requires proof of possession.

    Args:
        db: Async session for the regeneration transaction.
        redis: Redis client for lockout accounting.
        user: Authenticated account regenerating its codes.
        code: Current TOTP code or an unused backup code.

    Returns:
        The freshly generated backup codes (shown once).

    Raises:
        HTTPException(409): If 2FA is not enabled.
        HTTPException(422): If the supplied code is invalid.
        HTTPException(429): If the account is temporarily locked out.
    """
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA is not enabled.",
        )
    await _ensure_totp_not_locked(redis, user.id)
    if not await _verify_totp_or_backup_code(db, user, code):
        await _record_totp_failure(redis, user.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid 2FA code.",
        )

    backup_codes = generate_backup_codes()
    await db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == user.id))
    for new_code in backup_codes:
        db.add(UserBackupCode(user_id=user.id, code_hash=_backup_code_hash(new_code)))

    await _clear_totp_failures(redis, user.id)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="2fa_backup_codes_regenerated",
        target_type="user",
        target_id=user.id,
    )
    await db.commit()
    return backup_codes


async def verify_totp_login(
    db: AsyncSession,
    redis: Redis,
    challenge_token: str,
    code: str,
    ip: str | None = None,
    ua: str | None = None,
) -> tuple[LoginResponse, str]:
    """Complete a 2FA login challenge and issue browser session tokens."""
    key = _totp_challenge_key(challenge_token)
    raw_user_id = await redis.get(key)
    if raw_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="2FA challenge expired or already used.",
        )

    user_id = UUID(str(raw_user_id))
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or user.deactivated_at is not None or not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 2FA challenge.",
        )
    if user.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended.",
        )

    await _ensure_totp_not_locked(redis, user.id)
    if not await _verify_totp_or_backup_code(db, user, code):
        await _record_totp_failure(redis, user.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid 2FA code.",
        )

    roles = await _load_active_roles(db, user.id)
    access_token = create_access_token(user_id=user.id, roles=roles, totp_verified=True)
    refresh_token = generate_opaque_token()
    family_id = str(uuid4())
    await redis.delete(key)
    await _clear_totp_failures(redis, user.id)
    await _store_refresh_token(
        redis,
        refresh_token,
        user.id,
        family_id,
        ip,
        ua,
        totp_verified=True,
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="login_success",
        target_type="user",
        target_id=user.id,
        metadata={"totp_verified": True},
        ip=ip,
        ua=ua,
    )
    await db.commit()
    return LoginResponse(access_token=access_token), refresh_token
