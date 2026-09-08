"""Service layer for the Auracles Profile module.

Assembles the curated public profile for any user from identity columns plus
role and KYC badges. The response is an explicit allow-list: private account
fields (email, security secrets, kyc internals) are never copied into it.

Maps to: FR-SET-001/002.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.profile_images import resolve_profile_image_url
from app.integrations import s3
from app.modules.attestation.models import Credential
from app.modules.attestation.schemas import PublicCredentialResponse
from app.modules.auth.models import User, UserRole
from app.modules.explore import service as explore_service
from app.modules.frameworks.models import Framework, Review
from app.modules.profiles.schemas import (
    AvatarConfirmRequest,
    AvatarUploadUrlRequest,
    AvatarUploadUrlResponse,
    BannerConfirmRequest,
    BannerUploadUrlRequest,
    BannerUploadUrlResponse,
    ProfileFeatured,
    ProfileStats,
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


async def _verified_credentials(
    db: AsyncSession, user_id: UUID
) -> list[PublicCredentialResponse]:
    """Return a user's verified credentials as public display rows.

    Only verified credentials are exposed; evidence keys, verification URLs,
    and review metadata are never included (handled by PublicCredentialResponse).

    Args:
        db: Async session for loading credentials.
        user_id: UUID of the credential holder.

    Returns:
        Public credential rows, newest issued first.
    """
    rows = await db.execute(
        select(Credential)
        .where(
            Credential.user_id == user_id,
            Credential.verification_status == "verified",
        )
        .order_by(Credential.issued_date.desc())
    )
    today = date.today()
    return [
        PublicCredentialResponse(
            title=credential.title,
            issuer=credential.issuer,
            credential_type=credential.credential_type,
            issued_date=credential.issued_date,
            expires_date=credential.expires_date,
            expired=(
                credential.expires_date is not None and credential.expires_date < today
            ),
        )
        for credential in rows.scalars().all()
    ]


async def _profile_stats(db: AsyncSession, user_id: UUID) -> ProfileStats:
    """Compute the public marketplace analytics shown on a profile.

    All values come from public records: published Frameworks and public reviews
    on those Frameworks. Attestation is credited to the attestor organization, so
    it is not advertised on individual user profiles.

    Args:
        db: Async session for the aggregate queries.
        user_id: UUID of the profile owner.

    Returns:
        The aggregated profile stats.
    """
    frameworks_published = int(
        await db.scalar(
            select(func.count(Framework.id)).where(
                Framework.contributor_id == user_id,
                Framework.status == "published",
            )
        )
        or 0
    )
    review_count, review_avg = (
        await db.execute(
            select(func.count(Review.id), func.avg(Review.score))
            .join(Framework, Framework.id == Review.framework_id)
            .where(Framework.contributor_id == user_id)
        )
    ).one()
    return ProfileStats(
        frameworks_published=frameworks_published,
        reviews_received=int(review_count or 0),
        average_rating=round(float(review_avg), 1) if review_avg is not None else None,
    )


async def _resolve_featured(
    db: AsyncSession,
    stored: list[dict[str, object]],
) -> list[ProfileFeatured]:
    """Build featured spotlights, resolving pinned Frameworks to live cards.

    Args:
        db: Async session for loading pinned Framework cards.
        stored: The raw featured entries from the user's JSONB column.

    Returns:
        Featured spotlights with resolved Framework cards where pinned. A pinned
        Framework that is no longer published resolves to None.
    """
    framework_ids = [
        UUID(str(item["framework_id"])) for item in stored if item.get("framework_id")
    ]
    cards = (
        await explore_service.public_framework_cards(db, framework_ids)
        if framework_ids
        else {}
    )
    resolved: list[ProfileFeatured] = []
    for item in stored:
        raw_id = item.get("framework_id")
        framework_id = UUID(str(raw_id)) if raw_id else None
        resolved.append(
            ProfileFeatured(
                title=item.get("title"),
                description=item.get("description"),
                url=item.get("url"),
                framework_id=framework_id,
                framework=cards.get(framework_id) if framework_id else None,
            )
        )
    return resolved


async def _roles_for(db: AsyncSession, user_id: UUID) -> list[str]:
    """Return a user's role names, alphabetically ordered for stable output."""
    roles = list(
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
    return list(dict.fromkeys(roles))


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
    credentials = [] if is_limited else await _verified_credentials(db, user_id)
    stats = ProfileStats() if is_limited else await _profile_stats(db, user_id)

    return PublicProfileResponse(
        id=user.id,
        display_name=user.display_name,
        avatar_url=resolve_profile_image_url(user.avatar_url),
        banner_url=(
            None if is_limited else resolve_profile_image_url(user.banner_url)
        ),
        headline=None if is_limited else user.headline,
        bio=None if is_limited else user.bio,
        location=None if is_limited else user.location,
        website=None if is_limited else _safe_public_url(user.website),
        specializations=[] if is_limited else list(user.specializations),
        links=[] if is_limited else list(user.links),
        social_links=[] if is_limited else list(user.social_links),
        featured=[] if is_limited else await _resolve_featured(db, list(user.featured)),
        experience=[] if is_limited else list(user.experience),
        education=[] if is_limited else list(user.education),
        verified_credentials=credentials,
        stats=stats,
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
        avatar_url=resolve_profile_image_url(user.avatar_url),
        banner_url=resolve_profile_image_url(user.banner_url),
        headline=user.headline,
        bio=user.bio,
        location=user.location,
        website=_safe_public_url(user.website),
        specializations=list(user.specializations),
        links=list(user.links),
        social_links=list(user.social_links),
        featured=await _resolve_featured(db, list(user.featured)),
        experience=list(user.experience),
        education=list(user.education),
        verified_credentials=await _verified_credentials(db, user.id),
        stats=await _profile_stats(db, user.id),
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
    # mode="json" so UUIDs (e.g. featured framework_id) serialise to strings,
    # which the JSONB columns can store.
    changes = payload.model_dump(exclude_unset=True, mode="json")
    if "featured" in changes:
        await _validate_featured_frameworks(db, user, changes["featured"])
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    return await get_own_profile(db, user=user)


async def _validate_featured_frameworks(
    db: AsyncSession,
    user: User,
    featured: list[dict[str, object]],
) -> None:
    """Ensure every pinned featured Framework is the owner's and published.

    Args:
        db: Async session for the ownership check.
        user: The profile owner.
        featured: The submitted featured items (already serialised).

    Raises:
        HTTPException(422): If a pinned Framework is not the owner's published one.
    """
    pinned_ids = [
        str(item["framework_id"])
        for item in featured
        if item.get("framework_id") is not None
    ]
    pinned = set(pinned_ids)
    if not pinned:
        return
    if len(pinned_ids) != len(pinned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A framework can only be featured once.",
        )
    owned = {
        str(framework_id)
        for framework_id in (
            await db.execute(
                select(Framework.id).where(
                    Framework.id.in_(pinned),
                    Framework.contributor_id == user.id,
                    Framework.status == "published",
                )
            )
        )
        .scalars()
        .all()
    }
    if pinned - owned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A featured framework must be your own published framework.",
        )


def _presign_profile_image(
    *,
    user: User,
    filename_mime: str,
    file_size: int,
    prefix: str,
) -> tuple[str, dict[str, str], str, str]:
    """Validate an image and mint a presigned POST target under a key prefix.

    Avatars and banners share the public avatars bucket, the same image type
    allow-list and size cap, and the same per-user key namespacing; only the key
    prefix differs.

    Args:
        user: The authenticated profile owner.
        filename_mime: The declared MIME type.
        file_size: The declared size in bytes.
        prefix: The object key prefix ("avatars" or "banners").

    Returns:
        A tuple of (upload_url, fields, file_key, public_url).

    Raises:
        HTTPException(415): If the MIME type is not an allowed image type.
        HTTPException(413): If the declared size exceeds the cap.
    """
    extension = ALLOWED_AVATAR_MIME_TYPES.get(filename_mime)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Image must be a PNG, JPEG, or WebP image.",
        )
    if file_size > AVATAR_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Image exceeds the 5MB limit.",
        )

    settings = get_settings()
    file_key = f"{prefix}/{user.id}/{uuid4()}.{extension}"
    target = s3.storage.presigned_post(
        bucket=settings.s3_avatars_bucket,
        key=file_key,
        mime_type=filename_mime,
        max_size=AVATAR_MAX_SIZE,
        expires_in=AVATAR_UPLOAD_URL_TTL_SECONDS,
    )
    fields = {str(name): str(value) for name, value in target["fields"].items()}
    return (
        str(target["url"]),
        fields,
        file_key,
        resolve_profile_image_url(file_key),
    )


