"""Pydantic schemas for the Auracles Profile module.

Response shapes are an explicit allow-list of public identity fields. Private
account columns (email, kyc internals, security secrets) are never modelled
here, so they can never leak through a public profile response.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class PublicProfileResponse(BaseModel):
    """Curated public identity for any platform user.

    Returned for the canonical profile page regardless of role. Only fields a
    visitor is allowed to see are present; the body is assembled field-by-field
    in the service, never serialised straight from the ORM user.

    Attributes:
        id: The profile owner's user id.
        display_name: Public display name.
        avatar_url: Public avatar URL, or None.
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
    bio: str | None = None
    location: str | None = None
    website: str | None = None
    roles: list[str] = []
    kyc_verified: bool = False
    is_deactivated: bool = False
    is_limited: bool = False
