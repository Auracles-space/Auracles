"""Pydantic schemas for the Auracles Profile module.

Response shapes are an explicit allow-list of public identity fields. Private
account columns (email, kyc internals, security secrets) are never modelled
here, so they can never leak through a public profile response.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.attestation.schemas import PublicCredentialResponse
from app.modules.explore.schemas import ExploreFrameworkCard

PUBLIC_URL_ALLOWED_SCHEMES = ("http", "https")
MAX_SPECIALIZATIONS = 20
MAX_SPECIALIZATION_LENGTH = 80
MAX_LINKS = 10
MAX_EXPERIENCE = 20
MAX_EDUCATION = 15
MAX_FEATURED = 3

# Allow-list of social platforms a profile can link out to. Typed (unlike the
# free-form portfolio ``links``) so the frontend renders the right icon and a
# profile carries at most one URL per platform.
SocialPlatform = Literal[
    "x",
    "linkedin",
    "github",
    "youtube",
    "instagram",
    "facebook",
    "tiktok",
]
MAX_SOCIAL_LINKS = 7


def _validate_featured_url(value: str | None) -> str | None:
    """Return a featured URL only when it uses a safe http/https scheme.

    Args:
        value: The submitted URL, or None.

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
        raise ValueError("featured url must be an http or https URL")
    return candidate


class ProfileFeaturedInput(BaseModel):
    """A featured spotlight as submitted by the owner (PATCH /profiles/me).

    A spotlight is either a pinned Framework (``framework_id`` set to one of the
    owner's published Frameworks) or a free-form entry (``title`` set). At least
    one of the two must be present.

    Attributes:
        title: Free-form title (<=160 chars); required unless framework_id set.
        description: Short summary, or None (<=500 chars).
        url: Optional link; must use http or https.
        framework_id: Optional id of a published Framework to pin.
    """

    title: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2048)
    framework_id: UUID | None = None

    _check_url = field_validator("url")(_validate_featured_url)

    @model_validator(mode="after")
    def require_title_or_framework(self) -> ProfileFeaturedInput:
        """Require either a pinned Framework or a free-form title."""
        if self.framework_id is None and not (self.title and self.title.strip()):
            raise ValueError("a featured item needs a title or a framework")
        return self


class ProfileFeatured(BaseModel):
    """A featured spotlight as shown on the profile.

    Carries the stored fields plus, when a Framework is pinned, the resolved
    public Framework card so clients render the live Framework.

    Attributes:
        title: Free-form title, or None when a Framework is pinned.
        description: Short summary, or None.
        url: Optional link.
        framework_id: Pinned Framework id, or None.
        framework: Resolved public Framework card, or None.
    """

    title: str | None = None
    description: str | None = None
    url: str | None = None
    framework_id: UUID | None = None
    framework: ExploreFrameworkCard | None = None


class ProfileExperience(BaseModel):
    """A single self-reported professional experience entry.

    Dates are free-text (e.g. "2021" or "Jan 2021") to avoid forcing a precise
    format; ``current`` marks an ongoing role where ``end`` is absent.

    Attributes:
        title: Role title (1-160 chars).
        company: Organization name (1-160 chars).
        start: Free-text start date, or None.
        end: Free-text end date, or None (e.g. for current roles).
        current: Whether this is the person's current role.
        description: Responsibilities/summary, or None (<=2000 chars).
    """

    title: str = Field(min_length=1, max_length=160)
    company: str = Field(min_length=1, max_length=160)
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    current: bool = False
    description: str | None = Field(default=None, max_length=2000)


class ProfileEducation(BaseModel):
    """A single self-reported education entry.

    Attributes:
        school: Institution name (1-160 chars).
        degree: Degree or qualification, or None (<=160 chars).
        field: Field of study, or None (<=160 chars).
        start_year: Start year, or None.
        end_year: End/graduation year, or None.
    """

    school: str = Field(min_length=1, max_length=160)
    degree: str | None = Field(default=None, max_length=160)
    field: str | None = Field(default=None, max_length=160)
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)


class ProfileLink(BaseModel):
    """A single portfolio link.

    Attributes:
        label: Human-readable link label (1-80 chars).
        url: Destination URL; must use http or https.
    """

    label: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def url_uses_safe_scheme(cls, value: str) -> str:
        """Reject any link URL that is not http/https.

        Args:
            value: The submitted link URL.

        Returns:
            The trimmed URL when valid.

        Raises:
            ValueError: If the URL does not use a safe web scheme.
        """
        candidate = value.strip()
        scheme, separator, _ = candidate.partition("://")
        if not separator or scheme.lower() not in PUBLIC_URL_ALLOWED_SCHEMES:
            raise ValueError("link url must be an http or https URL")
        return candidate


