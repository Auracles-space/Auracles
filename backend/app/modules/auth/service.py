"""Auth service layer for registration and email verification.

This module also centralizes session-state enforcement decisions such as
account deactivation, suspension, and access-token revocation cutoffs.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import time
from base64 import b64encode
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
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
from app.core.config import get_settings
from app.core.rate_limit import RateLimiter, RedisCounter, format_retry_phrase
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
# TOTP time-step and the ± window of steps `verify` accepts. A matched step is
# claimed single-use in Redis for the full window so a code cannot be replayed.
TOTP_STEP_SECONDS = 30
TOTP_VALID_WINDOW = 1

LOGIN_IP_LIMITER = RateLimiter(namespace="login_ip", limit=20, window=60)
# Registration dispatches a verification email to the caller-supplied address,
# so an unlimited endpoint is an email-bombing and account-spam vector (M3).
# Mirrors the forgot-password caps: coarse per-IP, tight per-email.
REGISTER_IP_LIMITER = RateLimiter(namespace="register_ip", limit=10, window=3_600)
REGISTER_EMAIL_LIMITER = RateLimiter(
    namespace="register_email",
    limit=3,
    window=3_600,
)
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


@cache
def _timing_decoy_hash() -> str:
    """Return a throwaway Argon2 hash used to keep login timing flat.

    Verified against when no user row (or no stored password) exists, so an
    unregistered address pays the same hashing cost as a registered one and the
    response time stops telling an attacker which is which. Cached because the
    value is irrelevant — only the work of checking it matters — and hashing on
    every miss would hand back a slower miss than a hit.
    """
    return hash_password(f"decoy-{uuid4()}")


def _login_failure_key(email: str) -> str:
    """Build the Redis failed-login counter key."""
    return f"login_failure:{email}"


def _totp_challenge_key(token: str) -> str:
    """Build the Redis key for a pending 2FA login challenge."""
    return f"2fa_challenge:{hash_token(token)}"


def _totp_failure_key(user_id: UUID) -> str:
    """Build the Redis failed-2FA counter key."""
    return f"2fa_failure:{user_id}"


def step_up_key(user_id: UUID) -> str:
    """Build the Redis key holding a user's open step-up window."""
    return f"stepup:{user_id}"


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


def _lockout_error(ttl: int, *, window: int, what: str) -> HTTPException:
    """Build the 429 a failure lockout raises, saying when it lifts.

    These lockouts count failures directly in Redis rather than going through
    ``RateLimiter``, so they have to spell out the wait themselves. A lockout
    that gives no end date is indistinguishable from a permanent ban, and the
    user's only recourse is to keep retrying — which is what the counter is
    there to stop.

    Args:
        ttl: Remaining TTL on the failure counter, in seconds. A non-positive
            value means Redis holds no expiry yet, so the full window is used.
        window: The lockout window to fall back to.
        what: Plural noun for the attempts being limited, e.g. ``"login
            attempts"``.

    Returns:
        A 429 carrying both a readable message and a ``Retry-After`` header.
    """
    retry_after = ttl if ttl > 0 else window
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"Too many {what}. Please try again in {format_retry_phrase(retry_after)}."
        ),
        headers={"Retry-After": str(retry_after)},
    )