def _verify_profile_image(*, user: User, file_key: str, prefix: str) -> str:
    """Verify an uploaded image belongs to the owner and exists in storage.

    Args:
        user: The authenticated profile owner.
        file_key: The confirmed object key.
        prefix: The expected key prefix ("avatars" or "banners").

    Returns:
        The public URL for the verified object.

    Raises:
        HTTPException(403): If the key is not namespaced under the owner's id.
        HTTPException(409): If no object exists at the key (upload incomplete).
    """
    # Ownership is enforced by key prefix: the upload-url endpoint only issues
    # keys under the caller's own id, so any other prefix is a cross-user write.
    if not file_key.startswith(f"{prefix}/{user.id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Image key does not belong to this user.",
        )
    settings = get_settings()
    if not s3.storage.object_exists(settings.s3_avatars_bucket, file_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Image upload not found. Complete the upload and retry.",
        )
    return file_key


async def request_avatar_upload_url(
    *,
    user: User,
    payload: AvatarUploadUrlRequest,
) -> AvatarUploadUrlResponse:
    """Return a presigned POST target for the owner's avatar.

    Args:
        user: The authenticated profile owner.
        payload: Declared filename, MIME type, and size.

    Returns:
        The presigned POST target plus the eventual public avatar URL.

    Raises:
        HTTPException(415): If the MIME type is not an allowed image type.
        HTTPException(413): If the declared size exceeds the cap.
    """
    upload_url, fields, file_key, public_url = _presign_profile_image(
        user=user,
        filename_mime=payload.mime_type,
        file_size=payload.file_size,
        prefix="avatars",
    )
    logger.bind(
        module="profiles", action="request_avatar_upload_url", user_id=user.id
    ).info("avatar_upload_url_created")
    return AvatarUploadUrlResponse(
        upload_url=upload_url,
        fields=fields,
        file_key=file_key,
        avatar_url=public_url,
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
    user.avatar_url = _verify_profile_image(
        user=user, file_key=payload.file_key, prefix="avatars"
    )
    await db.commit()
    logger.bind(
        module="profiles", action="confirm_avatar_upload", user_id=user.id
    ).info("avatar_updated")
    return await get_own_profile(db, user=user)


async def request_banner_upload_url(
    *,
    user: User,
    payload: BannerUploadUrlRequest,
) -> BannerUploadUrlResponse:
    """Return a presigned POST target for the owner's profile banner.

    Args:
        user: The authenticated profile owner.
        payload: Declared filename, MIME type, and size.

    Returns:
        The presigned POST target plus the eventual public banner URL.

    Raises:
        HTTPException(415): If the MIME type is not an allowed image type.
        HTTPException(413): If the declared size exceeds the cap.
    """
    upload_url, fields, file_key, public_url = _presign_profile_image(
        user=user,
        filename_mime=payload.mime_type,
        file_size=payload.file_size,
        prefix="banners",
    )
    logger.bind(
        module="profiles", action="request_banner_upload_url", user_id=user.id
    ).info("banner_upload_url_created")
    return BannerUploadUrlResponse(
        upload_url=upload_url,
        fields=fields,
        file_key=file_key,
        banner_url=public_url,
        max_size=AVATAR_MAX_SIZE,
        expires_in=AVATAR_UPLOAD_URL_TTL_SECONDS,
    )


async def confirm_banner_upload(
    db: AsyncSession,
    *,
    user: User,
    payload: BannerConfirmRequest,
) -> PublicProfileResponse:
    """Persist the owner's banner once the uploaded object is verified present.

    Args:
        db: Async session for the update.
        user: The authenticated profile owner.
        payload: The confirmed object key.

    Returns:
        The owner's profile with the banner applied.

    Raises:
        HTTPException(403): If the key is not namespaced under the owner's id.
        HTTPException(409): If no object exists at the key (upload incomplete).
    """
    user.banner_url = _verify_profile_image(
        user=user, file_key=payload.file_key, prefix="banners"
    )
    await db.commit()
    logger.bind(
        module="profiles", action="confirm_banner_upload", user_id=user.id
    ).info("banner_updated")
    return await get_own_profile(db, user=user)
