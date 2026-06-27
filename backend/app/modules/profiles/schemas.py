"""Pydantic schemas for the Auracles Profile module.

Response shapes are an explicit allow-list of public identity fields. Private
account columns (email, kyc internals, security secrets) are never modelled
here, so they can never leak through a public profile response.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

PUBLIC_URL_ALLOWED_SCHEMES = ("http", "https")


class PublicProfileResponse(BaseModel):
    """Curated public identity for any platform user.

    Returned for the canonical profile page regardless of role. Only fields a
    visitor is allowed to see are present; the body is assembled field-by-field
    in the service, never serialised straight from the ORM user.

    Attributes:
        id: The profile owner's user id.
        display_name: Public display name.
        avatar_url: Public avatar URL, or None.
        headline: Short professional headline, or None.
        bio: Free-text bio, or None.
        location: Free-text location, or None.
        website: Personal/site URL, validated to a safe web scheme, or None.
        roles: Public role badges (e.g. contributor, operator, attestor).
        kyc_verified: Whether the user has completed identity verification.
        is_deactivated: Whether the account is self-deactivated.
        is_limited: Whether discretionary content is withheld (suspended
            account). Safe identity stays visible; bio/location/website are
            nulled.
    """

    id: UUID
    display_name: str
    avatar_url: str | None = None
    headline: str | None = None
    bio: str | None = None
    location: str | None = None
    website: str | None = None
    roles: list[str] = []
    kyc_verified: bool = False
    is_deactivated: bool = False
    is_limited: bool = False


class ProfileUpdateRequest(BaseModel):
    """Owner-editable profile fields for PATCH /profiles/me.

    All fields optional: only those present in the request are updated, so a
    partial PATCH never clears omitted fields. The website scheme is validated
    here at the write boundary so an unsafe URL is rejected before storage,
    rather than silently nulled on read.

    Attributes:
        headline: Short professional headline (<=160 chars).
        bio: Free-text bio (<=2000 chars).
        location: Free-text location (<=100 chars).
        website: Personal/site URL; must use http or https.
    """

    headline: str | None = Field(default=None, max_length=160)
    bio: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=2048)

    @field_validator("website")
    @classmethod
    def website_uses_safe_scheme(cls, value: str | None) -> str | None:
        """Reject any website URL that is not http/https.

        Args:
            value: The submitted website URL, or None.

        Returns:
            The trimmed URL when valid, or None when cleared.

        Raises:
            ValueError: If a non-empty value does not use a safe web scheme.
        """
        if value is None:
            return None
        candidate = value.strip()
        if not candidate:
            return None
        scheme, separator, _ = candidate.partition("://")
        if not separator or scheme.lower() not in PUBLIC_URL_ALLOWED_SCHEMES:
            raise ValueError("website must be an http or https URL")
        return candidate