async def _ensure_totp_not_locked(redis: Redis, user_id: UUID) -> None:
    """Reject verification when recent wrong-code attempts exceeded the limit."""
    failure_key = _totp_failure_key(user_id)
    attempts = int(await redis.get(failure_key) or "0")
    if attempts >= TOTP_FAILURE_LIMIT:
        raise _lockout_error(
            await redis.ttl(failure_key),
            window=TOTP_FAILURE_WINDOW_SECONDS,
            what="2FA attempts",
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
    roles = [
        role
        for role, approved_at in rows
        if role != "attestor" or approved_at is not None
    ]
    return list(dict.fromkeys(roles))


async def _store_refresh_token(
    redis: Redis,
    token: str,
    user_id: UUID,
    family_id: str,
    ip: str | None,
    ua: str | None,
    totp_verified: bool = False,
    remember_me: bool = False,
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
        # Persisted so token rotation on /refresh can re-issue the cookie with
        # the same lifetime the user originally chose.
        "remember_me": remember_me,
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
    await REGISTER_IP_LIMITER.check(cast(RedisCounter, redis), ip or "unknown")
    await REGISTER_EMAIL_LIMITER.check(cast(RedisCounter, redis), email)
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
            from app.modules.notifications.service import create_notification
            from app.modules.organizations.models import OrgInvitation

            pending_invites = (
                await db.scalars(
                    select(OrgInvitation).where(
                        func.lower(OrgInvitation.email) == email,
                        OrgInvitation.status == "pending",
                    )
                )
            ).all()
            for invite in pending_invites:
                await create_notification(
                    db=db,
                    user_id=user.id,
                    notification_type="org_invitation_received",
                    title="You have a pending organization invitation",
                    body=(
                        "An organization invited you to join. Review it in "
                        "your settings."
                    ),
                    link="/settings/organizations",
                    payload={"org_id": str(invite.org_id)},
                    dedupe_key=f"org-invitation-received:{invite.id}",
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
    send_verification_email.delay(email, token, request.next)
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
    # Refresh-token deletion alone leaves already-issued access tokens valid for
    # the rest of their TTL. A user resetting their password to eject an
    # intruder expects the intruder out now, and that window is long enough to
    # seize the account permanently by re-keying 2FA.
    user.access_revoked_before = datetime.now(UTC)
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
    remember_me: bool = False,
) -> tuple[LoginResponse, str, bool]:
    """Authenticate a verified user and issue access plus refresh tokens.

    Returns:
        A tuple of the login response, the opaque refresh token (empty when a
        2FA challenge is pending), and the resolved ``remember_me`` flag the
        caller uses to decide cookie persistence.
    """
    normalized_email = normalize_email(email)
    await LOGIN_IP_LIMITER.check(cast(RedisCounter, redis), ip or "unknown")
    failure_key = _login_failure_key(normalized_email)
    if int(await redis.get(failure_key) or "0") >= LOGIN_FAILURE_LIMIT:
        raise _lockout_error(
            await redis.ttl(failure_key),
            window=LOGIN_FAILURE_WINDOW_SECONDS,
            what="login attempts",
        )

    user = await db.scalar(select(User).where(User.email == normalized_email))
    # Verify against a decoy when there is no stored hash, so an unregistered
    # address costs the same Argon2 work as a registered one. Short-circuiting
    # here answered ~28ms faster for an unknown email, which enumerates the
    # user base without needing a single correct password.
    stored_hash = (
        user.password_hash
        if user is not None and user.password_hash is not None
        else _timing_decoy_hash()
    )
    password_matches = verify_password(password, stored_hash)
    if user is None or user.password_hash is None or not password_matches:
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
        # Carry the remember_me choice server-side through the 2FA step so it
        # cannot be tampered with between challenge and verification.
        await redis.setex(
            _totp_challenge_key(challenge_token),
            TOTP_CHALLENGE_TTL_SECONDS,
            json.dumps({"user_id": str(user.id), "remember_me": remember_me}),
        )
        await db.commit()
        return (
            LoginResponse(
                requires_2fa=True,
                challenge_token=challenge_token,
            ),
            "",
            remember_me,
        )

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
        remember_me=remember_me,
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
    return LoginResponse(access_token=access_token), refresh_token, remember_me


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
) -> tuple[LoginResponse, str, bool]:
    """Rotate a refresh token and issue a new access token.

    Returns the login response, the rotated refresh token, and the stored
    ``remember_me`` flag so the caller re-issues the cookie with the same
    lifetime the user originally chose.
    """
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
    remember_me = bool(record.get("remember_me", False))
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
        remember_me=remember_me,
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
    return LoginResponse(access_token=access_token), new_refresh_token, remember_me


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
        await revoke_step_up(redis, UUID(record["user_id"]))
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
        select(UserRole)
        .where(
            UserRole.user_id == user.id,
            UserRole.role == role,
            UserRole.source == "self",
        )
        .limit(1)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Role already assigned.",
        )

    assigned_role = UserRole(
        user_id=user.id,
        role=role,
        source="self",
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


async def setup_totp(
    db: AsyncSession,
    user: User,
    password: str | None = None,
) -> TotpSetupResponse:
    """Start TOTP enrollment and return one-time recovery material.

    Args:
        db: Async session used to persist the new enrollment material.
        user: The authenticated account enrolling in 2FA.
        password: The account password, required when the account has one.

    Returns:
        The provisioning URI, a QR rendering, and one-time backup codes.

    Raises:
        HTTPException(401): If the account has a password and it was not
            supplied or did not match.
        HTTPException(409): If 2FA is already enabled.
    """
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA is already enabled.",
        )

    # Enrollment re-keys the account's second factor and discards its existing
    # backup codes, so a bare access token must not be enough: a session thief
    # would otherwise enroll their own authenticator and lock the owner out
    # permanently. Passwordless accounts have no password to demand, and
    # demanding one would lock them out of 2FA entirely.
    if user.password_hash is not None:
        if password is None or not verify_password(password, user.password_hash):
            logger.bind(module="auth", action="setup_totp", user_id=user.id).warning(
                "totp_setup_reauthentication_failed"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password.",
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


async def _claim_totp_counter(redis: Redis, user_id: UUID, counter: int) -> bool:
    """Atomically claim one TOTP time-step for a user, once (M4 replay guard).

    Returns True on first use of the step, False if it was already consumed —
    so a code observed or phished within its ~90s validity window authorizes
    at most one action. The TTL spans the accepted window so the key self-
    expires once the code is no longer valid anyway.
    """
    claimed = await redis.set(
        f"totp_used:{user_id}:{counter}",
        "1",
        ex=TOTP_STEP_SECONDS * (2 * TOTP_VALID_WINDOW + 1),
        nx=True,
    )
    return bool(claimed)


async def _verify_totp_or_backup_code(
    db: AsyncSession,
    redis: Redis,
    user: User,
    code: str,
) -> bool:
    """Accept a current, unused TOTP code or an unused backup code.

    A matched TOTP time-step is claimed single-use in Redis so the same code
    cannot be replayed within its validity window; backup codes are already
    one-time via `_consume_backup_code`.
    """
    if user.totp_secret is not None:
        secret = decrypt_totp_secret(user.totp_secret)
        totp = pyotp.TOTP(secret)
        now = int(time.time())
        base_counter = now // TOTP_STEP_SECONDS
        for offset in range(-TOTP_VALID_WINDOW, TOTP_VALID_WINDOW + 1):
            counter = base_counter + offset
            if hmac.compare_digest(totp.at(counter * TOTP_STEP_SECONDS), code):
                # The code matches exactly one step; claim it or reject replay.
                return await _claim_totp_counter(redis, user.id, counter)
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
    if not await _verify_totp_or_backup_code(db, redis, user, code):
        await _record_totp_failure(redis, user.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid 2FA code.",
        )
    await _clear_totp_failures(redis, user.id)


async def open_step_up(
    db: AsyncSession,
    redis: Redis,
    user: User,
    code: str,
) -> datetime:
    """Open a step-up window after one TOTP or backup-code verification.

    Sensitive endpoints (see the 2026-09-13 step-up design registry) require
    an open window rather than a per-request code. The window is a Redis key
    per user with a fixed TTL, so it survives access-token rotation and is
    revoked on logout, 2FA disable, and suspension.

    Args:
        db: Async session for backup-code consumption and the audit row.
        redis: Redis client holding the window and the failure counter.
        user: The authenticated user opening the window.
        code: A current TOTP code or an unused backup code.

    Returns:
        The instant the window closes.

    Raises:
        HTTPException(403): If the user has not enrolled in 2FA.
        HTTPException(422): If the code is invalid.
        HTTPException(429): If recent wrong codes exceeded the lockout limit.
    """
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "totp_setup_required",
                "onboarding_url": "/settings/security",
                "message": "Enable two-factor authentication before this action.",
            },
        )
    await _ensure_totp_not_locked(redis, user.id)
    if not await _verify_totp_or_backup_code(db, redis, user, code):
        await _record_totp_failure(redis, user.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid 2FA code.",
        )
    await _clear_totp_failures(redis, user.id)

    ttl = get_settings().step_up_ttl_seconds
    verified_at = datetime.now(UTC)
    verified_until = verified_at + timedelta(seconds=ttl)
    await redis.set(step_up_key(user.id), verified_at.isoformat(), ex=ttl)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="step_up_verified",
        target_type="user",
        target_id=user.id,
        metadata={"ttl_seconds": ttl},
    )
    await db.commit()
    logger.bind(module="auth", action="step_up_verified", user_id=str(user.id)).info(
        "Step-up window opened"
    )
    return verified_until


