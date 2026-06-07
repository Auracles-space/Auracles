"""Pydantic schemas for auth request and response payloads."""

from typing import Literal

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
