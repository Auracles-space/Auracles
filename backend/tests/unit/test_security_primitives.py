"""Behavior tests for Phase 1 security primitives.

The auth feature slices build on these helpers for password storage, JWT
access tokens, opaque refresh/reset tokens, and password policy enforcement.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from freezegun import freeze_time
from jose import JWTError
from pydantic import BaseModel, ValidationError, field_validator

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)


def test_password_hashes_verify_without_storing_plaintext() -> None:
    """Password hashes verify the original password and reject other input."""
    password_hash = hash_password("CorrectHorse9")

    assert password_hash != "CorrectHorse9"
    assert verify_password("CorrectHorse9", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_access_tokens_round_trip_roles_and_totp_state() -> None:
    """JWT access tokens encode the authenticated user's identity and roles."""
    user_id = uuid4()
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)

    with freeze_time(now):
        token = create_access_token(
            user_id=user_id,
            roles=["contributor", "operator"],
            totp_verified=True,
        )
        payload = decode_access_token(token)

    assert payload.sub == user_id
    assert payload.roles == ["contributor", "operator"]
    assert payload.totp_verified is True
    assert payload.exp == int((now + timedelta(minutes=15)).timestamp())
    assert UUID(payload.jti)


def test_access_tokens_reject_tampering_and_expiry() -> None:
    """JWT decoding rejects tampered or expired access tokens."""
    with freeze_time("2026-06-07 12:00:00+00:00"):
        token = create_access_token(user_id=uuid4(), roles=["admin"])

    with pytest.raises(JWTError):
        decode_access_token(f"{token}tampered")

    with freeze_time("2026-06-07 12:16:00+00:00"), pytest.raises(JWTError):
        decode_access_token(token)


def test_opaque_tokens_are_urlsafe_and_hashed_for_storage() -> None:
    """Opaque token helpers produce high-entropy values and stable hashes."""
    token = generate_opaque_token()

    assert len(token) >= 43
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token
    assert hash_token(token) != hash_token(generate_opaque_token())


def test_password_strength_validator_rejects_weak_passwords() -> None:
    """The reusable validator rejects short or single-character-class passwords."""

    class PasswordInput(BaseModel):
        password: str

        @field_validator("password")
        @classmethod
        def strong_password(cls, value: str) -> str:
            """Apply the application password policy to test input."""
            return validate_password_strength(value)

    assert PasswordInput(password="CorrectHorse9").password == "CorrectHorse9"

    for weak_password in ["short9", "allletterslong", "123456789012"]:
        with pytest.raises(ValidationError):
            PasswordInput(password=weak_password)