async def get_step_up_verified_until(redis: Redis, user_id: UUID) -> datetime | None:
    """Return when the user's step-up window closes, or None if none is open."""
    key = step_up_key(user_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    ttl = await redis.ttl(key)
    if ttl < 0:
        return None
    return datetime.now(UTC) + timedelta(seconds=ttl)


async def has_step_up(redis: Redis, user_id: UUID) -> bool:
    """Return whether the user currently holds an open step-up window."""
    return await redis.get(step_up_key(user_id)) is not None


async def revoke_step_up(redis: Redis, user_id: UUID) -> None:
    """Close the user's step-up window, if any."""
    await redis.delete(step_up_key(user_id))


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
    if not await _verify_totp_or_backup_code(db, redis, user, code):
        await _record_totp_failure(redis, user.id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid 2FA code.",
        )

    user.totp_enabled = False
    user.totp_secret = None
    await db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == user.id))
    await _clear_totp_failures(redis, user.id)
    await revoke_step_up(redis, user.id)
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
    if not await _verify_totp_or_backup_code(db, redis, user, code):
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
) -> tuple[LoginResponse, str, bool]:
    """Complete a 2FA login challenge and issue browser session tokens.

    Returns the login response, the refresh token, and the ``remember_me`` flag
    carried from the first login step so the caller sets cookie persistence.
    """
    key = _totp_challenge_key(challenge_token)
    raw_challenge = await redis.get(key)
    if raw_challenge is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="2FA challenge expired or already used.",
        )

    # Challenges are stored as JSON carrying the remember_me choice. Fall back to
    # a bare user-id string for challenges issued before this field existed (and
    # for the Google 2FA path, which does not offer a remember_me checkbox).
    challenge_text = _redis_text(raw_challenge)
    remember_me = False
    try:
        challenge_data = json.loads(challenge_text)
        user_id = UUID(str(challenge_data["user_id"]))
        remember_me = bool(challenge_data.get("remember_me", False))
    except (json.JSONDecodeError, KeyError, TypeError):
        user_id = UUID(challenge_text)
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
    if not await _verify_totp_or_backup_code(db, redis, user, code):
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
        remember_me=remember_me,
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
    return LoginResponse(access_token=access_token), refresh_token, remember_me
