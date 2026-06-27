"""Service layer for the Auracles Profile module.

Assembles the curated public profile for any user from identity columns plus
role and KYC badges. The response is an explicit allow-list: private account
fields (email, security secrets, kyc internals) are never copied into it.

Maps to: FR-SET-001/002.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.integrations import s3
from app.modules.auth.models import User, UserRole
from app.modules.profiles.schemas import (
    AvatarConfirmRequest,
    AvatarUploadUrlRequest,
    AvatarUploadUrlResponse,
    ProfileUpdateRequest,
    PublicProfileResponse,
)

# Avatars are public images served on every profile view. Keep the type set
# small (raster web image formats) and the size cap modest.
ALLOWED_AVATAR_MIME_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}
AVATAR_MAX_SIZE = 5 * 1024 * 1024
AVATAR_UPLOAD_URL_TTL_SECONDS = 900


def _avatar_public_url(settings: Settings, file_key: str) -> str:
    """Build the public URL an avatar object is served at.

    Avatars live in a public-read bucket, so the URL is deterministic from the
    key. A configured endpoint (LocalStack) is path-style; AWS is virtual-host.

    Args:
        settings: Application settings holding bucket, region, endpoint.
        file_key: The avatar object key.

    Returns:
        The public URL for the object.
    """
    bucket = settings.s3_avatars_bucket
    if settings.aws_endpoint_url is not None:
        return f"{settings.aws_endpoint_url.rstrip('/')}/{bucket}/{file_key}"
    return (
        f"https://{bucket}.s3.{settings.aws_default_region}.amazonaws.com/{file_key}"
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
        specializations=[] if is_limited else list(user.specializations),
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
        specializations=list(user.specializations),
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


async def request_avatar_upload_url(
    *,
    user: User,
    payload: AvatarUploadUrlRequest,
) -> AvatarUploadUrlResponse:
    """Return a presigned POST target for the owner's avatar.

    Validates the declared image type and size before minting the target. The
    object key is namespaced under the owner's id so one user can never target
    another's avatar. The avatar_url is returned but not persisted until the
    upload is confirmed.

    Args:
        user: The authenticated profile owner.
        payload: Declared filename, MIME type, and size.

    Returns:
        The presigned POST target plus the eventual public avatar URL.

    Raises:
        HTTPException(415): If the MIME type is not an allowed image type.
        HTTPException(413): If the declared size exceeds the avatar cap.
    """
    extension = ALLOWED_AVATAR_MIME_TYPES.get(payload.mime_type)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Avatar must be a PNG, JPEG, or WebP image.",
        )
    if payload.file_size > AVATAR_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Avatar exceeds the 5MB limit.",
        )

    settings = get_settings()
    file_key = f"avatars/{user.id}/{uuid4()}.{extension}"
    upload_target = s3.storage.presigned_post(
        bucket=settings.s3_avatars_bucket,
        key=file_key,
        mime_type=payload.mime_type,
        max_size=AVATAR_MAX_SIZE,
        expires_in=AVATAR_UPLOAD_URL_TTL_SECONDS,
    )
    logger.bind(
        module="profiles",
        action="request_avatar_upload_url",
        user_id=user.id,
    ).info("avatar_upload_url_created")
    return AvatarUploadUrlResponse(
        upload_url=str(upload_target["url"]),
        fields={
            str(name): str(value)
            for name, value in upload_target["fields"].items()
        },
        file_key=file_key,
        avatar_url=_avatar_public_url(settings, file_key),
        max_size=AVATAR_MAX_SIZE,
        expires_in=AVATAR_UPLOAD_URL_TTL_SECONDS,
    )


async def confirm_avatar_upload(
    db: AsyncSession,
    *,
    user: User,
    payload: AvatarConfirmRequest,
) -> PublicProfileResponse:
    """Persist the owner's avatar once the uploaded object is verified present.

    Args:
        db: Async session for the update.
        user: The authenticated profile owner.
        payload: The confirmed object key.

    Returns:
        The owner's profile with the avatar applied.

    Raises:
        HTTPException(403): If the key is not namespaced under the owner's id.
        HTTPException(409): If no object exists at the key (upload incomplete).
    """
    # Ownership is enforced by key prefix: the upload-url endpoint only ever
    # issues keys under the caller's own id, so a key under a different id is a
    # cross-user write attempt.
    if not payload.file_key.startswith(f"avatars/{user.id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Avatar key does not belong to this user.",
        )

    settings = get_settings()
    if not s3.storage.object_exists(settings.s3_avatars_bucket, payload.file_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Avatar upload not found. Complete the upload and retry.",
        )

    user.avatar_url = _avatar_public_url(settings, payload.file_key)
    await db.commit()
    logger.bind(
        module="profiles",
        action="confirm_avatar_upload",
        user_id=user.id,
    ).info("avatar_updated")
    return await get_own_profile(db, user=user)
