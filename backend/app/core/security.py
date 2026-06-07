"""Security primitives for authentication and authorization.

This module centralizes password hashing, JWT access tokens, opaque token
generation, and password policy validation. Keeping these helpers small and
typed lets later auth slices compose them without duplicating security logic.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import jwt  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.shared.schemas.token import TokenPayload

ACCESS_TOKEN_EXPIRE_MINUTES = 15
JWT_ALGORITHM = "HS256"
MAX_PASSWORD_LENGTH = 128
MIN_PASSWORD_LENGTH = 12

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
