"""Pydantic schemas for the Auracles Profile module.

Response shapes are an explicit allow-list of public identity fields. Private
account columns (email, kyc internals, security secrets) are never modelled
here, so they can never leak through a public profile response.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

PUBLIC_URL_ALLOWED_SCHEMES = ("http", "https")
MAX_SPECIALIZATIONS = 20
MAX_SPECIALIZATION_LENGTH = 80


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
    specializations: list[str] = []
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
    specializations: list[str] | None = Field(default=None)

    @field_validator("specializations")
    @classmethod
    def clean_specializations(cls, value: list[str] | None) -> list[str] | None:
        """Trim, drop blanks, and de-duplicate specializations in order.

        Args:
            value: The submitted specializations, or None when omitted.

        Returns:
            The cleaned list, or None when omitted (leaving them untouched).

        Raises:
            ValueError: If too many are submitted, or any entry is too long.
        """
        if value is None:
            return None
        if len(value) > MAX_SPECIALIZATIONS:
            raise ValueError(
                f"at most {MAX_SPECIALIZATIONS} specializations are allowed"
            )
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            label = raw.strip()
            if not label:
                continue
            if len(label) > MAX_SPECIALIZATION_LENGTH:
                raise ValueError(
                    "each specialization must be "
                    f"{MAX_SPECIALIZATION_LENGTH} characters or fewer"
                )
            key = label.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(label)
        return cleaned

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


class AvatarUploadUrlRequest(BaseModel):
    """Request body for an avatar presigned upload target.

    Attributes:
        filename: Original filename, used only to derive the stored extension.
        mime_type: Declared image MIME type (validated against an allow-list).
        file_size: Declared size in bytes (validated against the size cap).
    """

    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size: int = Field(gt=0)


class AvatarUploadUrlResponse(BaseModel):
    """Presigned POST target plus the avatar URL the object will be served at.

    The avatar_url is not persisted until the upload is confirmed, so a never
    completed upload cannot leave a dangling URL on the profile.

    Attributes:
        upload_url: The S3 POST URL the client uploads to.
        fields: Form fields the client must include in the POST.
        file_key: The object key the avatar will live at.
        avatar_url: Public URL the object will be served at once uploaded.
        max_size: Maximum allowed size in bytes (also enforced by S3).
        expires_in: Seconds until the presigned target expires.
    """

    upload_url: str
    fields: dict[str, str]
    file_key: str
    avatar_url: str
    max_size: int
    expires_in: int


class AvatarConfirmRequest(BaseModel):
    """Request body confirming a completed avatar upload.

    Attributes:
        file_key: The object key returned by the upload-url request.
    """

    file_key: str = Field(min_length=1, max_length=512)
