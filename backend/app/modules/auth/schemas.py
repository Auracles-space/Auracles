"""Pydantic schemas for auth request and response payloads."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator

from app.core.security import validate_password_strength

AssignableRole = Literal["contributor", "operator", "attestor"]
SelfAssignableRole = Literal["contributor", "operator"]


class RegisterRequest(BaseModel):
    """Request body for email/password registration."""

    email: EmailStr
    password: SecretStr
    display_name: str = Field(min_length=1, max_length=100)
    roles: list[AssignableRole] = Field(min_length=1)
    # In-app path to return to after email verification (an invitation the
    # user was following, for instance). Carried on the verification link.
    next: str | None = Field(default=None, max_length=500)

    @field_validator("password")
    @classmethod
    def password_meets_policy(cls, value: SecretStr) -> SecretStr:
        """Apply the shared password policy to registration."""
        validate_password_strength(value.get_secret_value())
        return value

    @field_validator("next")
    @classmethod
    def next_is_an_app_path(cls, value: str | None) -> str | None:
        """Accept only a same-origin path: one leading slash, never ``//``.

        A scheme or a protocol-relative ``//host`` would turn the verification
        email into an open redirect.
        """
        if value is None:
            return None
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("next must be an in-app path starting with a single '/'.")
        return value

    @field_validator("roles")
    @classmethod
    def roles_are_valid(cls, value: list[AssignableRole]) -> list[AssignableRole]:
        """Reject duplicate roles and self-selected Attestor.

        Operator and Contributor may coexist and are the only self-selectable
        roles. Attestor is granted solely as a derived role through an
        organization's active attestor capability, so it cannot be selected at
        registration.
        """
        if len(set(value)) != len(value):
            raise ValueError("Roles must be unique.")
        if "attestor" in value:
            raise ValueError(
                "Attestor access is granted through an organization; "
                "it cannot be self-selected."
            )
        return value


class RegisterResponse(BaseModel):
    """No-enumeration registration response."""

    message: str = (
        "We've sent a verification link to your email. "
        "Please check your inbox to activate your account."
    )


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
    # When True, the browser refresh + session-hint cookies persist for 30 days
    # ("Remember me"). When False (default), they are session-scoped and dropped
    # on browser close.
    remember_me: bool = False


class ForgotPasswordRequest(BaseModel):
    """Request body for starting password reset without enumeration."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Request body for consuming a password reset token."""

    token: str = Field(min_length=1)
    new_password: SecretStr

    @field_validator("new_password")
    @classmethod
    def new_password_meets_policy(cls, value: SecretStr) -> SecretStr:
        """Apply the shared password policy to password reset."""
        validate_password_strength(value.get_secret_value())
        return value


class LoginResponse(BaseModel):
    """Browser login response; refresh token travels via HttpOnly cookie."""

    access_token: str | None = None
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 900
    requires_2fa: bool | None = None
    challenge_token: str | None = None


class RefreshRequest(BaseModel):
    """Empty refresh request body; server reads the refresh cookie."""


class CurrentUserResponse(BaseModel):
    """Authenticated user response for `/v1/auth/me`."""

    id: UUID
    email: EmailStr
    display_name: str
    avatar_url: str | None
    roles: list[str]
    pending_roles: list[str] = Field(
        description=(
            "Roles held but not yet usable — in practice only an Attestor "
            "application awaiting admin approval. Never overlaps `roles`, so "
            "callers can render the two lists side by side."
        )
    )
    email_verified: bool
    kyc_status: str
    deactivated_at: datetime | None
    is_superadmin: bool = False
    # False for passwordless (e.g. Google) accounts; the settings UI uses this to
    # swap password re-auth for a "set a password" path and TOTP-only step-up.
    has_password: bool = True


class AddRoleRequest(BaseModel):
    """Request body for self-adding a non-privileged role."""

    role: AssignableRole


class RoleAssignmentResponse(BaseModel):
    """Response body for role assignment endpoints."""

    user_id: UUID
    role: str
    approved: bool


class TotpSetupResponse(BaseModel):
    """One-time TOTP enrollment response with recovery material."""

    provisioning_uri: str
    qr_png_base64: str
    backup_codes: list[str]


class TotpSetupRequest(BaseModel):
    """Request body starting TOTP enrollment.

    ``password`` is required for accounts that have one. Passwordless (OAuth)
    accounts have no password to present, so the field stays optional at the
    schema layer and the service decides per account.
    """

    password: str | None = None


class TotpCodeRequest(BaseModel):
    """Request body containing a current TOTP code."""

    code: str = Field(min_length=6, max_length=16)


class StepUpRequest(BaseModel):
    """Request body opening a step-up window with a TOTP or backup code."""

    code: str = Field(min_length=6, max_length=16)


class StepUpResponse(BaseModel):
    """Response after a step-up verification: when the window closes."""

    verified_until: datetime


class StepUpStatusResponse(BaseModel):
    """Whether the caller currently holds an open step-up window."""

    active: bool
    verified_until: datetime | None = None


class TotpStatusResponse(BaseModel):
    """Response body describing TOTP account state.

    ``backup_codes_remaining`` is only meaningful on the status endpoint; the
    enable/disable endpoints leave it at the default since the count is not
    relevant to their result.
    """

    totp_enabled: bool
    backup_codes_remaining: int = 0


class TotpBackupCodesResponse(BaseModel):
    """One-time response carrying a freshly generated set of backup codes."""

    backup_codes: list[str]


class TotpLoginVerifyRequest(BaseModel):
    """Request body for completing a 2FA login challenge."""

    challenge_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=16)
