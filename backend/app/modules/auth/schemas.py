"""Pydantic schemas for auth request and response payloads."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator

from app.core.security import validate_password_strength

AssignableRole = Literal["contributor", "operator", "attestor"]


class RegisterRequest(BaseModel):
    """Request body for email/password registration."""

    email: EmailStr
    password: SecretStr
    display_name: str = Field(min_length=1, max_length=100)
    roles: list[AssignableRole] = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def password_meets_policy(cls, value: SecretStr) -> SecretStr:
        """Apply the shared password policy to registration."""
        validate_password_strength(value.get_secret_value())
        return value

    @field_validator("roles")
    @classmethod
    def roles_are_unique(cls, value: list[AssignableRole]) -> list[AssignableRole]:
        """Reject duplicate role selections from malformed clients."""
        if len(set(value)) != len(value):
            raise ValueError("Roles must be unique.")
        return value


class RegisterResponse(BaseModel):
    """No-enumeration registration response."""

    message: str = "If email is new, verification sent."


class VerifyEmailRequest(BaseModel):
    """Request body for email verification."""

    token: str = Field(min_length=1)


class ResendVerificationRequest(BaseModel):
    """Request body for requesting a new verification email."""

    email: EmailStr


class LoginRequest(BaseModel):
    """Request body for email/password login."""

    email: EmailStr
    password: SecretStr


class LoginResponse(BaseModel):
    """Browser login response; refresh token travels via HttpOnly cookie."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 900


class RefreshRequest(BaseModel):
    """Empty refresh request body; server reads the refresh cookie."""


class CurrentUserResponse(BaseModel):
    """Authenticated user response for `/v1/auth/me`."""

    id: UUID
    email: EmailStr
    display_name: str
    roles: list[str]
    email_verified: bool
    kyc_status: str
    deactivated_at: datetime | None
