"""Service layer for the Auracles Profile module.

Assembles the curated public profile for any user from identity columns plus
role and KYC badges. The response is an explicit allow-list: private account
fields (email, security secrets, kyc internals) are never copied into it.

Maps to: FR-SET-001/002.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User, UserRole
from app.modules.profiles.schemas import (
    ProfileUpdateRequest,
    PublicProfileResponse,
)


async def _roles_for(db: AsyncSession, user_id: UUID) -> list[str]:
    """Return a user's role names, alphabetically ordered for stable output."""
    return list(
        (
            await db.execute(
                select(UserRole.role)
                .where(UserRole.user_id == user_id)
                .order_by(UserRole.role)
            )
        )
        .scalars()
        .all()
    )

PUBLIC_URL_ALLOWED_SCHEMES = ("http", "https")


def _safe_public_url(value: str | None) -> str | None:
    """Return a stored URL only when it uses a safe web scheme.

    Defends public profile responses against `javascript:`/`data:` URLs reaching
    clients that render them as links. The website field is plain text in
    storage, so the scheme is validated here at the read boundary regardless of
    how the value was persisted.

    Args:
        value: The raw stored URL, or None.

    Returns:
        The trimmed URL when it uses http/https, otherwise None.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    scheme, separator, _ = candidate.partition("://")
    if not separator or scheme.lower() not in PUBLIC_URL_ALLOWED_SCHEMES:
        return None
    return candidate


async def get_public_profile(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> PublicProfileResponse:
    """Return the curated public profile for any user.

    Args:
        db: Async session for loading the user and roles.
        user_id: UUID of the profile owner.

    Returns:
        The curated public profile payload.

    Raises:
        HTTPException(404): If no user exists with that id.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found.",
        )

    roles = await _roles_for(db, user_id)

    # A suspended account is a moderation state, not a 404: keep safe identity
    # (name, avatar, roles) visible but withhold discretionary free-text content
    # the user controls, so a suspended profile cannot keep broadcasting it.
    is_limited = user.suspended_at is not None

    return PublicProfileResponse(
        id=user.id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        headline=None if is_limited else user.headline,
        bio=None if is_limited else user.bio,
        location=None if is_limited else user.location,
        website=None if is_limited else _safe_public_url(user.website),
        roles=roles,
        kyc_verified=user.kyc_status == "verified",
        is_deactivated=user.deactivated_at is not None,
        is_limited=is_limited,
    )


async def get_own_profile(
    db: AsyncSession,
    *,
    user: User,
) -> PublicProfileResponse:
    """Return the authenticated owner's own profile.

    Unlike the public read, the owner always sees their full content even when
    the account is limited; the ``is_limited`` flag is still reported so the UI
    can surface a moderation notice.

    Args:
        db: Async session for loading the owner's roles.
        user: The authenticated profile owner.

    Returns:
        The owner's full profile payload.
    """
    roles = await _roles_for(db, user.id)
    return PublicProfileResponse(
        id=user.id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        headline=user.headline,
        bio=user.bio,
        location=user.location,
        website=_safe_public_url(user.website),
        roles=roles,
        kyc_verified=user.kyc_status == "verified",
        is_deactivated=user.deactivated_at is not None,
        is_limited=user.suspended_at is not None,
    )


async def update_profile(
    db: AsyncSession,
    *,
    user: User,
    payload: ProfileUpdateRequest,
) -> PublicProfileResponse:
    """Apply an owner's partial profile edit and return the updated profile.

    Only fields present in the request are written, so omitted fields are left
    untouched. The website scheme was already validated on the schema, so any
    stored value is safe.

    Args:
        db: Async session for the update.
        user: The authenticated profile owner.
        payload: The validated partial update.

    Returns:
        The owner's profile after the update.
    """
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    return await get_own_profile(db, user=user)
