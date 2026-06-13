"""Security primitives for authentication and authorization.

This module centralizes password hashing, JWT access tokens, opaque token
generation, and password policy validation. Keeping these helpers small and
typed lets later auth slices compose them without duplicating security logic.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from jose import jwt  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.shared.schemas.token import TokenPayload

ACCESS_TOKEN_EXPIRE_MINUTES = 15
JWT_ALGORITHM = "HS256"
MAX_PASSWORD_LENGTH = 128
MIN_PASSWORD_LENGTH = 12
BACKUP_CODE_BYTES = 4

_password_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash a plaintext password with Argon2id for durable storage."""
    return _password_hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    """Return whether a plaintext password matches a stored Argon2 hash."""
    try:
        return _password_hasher.verify(password_hash, plain)
    except VerifyMismatchError:
        return False


def create_access_token(
    user_id: UUID,
    roles: list[str],
    totp_verified: bool = False,
) -> str:
    """Create a 15-minute HS256 JWT access token with role claims."""
    settings = get_settings()
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    # Use string UUIDs in JWT JSON, then parse back into UUID via TokenPayload.
    payload = {
        "sub": str(user_id),
        "roles": roles,
        "totp_verified": totp_verified,
        "exp": int(expires_at.timestamp()),
        "iat": int(issued_at.timestamp()),
        "iat_ms": int(issued_at.timestamp() * 1000),
        "jti": str(uuid4()),
    }
    return cast(str, jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM))


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate a JWT access token into typed claims."""
    settings = get_settings()
    payload = cast(
        dict[str, Any],
        jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM]),
    )
    return TokenPayload.model_validate(payload)


def generate_opaque_token() -> str:
    """Generate a high-entropy URL-safe token for Redis-backed auth flows."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash an opaque token before storing or looking it up in Redis."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _totp_cipher() -> Fernet:
    """Build the Fernet cipher used for encrypted TOTP secrets."""
    key = get_settings().totp_encryption_key.get_secret_value().encode("utf-8")
    return Fernet(key)


def _payout_account_cipher() -> Fernet:
    """Build the Fernet cipher used for provider payout account IDs."""
    key = (
        get_settings()
        .payout_account_encryption_key.get_secret_value()
        .encode("utf-8")
    )
    return Fernet(key)


def _partner_webhook_cipher() -> Fernet:
    """Build the Fernet cipher used for Partner webhook signing secrets."""
    key = (
        get_settings()
        .partner_webhook_encryption_key.get_secret_value()
        .encode("utf-8")
    )
    return Fernet(key)


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt a TOTP shared secret before database persistence."""
    return _totp_cipher().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_totp_secret(encrypted_secret: str) -> str:
    """Decrypt a stored TOTP shared secret for verification."""
    return _totp_cipher().decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")


def encrypt_payout_provider_account_id(provider_account_id: str) -> str:
    """Encrypt a provider payout account id before database persistence."""
    return _payout_account_cipher().encrypt(provider_account_id.encode("utf-8")).decode(
        "utf-8"
    )


def decrypt_payout_provider_account_id(encrypted_provider_account_id: str) -> str:
    """Decrypt a provider payout account id before provider API calls."""
    return (
        _payout_account_cipher()
        .decrypt(encrypted_provider_account_id.encode("utf-8"))
        .decode("utf-8")
    )


def hash_payout_provider_account_id(provider_account_id: str) -> str:
    """Return a stable keyed lookup hash for provider payout account ids."""
    key = get_settings().payout_account_encryption_key.get_secret_value().encode(
        "utf-8"
    )
    return hmac.new(
        key,
        provider_account_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def encrypt_partner_webhook_secret(secret: str) -> str:
    """Encrypt a Partner webhook HMAC secret before database persistence."""
    return _partner_webhook_cipher().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_partner_webhook_secret(encrypted_secret: str) -> str:
    """Decrypt a stored Partner webhook HMAC secret for outbound signing."""
    return (
        _partner_webhook_cipher()
        .decrypt(encrypted_secret.encode("utf-8"))
        .decode("utf-8")
    )


def generate_backup_codes(n: int = 10) -> list[str]:
    """Generate one-time backup codes in `xxxx-xxxx` format."""
    codes: list[str] = []
    while len(codes) < n:
        raw = secrets.token_hex(BACKUP_CODE_BYTES)
        code = f"{raw[:4]}-{raw[4:]}"
        if code not in codes:
            codes.append(code)
    return codes


def validate_password_strength(password: str) -> str:
    """Validate the Phase 1 password policy and return the original value."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("Password must be at least 12 characters long.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("Password must be at most 128 characters long.")
    if not any(character.isalpha() for character in password):
        raise ValueError("Password must include at least one letter.")
    if not any(character.isdigit() for character in password):
        raise ValueError("Password must include at least one digit.")
    return password