class SocialLink(BaseModel):
    """A single typed social profile link.

    Attributes:
        platform: One of the allow-listed social platforms.
        url: Destination URL on that platform; must use http or https.
    """

    platform: SocialPlatform
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def url_uses_safe_scheme(cls, value: str) -> str:
        """Reject any social link URL that is not http/https.

        Args:
            value: The submitted social link URL.

        Returns:
            The trimmed URL when valid.

        Raises:
            ValueError: If the URL does not use a safe web scheme.
        """
        candidate = value.strip()
        scheme, separator, _ = candidate.partition("://")
        if not separator or scheme.lower() not in PUBLIC_URL_ALLOWED_SCHEMES:
            raise ValueError("social link url must be an http or https URL")
        return candidate


class ProfileStats(BaseModel):
    """Aggregated marketplace analytics shown on the profile.

    All values are derived from public records (published Frameworks, public
    reviews, completed attestations), not self-reported.

    Attributes:
        frameworks_published: Count of the user's published Frameworks.
        reviews_received: Count of reviews across the user's Frameworks.
        average_rating: Mean review score (1 decimal), or None if no reviews.
        attestations_performed: Count of attestations the user completed as an
            Attestor.
    """

    frameworks_published: int = 0
    reviews_received: int = 0
    average_rating: float | None = None
    attestations_performed: int = 0


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
    banner_url: str | None = None
    headline: str | None = None
    bio: str | None = None
    location: str | None = None
    website: str | None = None
    specializations: list[str] = []
    links: list[ProfileLink] = []
    social_links: list[SocialLink] = []
    featured: list[ProfileFeatured] = []
    experience: list[ProfileExperience] = []
    education: list[ProfileEducation] = []
    verified_credentials: list[PublicCredentialResponse] = []
    stats: ProfileStats = ProfileStats()
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
    links: list[ProfileLink] | None = Field(default=None, max_length=MAX_LINKS)
    social_links: list[SocialLink] | None = Field(
        default=None, max_length=MAX_SOCIAL_LINKS
    )
    featured: list[ProfileFeaturedInput] | None = Field(
        default=None, max_length=MAX_FEATURED
    )
    experience: list[ProfileExperience] | None = Field(
        default=None, max_length=MAX_EXPERIENCE
    )
    education: list[ProfileEducation] | None = Field(
        default=None, max_length=MAX_EDUCATION
    )

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

    @field_validator("social_links")
    @classmethod
    def social_links_unique_platform(
        cls, value: list[SocialLink] | None
    ) -> list[SocialLink] | None:
        """Reject more than one social link for the same platform.

        Args:
            value: The submitted social links, or None when omitted.

        Returns:
            The list unchanged when valid, or None when omitted.

        Raises:
            ValueError: If a platform appears more than once.
        """
        if value is None:
            return None
        seen: set[str] = set()
        for link in value:
            if link.platform in seen:
                raise ValueError(
                    f"only one link per platform is allowed ({link.platform})"
                )
            seen.add(link.platform)
        return value

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


class BannerUploadUrlRequest(BaseModel):
    """Request body for a banner presigned upload target.

    Attributes:
        filename: Original filename, used only to derive the stored extension.
        mime_type: Declared image MIME type (validated against an allow-list).
        file_size: Declared size in bytes (validated against the size cap).
    """

    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size: int = Field(gt=0)


class BannerUploadUrlResponse(BaseModel):
    """Presigned POST target plus the URL the banner will be served at.

    Attributes:
        upload_url: The S3 POST URL the client uploads to.
        fields: Form fields the client must include in the POST.
        file_key: The object key the banner will live at.
        banner_url: Public URL the object will be served at once uploaded.
        max_size: Maximum allowed size in bytes (also enforced by S3).
        expires_in: Seconds until the presigned target expires.
    """

    upload_url: str
    fields: dict[str, str]
    file_key: str
    banner_url: str
    max_size: int
    expires_in: int


class BannerConfirmRequest(BaseModel):
    """Request body confirming a completed banner upload.

    Attributes:
        file_key: The object key returned by the upload-url request.
    """

    file_key: str = Field(min_length=1, max_length=512)
