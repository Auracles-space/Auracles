"""Organizations Core service layer.

Org CRUD, membership, invitations, teams, capability reads, and the
derived attestor-role sync. RBAC lives in dependencies.py, never here.
"""

from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.profile_images import resolve_profile_image_url
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.security import hash_token
from app.integrations import s3
from app.modules.auth.models import User
from app.modules.auth.service import verify_totp_for_sensitive_action
from app.modules.gdpr.schemas import AccountDeletionBlockedReason
from app.modules.notifications.service import create_notification
from app.modules.organizations.dependencies import OrgContext
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgInvitation,
    OrgMember,
    OrgMemberNda,
    OrgTeam,
    OrgTeamCapability,
    OrgTeamMember,
)
from app.modules.organizations.schemas import (
    AdminOrgResponse,
    AdminOrgsResponse,
    LogoConfirmRequest,
    LogoUploadUrlRequest,
    LogoUploadUrlResponse,
    MemberSearchResponse,
    MemberSearchResult,
    MyInvitationResponse,
    MyInvitationsResponse,
    MyOrganizationResponse,
    OrgActionCounts,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    OrgInvitationCreateRequest,
    OrgInvitationPreviewResponse,
    OrgInvitationResponse,
    OrgInvitationsResponse,
    OrgMemberResponse,
    OrgMembersResponse,
    OrgTeamCreateRequest,
    OrgTeamMembersResponse,
    OrgTeamRenameRequest,
    OrgTeamResponse,
    OrgTeamsResponse,
    PublicOrganizationResponse,
)
from app.workers.tasks.org_notifications import send_org_invitation

INVITATION_TTL_DAYS = 7
INVITE_RATE_LIMITER = RateLimiter(namespace="org_invite", limit=20, window=3600)
MEMBER_SEARCH_RATE_LIMITER = RateLimiter(
    namespace="org_member_search", limit=30, window=60
)
_DERIVED_ROLE_MAP = {
    "attestor": "attestor",
    "contributor": "contributor",
    "operator": "operator",
}


def _mask_email(email: str) -> str:
    """Mask an email for typeahead results without exposing the full address."""
    local, _, domain = email.partition("@")
    prefix = local[:1] if len(local) > 1 else ""
    return f"{prefix}•••@{domain}"


def _escape_like_prefix(value: str) -> str:
    """Escape SQL LIKE metacharacters before prefix matching user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def create_organization(
    *,
    db: AsyncSession,
    user: User,
    payload: OrganizationCreateRequest,
) -> Organization:
    """Create an organization and seed the creator as its owner.

    Args:
        db: Async database session.
        user: Authenticated creator of the organization.
        payload: Normalized organization creation payload.

    Returns:
        The created organization row.

    Raises:
        HTTPException(409): If the slug is already in use.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()

    organization = Organization(
        slug=payload.slug,
        name=payload.name,
        country=payload.country,
        website=payload.website,
        description=payload.description,
        created_by=user_id,
    )

    try:
        async with db.begin():
            db.add(organization)
            await db.flush()
            db.add(
                OrgMember(
                    org_id=organization.id,
                    user_id=user_id,
                    role="owner",
                )
            )
            await write_audit(
                db=db,
                actor_id=user_id,
                action="org_created",
                target_type="organization",
                target_id=organization.id,
                metadata={"slug": organization.slug},
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization slug already exists.",
        ) from exc

    await db.refresh(organization)
    logger.bind(
        module="organizations",
        action="create_organization",
        user_id=user_id,
        org_id=organization.id,
    ).info("organization_created")
    return organization


async def list_my_organizations(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> list[tuple[Organization, str, list[OrgCapability]]]:
    """Return organizations, my role, and capability rows for one user.

    Args:
        db: Async database session.
        user_id: Authenticated user whose memberships should be listed.

    Returns:
        A list of tuples containing the organization, the user's role, and
        the organization's capability rows.
    """
    memberships = (
        await db.execute(
            select(Organization, OrgMember.role)
            .join(OrgMember, OrgMember.org_id == Organization.id)
            .where(
                OrgMember.user_id == user_id,
                Organization.deactivated_at.is_(None),
            )
            .order_by(desc(Organization.created_at))
        )
    ).all()
    org_ids = [organization.id for organization, _role in memberships]
    capabilities_by_org: dict[UUID, list[OrgCapability]] = defaultdict(list)

    if org_ids:
        capabilities = (
            await db.execute(
                select(OrgCapability)
                .where(OrgCapability.org_id.in_(org_ids))
                .order_by(OrgCapability.capability.asc())
            )
        ).scalars()
        for capability in capabilities:
            capabilities_by_org[capability.org_id].append(capability)

    return [
        (organization, role, capabilities_by_org.get(organization.id, []))
        for organization, role in memberships
    ]


async def caller_capability_grants(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_ids: list[UUID],
) -> dict[UUID, set[str]]:
    """Return active capabilities the caller personally holds in each org.

    Args:
        db: Async database session.
        user_id: Caller whose organization memberships determine entitlement.
        org_ids: Organizations included in the caller's response.

    Returns:
        Active capability names held by the caller, keyed by organization id.
    """
    if not org_ids:
        return {}

    grants: dict[UUID, set[str]] = {org_id: set() for org_id in org_ids}
    active_rows = await db.execute(
        select(OrgCapability.org_id, OrgCapability.capability).where(
            OrgCapability.org_id.in_(org_ids),
            OrgCapability.status == "active",
        )
    )
    active_by_org: dict[UUID, set[str]] = defaultdict(set)
    for org_id, capability in active_rows.all():
        active_by_org[org_id].add(capability)

    member_rows = await db.execute(
        select(OrgMember.org_id, OrgMember.id, OrgMember.role).where(
            OrgMember.user_id == user_id,
            OrgMember.org_id.in_(org_ids),
        )
    )
    memberships = {
        org_id: (member_id, role)
        for org_id, member_id, role in member_rows.all()
    }
    member_ids = [member_id for member_id, _role in memberships.values()]
    team_caps_by_member: dict[UUID, set[str]] = defaultdict(set)
    if member_ids:
        team_rows = await db.execute(
            select(OrgTeamMember.member_id, OrgTeamCapability.capability)
            .join(OrgTeam, OrgTeam.id == OrgTeamMember.team_id)
            .join(OrgTeamCapability, OrgTeamCapability.team_id == OrgTeam.id)
            .where(OrgTeamMember.member_id.in_(member_ids))
        )
        for member_id, capability in team_rows.all():
            team_caps_by_member[member_id].add(capability)

    for org_id in org_ids:
        membership = memberships.get(org_id)
        if membership is None:
            continue
        member_id, role = membership
        active = active_by_org.get(org_id, set())
        grants[org_id] = (
            set(active)
            if role in {"owner", "admin"}
            else active & team_caps_by_member.get(member_id, set())
        )
    return grants


# Membership roles allowed to act on offers, the queue, and invitations. Plain
# members never see these tabs, so their counts stay zero.
_ADMIN_ROLES = {"owner", "admin"}


async def count_org_actions(
    db: AsyncSession,
    *,
    admin_org_ids: list[UUID],
    member_queue_scope: dict[UUID, UUID] | None = None,
) -> dict[UUID, OrgActionCounts]:
    """Count per-org items awaiting attention, in grouped queries.

    Feeds the org-card unread dot and the inner-tab count badges. Admin orgs get
    org-wide offer/queue/invitation counts. Non-admin orgs pass a
    ``member_queue_scope`` mapping org id to the caller's membership id, and get
    a queue count scoped to attestations assigned to that member (offers and
    invitations stay zero — those tabs are admin-only).

    Args:
        db: Async database session.
        admin_org_ids: Org ids where the current user is owner or admin.
        member_queue_scope: Org id to the caller's ``OrgMember.id`` for non-admin
            memberships, used to scope the queue count to their own assignments.

    Returns:
        Mapping of org id to its offer/queue/invitation counts. Orgs with no
        pending items are omitted (absence means all zero).
    """
    member_queue_scope = member_queue_scope or {}
    if not admin_org_ids and not member_queue_scope:
        return {}

    from app.modules.attestation.models import Attestation, AttestationOffer

    now = datetime.now(UTC)
    offers: dict[UUID, int] = {}
    queue: dict[UUID, int] = {}
    invitations: dict[UUID, int] = {}

    if admin_org_ids:
        offer_rows = await db.execute(
            select(AttestationOffer.org_id, func.count())
            .where(
                AttestationOffer.org_id.in_(admin_org_ids),
                AttestationOffer.status == "offered",
                AttestationOffer.expires_at > now,
            )
            .group_by(AttestationOffer.org_id)
        )
        for org_id, count in offer_rows.all():
            offers[org_id] = int(count)

        queue_rows = await db.execute(
            select(Attestation.attestor_org_id, func.count())
            .where(
                Attestation.attestor_org_id.in_(admin_org_ids),
                Attestation.status.in_(_IN_FLIGHT_REVIEW_STATUSES),
            )
            .group_by(Attestation.attestor_org_id)
        )
        for org_id, count in queue_rows.all():
            if org_id is not None:
                queue[org_id] = int(count)

        invite_rows = await db.execute(
            select(OrgInvitation.org_id, func.count())
            .where(
                OrgInvitation.org_id.in_(admin_org_ids),
                OrgInvitation.status == "pending",
            )
            .group_by(OrgInvitation.org_id)
        )
        for org_id, count in invite_rows.all():
            invitations[org_id] = int(count)

    if member_queue_scope:
        member_ids = list(member_queue_scope.values())
        member_queue_rows = await db.execute(
            select(
                Attestation.attestor_org_id,
                Attestation.reviewing_member_id,
                func.count(),
            )
            .where(
                Attestation.attestor_org_id.in_(list(member_queue_scope.keys())),
                Attestation.reviewing_member_id.in_(member_ids),
                Attestation.status.in_(_IN_FLIGHT_REVIEW_STATUSES),
            )
            .group_by(
                Attestation.attestor_org_id, Attestation.reviewing_member_id
            )
        )
        for org_id, member_id, count in member_queue_rows.all():
            # Only count rows assigned to *this* caller's membership in that org.
            if org_id is not None and member_queue_scope.get(org_id) == member_id:
                queue[org_id] = int(count)

    scoped_org_ids = set(admin_org_ids) | set(member_queue_scope)
    return {
        org_id: OrgActionCounts(
            offers=offers.get(org_id, 0),
            queue=queue.get(org_id, 0),
            invitations=invitations.get(org_id, 0),
        )
        for org_id in scoped_org_ids
    }


async def get_public_org(
    db: AsyncSession,
    *,
    slug: str,
) -> PublicOrganizationResponse:
    """Return the public profile for an active organization by slug.

    Args:
        db: Async database session.
        slug: Public organization slug from the request path.

    Returns:
        The public-safe organization profile.

    Raises:
        HTTPException(404): If the organization is unknown, deactivated, or suspended.
    """
    organization = await db.scalar(
        select(Organization).where(
            func.lower(Organization.slug) == slug.lower(),
            Organization.deactivated_at.is_(None),
            Organization.suspended_at.is_(None),
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    member_count = (
        await db.scalar(
            select(func.count())
            .select_from(OrgMember)
            .where(OrgMember.org_id == organization.id)
        )
    ) or 0
    active_capabilities = list(
        (
            await db.scalars(
                select(OrgCapability.capability).where(
                    OrgCapability.org_id == organization.id,
                    OrgCapability.status == "active",
                )
            )
        ).all()
    )

    return PublicOrganizationResponse(
        slug=organization.slug,
        name=organization.name,
        logo_key=organization.logo_key,
        country=organization.country,
        website=organization.website,
        description=organization.description,
        active_capabilities=sorted(active_capabilities),
        member_count=member_count,
        created_at=organization.created_at,
    )


async def update_organization(
    db: AsyncSession,
    *,
    context: OrgContext,
    payload: OrganizationUpdateRequest,
) -> OrganizationResponse:
    """Apply a partial organization profile update.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.
        payload: Partial update fields for the organization.

    Returns:
        The updated organization response.
    """
    org_id = context.org.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        organization = await db.scalar(
            select(Organization).where(Organization.id == org_id)
        )
        assert organization is not None
        for field in ("name", "website", "description"):
            value = getattr(payload, field)
            if value is not None:
                setattr(organization, field, value)

    await db.refresh(organization)
    return OrganizationResponse.model_validate(organization)


LOGO_MAX_SIZE = 5 * 1024 * 1024
LOGO_UPLOAD_URL_TTL_SECONDS = 900
_LOGO_KEY_PREFIX = "org-logos"
ALLOWED_LOGO_MIME_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def request_org_logo_upload_url(
    *,
    context: OrgContext,
    payload: LogoUploadUrlRequest,
) -> LogoUploadUrlResponse:
    """Return a presigned POST target for an organization logo upload.

    Validates the declared image type and size, then mints a target keyed under
    the org's own namespace (``org-logos/{org_id}/{uuid}.{ext}``) in the public
    avatars bucket. The key is issued server-side so the later confirm step can
    trust the namespace as the ownership boundary.

    Args:
        context: Resolved org/member/user context (admin+ enforced at the dep).
        payload: Declared MIME type and size in bytes.

    Returns:
        The presigned POST target plus the key and upload constraints.

    Raises:
        HTTPException(415): If the MIME type is not an allowed image type.
        HTTPException(413): If the declared size exceeds the cap.
    """
    extension = ALLOWED_LOGO_MIME_TYPES.get(payload.mime_type)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Logo must be a PNG, JPEG, or WebP image.",
        )
    if payload.file_size > LOGO_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Logo exceeds the 5MB limit.",
        )

    settings = get_settings()
    file_key = f"{_LOGO_KEY_PREFIX}/{context.org.id}/{uuid4()}.{extension}"
    target = s3.storage.presigned_post(
        bucket=settings.s3_avatars_bucket,
        key=file_key,
        mime_type=payload.mime_type,
        max_size=LOGO_MAX_SIZE,
        expires_in=LOGO_UPLOAD_URL_TTL_SECONDS,
    )
    fields = {str(name): str(value) for name, value in target["fields"].items()}
    logger.bind(
        module="organizations",
        action="request_org_logo_upload_url",
        user_id=context.user.id,
        org_id=context.org.id,
    ).info("org_logo_upload_url_created")
    return LogoUploadUrlResponse(
        upload_url=str(target["url"]),
        fields=fields,
        file_key=file_key,
        max_size=LOGO_MAX_SIZE,
        expires_in=LOGO_UPLOAD_URL_TTL_SECONDS,
    )


async def confirm_org_logo_upload(
    db: AsyncSession,
    *,
    context: OrgContext,
    payload: LogoConfirmRequest,
) -> OrganizationResponse:
    """Persist an organization logo once the uploaded object is verified.

    Ownership is enforced by key namespace: the upload-url step only ever issues
    keys under the caller org's id, so any other prefix is a cross-org write and
    is rejected. The object must also exist, guarding against confirming a key
    whose upload never completed.

    Args:
        db: Async database session.
        context: Resolved org/member/user context (admin+ enforced at the dep).
        payload: The confirmed object key.

    Returns:
        The organization response with the logo applied.

    Raises:
        HTTPException(403): If the key is not namespaced under the org's id.
        HTTPException(409): If no object exists at the key (upload incomplete).
    """
    # Capture ids as primitives before any rollback: the RBAC dep loaded these
    # ORM objects on this session, and rolling it back below would expire them,
    # turning a later attribute read into lazy IO in the wrong context.
    org_id = context.org.id
    actor_id = context.user.id
    if not payload.file_key.startswith(f"{_LOGO_KEY_PREFIX}/{org_id}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Logo key does not belong to this organization.",
        )

    settings = get_settings()
    if not s3.storage.object_exists(settings.s3_avatars_bucket, payload.file_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Logo upload not found. Complete the upload and retry.",
        )

    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        organization = await db.scalar(
            select(Organization).where(Organization.id == org_id)
        )
        assert organization is not None
        organization.logo_key = payload.file_key
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_logo_updated",
            target_type="organization",
            target_id=org_id,
        )

    await db.refresh(organization)
    logger.bind(
        module="organizations",
        action="confirm_org_logo_upload",
        user_id=actor_id,
        org_id=org_id,
    ).info("org_logo_updated")
    return OrganizationResponse.model_validate(organization)


async def deactivate_organization(
    db: AsyncSession,
    *,
    context: OrgContext,
) -> None:
    """Soft-delete an organization once all active capabilities are wound down.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.

    Raises:
        HTTPException(409): If any capability remains active.
    """
    org_id = context.org.id
    actor_id = context.user.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        active_capabilities = await db.scalar(
            select(func.count())
            .select_from(OrgCapability)
            .where(
                OrgCapability.org_id == org_id,
                OrgCapability.status == "active",
            )
        )
        if active_capabilities:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Wind down active capabilities before deactivating the "
                    "organization."
                ),
            )

        organization = await db.scalar(
            select(Organization).where(Organization.id == org_id).with_for_update()
        )
        assert organization is not None
        organization.deactivated_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_deactivated",
            target_type="organization",
            target_id=organization.id,
        )


async def list_members(
    db: AsyncSession,
    *,
    context: OrgContext,
) -> OrgMembersResponse:
    """List organization members with caller-scoped email visibility.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.

    Returns:
        The organization's members ordered by join time.
    """
    include_email = context.member.role in {"owner", "admin"}
    rows = (
        await db.execute(
            select(OrgMember, User.display_name, User.email)
            .join(User, User.id == OrgMember.user_id)
            .where(OrgMember.org_id == context.org.id)
            .order_by(OrgMember.joined_at.asc(), OrgMember.id.asc())
        )
    ).all()
    # Members holding a current-version NDA signature. The trial-nomination
    # picker filters on this so only NDA-signed members are selectable.
    current_version = get_settings().org_member_nda_version
    signed_member_ids = set(
        (
            await db.scalars(
                select(OrgMemberNda.member_id)
                .join(OrgMember, OrgMember.id == OrgMemberNda.member_id)
                .where(
                    OrgMember.org_id == context.org.id,
                    OrgMemberNda.nda_version == current_version,
                )
            )
        ).all()
    )
    return OrgMembersResponse(
        members=[
            OrgMemberResponse(
                id=member.id,
                user_id=member.user_id,
                display_name=display_name,
                email=email if include_email else None,
                role=member.role,
                joined_at=member.joined_at,
                nda_signed=member.id in signed_member_ids,
            )
            for member, display_name, email in rows
        ]
    )


async def _get_member_row(
    db: AsyncSession,
    *,
    org_id: UUID,
    member_id: UUID,
    for_update: bool = False,
) -> OrgMember:
    """Load one member row for an organization or raise 404."""
    statement = select(OrgMember).where(
        OrgMember.id == member_id,
        OrgMember.org_id == org_id,
    )
    if for_update:
        statement = statement.with_for_update()
    member = await db.scalar(statement)
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found.",
        )
    return member


async def remove_member(
    db: AsyncSession,
    *,
    context: OrgContext,
    member_id: UUID,
) -> None:
    """Remove a member or allow a non-owner to leave the organization.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.
        member_id: Target membership row id in this organization.

    Raises:
        HTTPException(403): Caller lacks permission to remove the target member.
        HTTPException(404): Target member does not belong to this organization.
        HTTPException(409): The organization owner cannot be removed.
    """
    org_id = context.org.id
    actor_id = context.user.id
    caller_role = context.member.role
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        target = await _get_member_row(
            db,
            org_id=org_id,
            member_id=member_id,
            for_update=True,
        )
        if target.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transfer ownership before removing the owner.",
            )

        is_self = target.user_id == actor_id
        if not is_self and caller_role == "member":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to remove this member.",
            )
        if caller_role == "admin" and target.role == "admin" and not is_self:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can remove an admin.",
            )

        await _guard_and_release_member_reviews(db, member_id=target.id)
        await _guard_and_release_member_deliveries(db, member_id=target.id)

        removed_user_id = target.user_id
        await db.delete(target)
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_member_removed",
            target_type="organization",
            target_id=org_id,
            metadata={
                "removed_user_id": str(removed_user_id),
                "self_removed": is_self,
            },
        )

    await sync_derived_roles(db, user_id=removed_user_id)


_IN_FLIGHT_REVIEW_STATUSES = (
    "accepted",
    "in_review",
    "report_submitted",
    "revision_requested",
    "disputed",
)


async def _guard_and_release_member_reviews(
    db: AsyncSession,
    *,
    member_id: UUID,
) -> None:
    """Block removal on started reviews; unassign unstarted ones.

    A member holding a started, in-flight attestation review cannot be removed
    until a platform admin resolves it (409). Unstarted assignments are simply
    unstaffed (``reviewing_member_id`` cleared) so the org can restaff.

    Raises:
        HTTPException(409): The member has a started, in-flight review.
    """
    from app.modules.attestation.models import Attestation

    started = await db.scalar(
        select(func.count())
        .select_from(Attestation)
        .where(
            Attestation.reviewing_member_id == member_id,
            Attestation.review_started_at.is_not(None),
            Attestation.status.in_(_IN_FLIGHT_REVIEW_STATUSES),
        )
    )
    if started and int(started) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This member has a started attestation review. A platform admin "
                "must resolve it before removal."
            ),
        )
    result = await db.execute(
        update(Attestation)
        .where(
            Attestation.reviewing_member_id == member_id,
            Attestation.review_started_at.is_(None),
            Attestation.status.in_(_IN_FLIGHT_REVIEW_STATUSES),
        )
        .values(reviewing_member_id=None)
        .returning(Attestation.id)
    )
    for (attestation_id,) in result.all():
        await write_audit(
            db=db,
            actor_id=None,
            action="attestation_reviewer_unassigned",
            target_type="attestation",
            target_id=attestation_id,
            metadata={"reason": "member_removed", "member_id": str(member_id)},
        )


async def _guard_and_release_member_deliveries(
    db: AsyncSession,
    *,
    member_id: UUID,
) -> None:
    """Block removal on started deliveries; unassign unstarted staffed work."""
    from app.modules.projects.models import Milestone, Proposal

    started = await db.scalar(
        select(func.count())
        .select_from(Proposal)
        .join(Milestone, Milestone.project_id == Proposal.project_id)
        .where(
            Proposal.delivering_member_id == member_id,
            Proposal.status == "accepted",
            Milestone.status != "pending",
        )
    )
    if started and int(started) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This member has a started Project delivery. A platform admin "
                "must resolve it before removal."
            ),
        )

    result = await db.execute(
        update(Proposal)
        .where(
            Proposal.delivering_member_id == member_id,
            Proposal.status.in_(("pending", "accepted")),
        )
        .values(delivering_member_id=None)
        .returning(Proposal.id)
    )
    for (proposal_id,) in result.all():
        await write_audit(
            db=db,
            actor_id=None,
            action="proposal_delivering_member_unassigned",
            target_type="proposal",
            target_id=proposal_id,
            metadata={"reason": "member_removed", "member_id": str(member_id)},
        )


ATTESTORS_TEAM_NAME = "Attestors"


async def ensure_member_on_attestor_team(
    db: AsyncSession, *, org_id: UUID, member_id: UUID
) -> None:
    """Place one member on the org's Attestors team, enabling attestor on it.

    Under team-scoped capability rights the derived ``attestor`` role is granted
    through team membership. Being assigned to perform an attestation (nominated
    at approval, or staffed on an accepted offer) makes the member an attestor,
    so this ensures a dedicated "Attestors" team exists (creating it on first
    use), enables the attestor capability on it, and adds the member.

    Runs inside the caller's transaction; the caller triggers the derived-role
    sync (``sync_derived_roles``) after its transaction commits.
    """
    team_id = await db.scalar(
        select(OrgTeam.id).where(
            OrgTeam.org_id == org_id,
            OrgTeam.name == ATTESTORS_TEAM_NAME,
        )
    )
    if team_id is None:
        team = OrgTeam(org_id=org_id, name=ATTESTORS_TEAM_NAME)
        db.add(team)
        await db.flush()
        team_id = team.id

    await db.execute(
        pg_insert(OrgTeamCapability)
        .values(team_id=team_id, capability="attestor")
        .on_conflict_do_nothing()
    )
    await db.execute(
        pg_insert(OrgTeamMember)
        .values(team_id=team_id, member_id=member_id)
        .on_conflict_do_nothing()
    )


async def sync_derived_roles(db: AsyncSession, *, user_id: UUID) -> None:
    """Grant or revoke org-derived user roles for one user's live memberships.

    A user holds a derived marketplace role only when an organization's
    capability is active and the user is either an owner/admin in that org or
    belongs to a team with the matching capability enabled. This sync selects
    and mutates only ``source="derived"`` rows. Self-selected roles are left
    untouched.
    """
    from app.modules.auth.models import UserRole

    should_have_role_by_name: dict[str, bool] = {}
    for capability, role in _DERIVED_ROLE_MAP.items():
        team_grant = (
            select(1)
            .select_from(OrgTeamMember)
            .join(OrgTeam, OrgTeam.id == OrgTeamMember.team_id)
            .join(
                OrgTeamCapability,
                (OrgTeamCapability.team_id == OrgTeam.id)
                & (OrgTeamCapability.capability == capability),
            )
            .where(
                OrgTeamMember.member_id == OrgMember.id,
                OrgTeam.org_id == Organization.id,
            )
            .exists()
        )
        stmt = (
            select(1)
            .select_from(OrgMember)
            .join(Organization, Organization.id == OrgMember.org_id)
            .join(
                OrgCapability,
                (OrgCapability.org_id == Organization.id)
                & (OrgCapability.capability == capability)
                & (OrgCapability.status == "active"),
            )
            .where(
                OrgMember.user_id == user_id,
                Organization.suspended_at.is_(None),
                Organization.deactivated_at.is_(None),
                or_(
                    OrgMember.role.in_(("owner", "admin")),
                    team_grant,
                ),
            )
            .limit(1)
        )
        should_have_role_by_name[role] = (await db.scalar(stmt)) is not None

    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        for role, should_have_role in should_have_role_by_name.items():
            current_role = await db.scalar(
                select(UserRole)
                .where(
                    UserRole.user_id == user_id,
                    UserRole.role == role,
                    UserRole.source == "derived",
                )
                .with_for_update()
            )

            if should_have_role and current_role is None:
                db.add(
                    UserRole(
                        user_id=user_id,
                        role=role,
                        source="derived",
                        approved_at=datetime.now(UTC),
                    )
                )
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="org_derived_role_synced",
                    target_type="user",
                    target_id=user_id,
                    metadata={"role": role, "granted": True},
                )
            elif not should_have_role and current_role is not None:
                await db.delete(current_role)
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="org_derived_role_synced",
                    target_type="user",
                    target_id=user_id,
                    metadata={"role": role, "granted": False},
                )


async def _sync_team_member_roles(db: AsyncSession, team_id: UUID) -> None:
    """Re-evaluate derived roles for every member of one team."""
    user_ids = (
        await db.scalars(
            select(OrgMember.user_id)
            .join(OrgTeamMember, OrgTeamMember.member_id == OrgMember.id)
            .where(OrgTeamMember.team_id == team_id)
        )
    ).all()
    for user_id in user_ids:
        await sync_derived_roles(db, user_id=user_id)


async def change_member_role(
    db: AsyncSession,
    *,
    context: OrgContext,
    member_id: UUID,
    new_role: str,
) -> OrgMemberResponse:
    """Change one member between the member and admin roles.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.
        member_id: Target membership row id in this organization.
        new_role: The replacement role, restricted to ``member`` or ``admin``.

    Returns:
        The updated member response with email included for the owner caller.

    Raises:
        HTTPException(404): Target member does not belong to this organization.
        HTTPException(409): The owner role must be moved through transfer flow.
    """
    org_id = context.org.id
    actor_id = context.user.id
    synced_user_id: UUID | None = None
    response: OrgMemberResponse | None = None
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        target = await _get_member_row(
            db,
            org_id=org_id,
            member_id=member_id,
            for_update=True,
        )
        if target.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Use transfer ownership to change the owner role.",
            )

        old_role = target.role
        target.role = new_role
        user_row = await db.scalar(select(User).where(User.id == target.user_id))
        assert user_row is not None
        if old_role != new_role:
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="org_member_role_changed",
                target_type="organization",
                target_id=org_id,
                metadata={
                    "member_user_id": str(target.user_id),
                    "from_role": old_role,
                    "to_role": new_role,
                },
            )
        synced_user_id = target.user_id
        response = OrgMemberResponse(
            id=target.id,
            user_id=target.user_id,
            display_name=user_row.display_name,
            email=user_row.email,
            role=target.role,
            joined_at=target.joined_at,
        )

    assert synced_user_id is not None
    assert response is not None
    await sync_derived_roles(db, user_id=synced_user_id)
    return response


async def transfer_ownership(
    db: AsyncSession,
    redis: Redis,
    *,
    context: OrgContext,
    new_owner_member_id: UUID,
    totp_code: str,
) -> None:
    """Transfer organization ownership to another existing member.

    Args:
        db: Async database session.
        redis: Redis client used for TOTP verification state.
        context: Resolved organization/member/user context from RBAC dependency.
        new_owner_member_id: Target membership row that should become owner.
        totp_code: TOTP or backup code provided by the current owner.

    Raises:
        HTTPException(401): The authenticated owner row can no longer be loaded.
        HTTPException(403): The sensitive-action TOTP check fails.
        HTTPException(404): The target membership does not belong to this organization.
        HTTPException(409): The transfer target already owns the organization.
    """
    org_id = context.org.id
    actor_id = context.user.id
    current_member_id = context.member.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        locked_user = await db.get(User, actor_id, with_for_update=True)
        if locked_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        await verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=locked_user,
            code=totp_code,
        )

        target = await _get_member_row(
            db,
            org_id=org_id,
            member_id=new_owner_member_id,
            for_update=True,
        )
        if target.id == current_member_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already own this organization.",
            )

        current_owner = await db.scalar(
            select(OrgMember)
            .where(
                OrgMember.org_id == org_id,
                OrgMember.role == "owner",
            )
            .with_for_update()
        )
        assert current_owner is not None
        current_owner.role = "admin"
        await db.flush()
        target.role = "owner"
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_ownership_transferred",
            target_type="organization",
            target_id=org_id,
            metadata={"new_owner_user_id": str(target.user_id)},
        )


async def create_invitation(
    db: AsyncSession,
    redis: Redis,
    *,
    context: OrgContext,
    payload: OrgInvitationCreateRequest,
) -> OrgInvitationResponse:
    """Create a pending invitation and dispatch its email after commit.

    Args:
        db: Async database session.
        redis: Redis client used by the per-org invitation rate limiter.
        context: Resolved organization/member/user context from RBAC dependency.
        payload: Lowercased invitee email and requested role.

    Returns:
        The created pending invitation.

    Raises:
        HTTPException(409): The invite already exists or the user is already a member.
        HTTPException(429): This organization exceeded its hourly invite budget.
    """
    org_id = context.org.id
    actor_id = context.user.id
    org_name = context.org.name
    invited_via_user_id = payload.user_id is not None
    await INVITE_RATE_LIMITER.check(cast(RedisCounter, redis), str(org_id))
    if db.in_transaction():
        await db.rollback()

    raw_token = secrets.token_urlsafe(32)
    if invited_via_user_id:
        target_user = await db.scalar(select(User).where(User.id == payload.user_id))
        if target_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )
        email = target_user.email.lower()
    else:
        assert payload.email is not None
        email = payload.email
    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            existing_member = await db.scalar(
                select(OrgMember)
                .join(User, User.id == OrgMember.user_id)
                .where(
                    OrgMember.org_id == org_id,
                    func.lower(User.email) == email,
                )
            )
            if existing_member is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This user is already a member.",
                )

            invitation = OrgInvitation(
                org_id=org_id,
                email=email,
                role=payload.role,
                invited_by=actor_id,
                status="pending",
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(UTC) + timedelta(days=INVITATION_TTL_DAYS),
            )
            db.add(invitation)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="org_member_invited",
                target_type="organization",
                target_id=org_id,
                metadata={"role": payload.role},
            )
            invitee = await db.scalar(
                select(User).where(func.lower(User.email) == email)
            )
            if invitee is not None:
                await create_notification(
                    db=db,
                    user_id=invitee.id,
                    notification_type="org_invitation_received",
                    title=f"Invitation to join {org_name}",
                    body=f"You've been invited to join {org_name} as {payload.role}.",
                    link="/settings/organizations",
                    payload={"org_id": str(org_id)},
                    dedupe_key=f"org-invitation-received:{invitation.id}",
                )
            response = OrgInvitationResponse.model_validate(invitation)
            if invited_via_user_id:
                response.email = _mask_email(email)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending invitation for this email already exists.",
        ) from exc

    send_org_invitation.delay(email, org_name, payload.role, raw_token)
    return response


async def search_members(
    db: AsyncSession,
    redis: Redis,
    *,
    context: OrgContext,
    q: str,
) -> MemberSearchResponse:
    """Return masked invite suggestions for one organization admin."""
    cleaned = q.strip().lower()
    await MEMBER_SEARCH_RATE_LIMITER.check(
        cast(RedisCounter, redis),
        str(context.user.id),
    )
    if len(cleaned) < 3:
        return MemberSearchResponse(results=[])

    pattern = f"{_escape_like_prefix(cleaned)}%"
    member_subquery = select(OrgMember.user_id).where(
        OrgMember.org_id == context.org.id
    )
    pending_invitation_exists = (
        select(OrgInvitation.id)
        .where(
            OrgInvitation.org_id == context.org.id,
            OrgInvitation.status == "pending",
            func.lower(OrgInvitation.email) == func.lower(User.email),
        )
        .exists()
    )
    rows = (
        await db.execute(
            select(User.id, User.display_name, User.avatar_url, User.email)
            .where(
                or_(
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(User.display_name).like(pattern, escape="\\"),
                ),
                User.id.not_in(member_subquery),
                ~pending_invitation_exists,
            )
            .order_by(User.display_name.asc(), User.id.asc())
            .limit(10)
        )
    ).all()

    await write_audit(
        db=db,
        actor_id=context.user.id,
        action="org_member_searched",
        target_type="organization",
        target_id=context.org.id,
        metadata={"query_length": len(cleaned)},
    )
    await db.commit()

    return MemberSearchResponse(
        results=[
            MemberSearchResult(
                user_id=user_id,
                display_name=display_name,
                avatar_url=resolve_profile_image_url(avatar_url),
                masked_email=_mask_email(email),
            )
            for user_id, display_name, avatar_url, email in rows
        ]
    )


async def list_invitations(
    db: AsyncSession,
    *,
    context: OrgContext,
) -> OrgInvitationsResponse:
    """List pending invitations for one organization.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.

    Returns:
        Pending invitations ordered newest-first.
    """
    invitations = (
        await db.scalars(
            select(OrgInvitation)
            .where(
                OrgInvitation.org_id == context.org.id,
                OrgInvitation.status == "pending",
            )
            .order_by(OrgInvitation.created_at.desc(), OrgInvitation.id.desc())
        )
    ).all()
    return OrgInvitationsResponse(
        invitations=[
            OrgInvitationResponse.model_validate(invitation)
            for invitation in invitations
        ]
    )


async def list_received_invitations(
    db: AsyncSession,
    *,
    user: User,
) -> MyInvitationsResponse:
    """List live pending invitations addressed to the authenticated user.

    Args:
        db: Async database session.
        user: The authenticated invitee.

    Returns:
        Pending invitations for the user's email, newest first.
    """
    rows = (
        await db.execute(
            select(OrgInvitation, Organization, User.display_name)
            .join(Organization, Organization.id == OrgInvitation.org_id)
            .join(User, User.id == OrgInvitation.invited_by, isouter=True)
            .where(
                OrgInvitation.status == "pending",
                func.lower(OrgInvitation.email) == user.email.lower(),
                Organization.deactivated_at.is_(None),
                Organization.suspended_at.is_(None),
                OrgInvitation.expires_at > datetime.now(UTC),
            )
            .order_by(OrgInvitation.created_at.desc(), OrgInvitation.id.desc())
        )
    ).all()

    return MyInvitationsResponse(
        invitations=[
            MyInvitationResponse(
                id=invitation.id,
                org=OrganizationResponse.model_validate(organization),
                role=invitation.role,
                invited_by_name=inviter_name,
                created_at=invitation.created_at,
            )
            for invitation, organization, inviter_name in rows
        ]
    )


async def revoke_invitation(
    db: AsyncSession,
    *,
    context: OrgContext,
    invitation_id: UUID,
) -> None:
    """Revoke one pending organization invitation.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC dependency.
        invitation_id: Invitation id scoped to this organization.

    Raises:
        HTTPException(404): Invitation does not belong to this organization.
        HTTPException(409): Only pending invitations can be revoked.
    """
    org_id = context.org.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        invitation = await db.scalar(
            select(OrgInvitation)
            .where(
                OrgInvitation.id == invitation_id,
                OrgInvitation.org_id == org_id,
            )
            .with_for_update()
        )
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation not found.",
            )
        if invitation.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only pending invitations can be revoked.",
            )
        invitation.status = "revoked"
        invitation.responded_at = datetime.now(UTC)


async def _get_live_invitation(
    db: AsyncSession,
    *,
    token: str,
) -> tuple[OrgInvitation, Organization]:
    """Resolve a pending invitation and its active org by raw token.

    Args:
        db: Async database session.
        token: Raw invitation token from the URL path.

    Returns:
        The pending invitation and its active organization.

    Raises:
        HTTPException(404): Unknown token, terminal status, or dead org.
        HTTPException(409): Token has a terminal status (accepted/declined/revoked).
        HTTPException(410): Pending but past its expiry timestamp.
    """
    invitation = await db.scalar(
        select(OrgInvitation).where(OrgInvitation.token_hash == hash_token(token))
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )
    if invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation is not available.",
        )
    organization = await db.scalar(
        select(Organization).where(
            Organization.id == invitation.org_id,
            Organization.deactivated_at.is_(None),
            Organization.suspended_at.is_(None),
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation is not available.",
        )
    if invitation.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invitation has expired.",
        )
    return invitation, organization


async def _get_live_invitation_by_id(
    db: AsyncSession,
    *,
    invitation_id: UUID,
) -> tuple[OrgInvitation, Organization]:
    """Resolve a pending invitation and its active org by id.

    Args:
        db: Async database session.
        invitation_id: Invitation id from the received-invitations inbox.

    Returns:
        The pending invitation and its active organization.

    Raises:
        HTTPException(404): Unknown id or dead org.
        HTTPException(409): Invitation is not pending.
        HTTPException(410): Pending invitation is expired.
    """
    invitation = await db.scalar(
        select(OrgInvitation).where(OrgInvitation.id == invitation_id)
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )
    if invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation is not available.",
        )
    organization = await db.scalar(
        select(Organization).where(
            Organization.id == invitation.org_id,
            Organization.deactivated_at.is_(None),
            Organization.suspended_at.is_(None),
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation is not available.",
        )
    if invitation.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invitation has expired.",
        )
    return invitation, organization


async def preview_invitation(
    db: AsyncSession,
    *,
    token: str,
) -> OrgInvitationPreviewResponse:
    """Return a preview of a live invitation without consuming it.

    Args:
        db: Async database session.
        token: Raw invitation token from the URL path.

    Returns:
        The org name, slug, invited role, and expiry for the invitee to review.

    Raises:
        HTTPException(404/409/410): Delegated from _get_live_invitation.
    """
    invitation, organization = await _get_live_invitation(db, token=token)
    return OrgInvitationPreviewResponse(
        org_name=organization.name,
        org_slug=organization.slug,
        role=invitation.role,
        expires_at=invitation.expires_at,
    )


async def _finalize_accept(
    db: AsyncSession,
    *,
    user: User,
    invitation: OrgInvitation,
    organization: Organization,
) -> MyOrganizationResponse:
    """Accept a resolved, email-matched invitation."""
    invitation_id = invitation.id
    invited_role = invitation.role
    invited_by = invitation.invited_by
    org_id = organization.id
    org_name = organization.name
    user_id = user.id
    user_display_name = user.display_name

    if db.in_transaction():
        await db.rollback()

    try:
        async with db.begin():
            locked_invitation = await db.scalar(
                select(OrgInvitation)
                .where(OrgInvitation.id == invitation_id)
                .with_for_update()
            )
            if locked_invitation is None or locked_invitation.status != "pending":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Invitation is not available.",
                )
            locked_invitation.status = "accepted"
            locked_invitation.responded_at = datetime.now(UTC)

            member = OrgMember(
                org_id=org_id,
                user_id=user_id,
                role=invited_role,
            )
            db.add(member)
            await write_audit(
                db=db,
                actor_id=user_id,
                action="org_member_joined",
                target_type="organization",
                target_id=org_id,
                metadata={"role": invited_role},
            )
            await create_notification(
                db=db,
                user_id=invited_by,
                notification_type="org_invitation_accepted",
                title=f"{user_display_name} joined {org_name}",
                body=f"{user_display_name} accepted the invitation to join {org_name}.",
                link="/settings/organizations",
                payload={"org_id": str(org_id)},
                dedupe_key=f"org-invite-accepted:{invitation_id}",
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a member of this organization.",
        ) from exc

    await sync_derived_roles(db, user_id=user_id)

    capabilities: dict[str, str] = {}
    cap_rows = (
        await db.scalars(select(OrgCapability).where(OrgCapability.org_id == org_id))
    ).all()
    for cap in cap_rows:
        capabilities[cap.capability] = cap.status

    org_obj = await db.scalar(select(Organization).where(Organization.id == org_id))
    if org_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    return MyOrganizationResponse(
        org=OrganizationResponse.model_validate(org_obj),
        role=invited_role,
        capabilities=capabilities,
        nda_required=capabilities.get("attestor") in ("pending", "active"),
    )


async def _finalize_decline(
    db: AsyncSession,
    *,
    user: User,
    invitation: OrgInvitation,
    organization: Organization,
) -> None:
    """Decline a resolved, email-matched invitation."""
    invitation_id = invitation.id
    invited_by = invitation.invited_by
    org_id = organization.id
    org_name = organization.name
    user_display_name = user.display_name

    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        locked_invitation = await db.scalar(
            select(OrgInvitation)
            .where(OrgInvitation.id == invitation_id)
            .with_for_update()
        )
        if locked_invitation is None or locked_invitation.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Invitation is not available.",
            )
        locked_invitation.status = "declined"
        locked_invitation.responded_at = datetime.now(UTC)

        await create_notification(
            db=db,
            user_id=invited_by,
            notification_type="org_invitation_declined",
            title=f"{user_display_name} declined the invitation",
            body=f"{user_display_name} declined the invitation to join {org_name}.",
            link="/settings/organizations",
            payload={"org_id": str(org_id)},
            dedupe_key=f"org-invite-declined:{invitation_id}",
        )


async def accept_invitation(
    db: AsyncSession,
    *,
    user: User,
    token: str,
) -> MyOrganizationResponse:
    """Accept an invitation and join the organization.

    Args:
        db: Async database session.
        user: Authenticated user accepting the invitation.
        token: Raw invitation token from the URL path.

    Returns:
        The new membership in the MyOrganizationResponse shape.

    Raises:
        HTTPException(403): Authenticated user's email does not match the invite.
        HTTPException(404/409/410): Delegated from _get_live_invitation.
    """
    invitation, organization = await _get_live_invitation(db, token=token)
    if user.email.lower() != invitation.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address.",
        )
    return await _finalize_accept(
        db=db,
        user=user,
        invitation=invitation,
        organization=organization,
    )


async def decline_invitation(
    db: AsyncSession,
    *,
    user: User,
    token: str,
) -> None:
    """Decline an invitation without joining.

    Args:
        db: Async database session.
        user: Authenticated user declining the invitation.
        token: Raw invitation token from the URL path.

    Raises:
        HTTPException(403): Authenticated user's email does not match the invite.
        HTTPException(404/409/410): Delegated from _get_live_invitation.
    """
    invitation, organization = await _get_live_invitation(db, token=token)
    if user.email.lower() != invitation.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address.",
        )
    await _finalize_decline(
        db=db,
        user=user,
        invitation=invitation,
        organization=organization,
    )

 

async def accept_invitation_by_id(
    db: AsyncSession,
    *,
    user: User,
    invitation_id: UUID,
) -> MyOrganizationResponse:
    """Accept an invitation the invitee found in their inbox."""
    invitation, organization = await _get_live_invitation_by_id(
        db,
        invitation_id=invitation_id,
    )
    if user.email.lower() != invitation.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address.",
        )
    return await _finalize_accept(
        db=db,
        user=user,
        invitation=invitation,
        organization=organization,
    )


async def decline_invitation_by_id(
    db: AsyncSession,
    *,
    user: User,
    invitation_id: UUID,
) -> None:
    """Decline an invitation the invitee found in their inbox."""
    invitation, organization = await _get_live_invitation_by_id(
        db,
        invitation_id=invitation_id,
    )
    if user.email.lower() != invitation.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address.",
        )
    await _finalize_decline(
        db=db,
        user=user,
        invitation=invitation,
        organization=organization,
    )


async def create_team(
    db: AsyncSession,
    *,
    context: OrgContext,
    payload: OrgTeamCreateRequest,
) -> OrgTeamResponse:
    """Create a new team in the organization."""
    org_id = context.org.id
    user_id = context.user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = OrgTeam(org_id=org_id, name=payload.name)
        db.add(team)
        try:
            await db.flush()
        except IntegrityError as exc:
            if "uq_org_teams_org_name" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A team with this name already exists.",
                ) from exc
            raise
        await write_audit(
            db=db,
            actor_id=user_id,
            action="org_team_created",
            target_type="organization",
            target_id=org_id,
            metadata={"team_id": str(team.id), "team_name": team.name},
        )
        return OrgTeamResponse(
            id=team.id,
            name=team.name,
            member_count=0,
            created_at=team.created_at,
        )


async def list_teams(
    db: AsyncSession,
    *,
    context: OrgContext,
) -> OrgTeamsResponse:
    """List teams in the organization."""
    org_id = context.org.id
    stmt = (
        select(
            OrgTeam.id,
            OrgTeam.name,
            OrgTeam.created_at,
            func.count(OrgTeamMember.member_id).label("member_count"),
        )
        .outerjoin(OrgTeamMember, OrgTeamMember.team_id == OrgTeam.id)
        .where(OrgTeam.org_id == org_id)
        .group_by(OrgTeam.id)
        .order_by(OrgTeam.name)
    )
    rows = (await db.execute(stmt)).all()
    cap_rows = (
        await db.execute(
            select(OrgTeamCapability.team_id, OrgTeamCapability.capability)
            .join(OrgTeam, OrgTeam.id == OrgTeamCapability.team_id)
            .where(OrgTeam.org_id == org_id)
        )
    ).all()
    caps_by_team: dict[UUID, list[str]] = {}
    for team_id_value, capability in cap_rows:
        caps_by_team.setdefault(team_id_value, []).append(capability)
    return OrgTeamsResponse(
        teams=[
            OrgTeamResponse(
                id=row.id,
                name=row.name,
                member_count=row.member_count,
                capabilities=sorted(caps_by_team.get(row.id, [])),
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


async def rename_team(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    payload: OrgTeamRenameRequest,
) -> OrgTeamResponse:
    """Rename a team in the organization."""
    org_id = context.org.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam)
            .where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
            .with_for_update()
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        team.name = payload.name
        try:
            await db.flush()
        except IntegrityError as exc:
            if "uq_org_teams_org_name" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A team with this name already exists.",
                ) from exc
            raise

        member_count = await db.scalar(
            select(func.count(OrgTeamMember.member_id)).where(
                OrgTeamMember.team_id == team_id
            )
        )
        capabilities = list(
            (
                await db.scalars(
                    select(OrgTeamCapability.capability).where(
                        OrgTeamCapability.team_id == team_id
                    )
                )
            ).all()
        )

        return OrgTeamResponse(
            id=team.id,
            name=team.name,
            member_count=member_count or 0,
            capabilities=sorted(capabilities),
            created_at=team.created_at,
        )


async def delete_team(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
) -> None:
    """Delete a team in the organization."""
    org_id = context.org.id
    user_id = context.user.id
    member_user_ids: list[UUID] = []
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        member_user_ids = list(
            (
                await db.scalars(
                    select(OrgMember.user_id)
                    .join(OrgTeamMember, OrgTeamMember.member_id == OrgMember.id)
                    .where(OrgTeamMember.team_id == team_id)
                )
            ).all()
        )
        team_name = team.name
        await db.delete(team)

        await write_audit(
            db=db,
            actor_id=user_id,
            action="org_team_deleted",
            target_type="organization",
            target_id=org_id,
            metadata={"team_id": str(team_id), "team_name": team_name},
        )

    for member_user_id in member_user_ids:
        await sync_derived_roles(db, user_id=member_user_id)


async def list_team_members(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
) -> OrgTeamMembersResponse:
    """List the organization members that belong to one team.

    Email is exposed only to owners and admins, matching ``list_members``.

    Args:
        db: Async database session.
        context: Resolved organization/member/user context from RBAC.
        team_id: Team whose roster to return.

    Returns:
        The team's members ordered by join time.

    Raises:
        HTTPException(404): If the team does not exist in this organization.
    """
    org_id = context.org.id
    team = await db.scalar(
        select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    include_email = context.member.role in {"owner", "admin"}
    rows = (
        await db.execute(
            select(OrgMember, User.display_name, User.email)
            .join(User, User.id == OrgMember.user_id)
            .join(OrgTeamMember, OrgTeamMember.member_id == OrgMember.id)
            .where(OrgTeamMember.team_id == team_id)
            .order_by(OrgMember.joined_at.asc(), OrgMember.id.asc())
        )
    ).all()
    return OrgTeamMembersResponse(
        members=[
            OrgMemberResponse(
                id=member.id,
                user_id=member.user_id,
                display_name=display_name,
                email=email if include_email else None,
                role=member.role,
                joined_at=member.joined_at,
            )
            for member, display_name, email in rows
        ]
    )


async def add_team_member(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    member_id: UUID,
) -> None:
    """Add a member to a team."""
    org_id = context.org.id
    added_user_id: UUID | None = None
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        member = await _get_member_row(db, org_id=org_id, member_id=member_id)
        added_user_id = member.user_id

        stmt = (
            pg_insert(OrgTeamMember)
            .values(team_id=team_id, member_id=member_id)
            .on_conflict_do_nothing()
        )
        await db.execute(stmt)

    assert added_user_id is not None
    await sync_derived_roles(db, user_id=added_user_id)


async def remove_team_member(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    member_id: UUID,
) -> None:
    """Remove a member from a team."""
    org_id = context.org.id
    removed_user_id: UUID | None = None
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        member_row = await db.scalar(
            select(OrgTeamMember).where(
                OrgTeamMember.team_id == team_id, OrgTeamMember.member_id == member_id
            )
        )
        if not member_row:
            raise HTTPException(status_code=404, detail="Member is not in this team.")

        target = await _get_member_row(db, org_id=org_id, member_id=member_id)
        removed_user_id = target.user_id
        await db.delete(member_row)

    assert removed_user_id is not None
    await sync_derived_roles(db, user_id=removed_user_id)


async def enable_team_capability(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    capability: str,
) -> None:
    """Enable one marketplace capability on a team.

    The org-level capability must already be active; team-scoped rights are a
    second eligibility layer, not a way to bypass org capability gating.
    """
    org_id = context.org.id
    actor_id = context.user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        active = await db.scalar(
            select(1)
            .select_from(OrgCapability)
            .where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == capability,
                OrgCapability.status == "active",
            )
            .limit(1)
        )
        if active is None:
            raise HTTPException(
                status_code=422,
                detail="Activate this capability for the organization first.",
            )

        await db.execute(
            pg_insert(OrgTeamCapability)
            .values(team_id=team_id, capability=capability)
            .on_conflict_do_nothing()
        )
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_team_capability_enabled",
            target_type="organization",
            target_id=org_id,
            metadata={"team_id": str(team_id), "capability": capability},
        )

    await _sync_team_member_roles(db, team_id)


async def disable_team_capability(
    db: AsyncSession,
    *,
    context: OrgContext,
    team_id: UUID,
    capability: str,
) -> None:
    """Disable one marketplace capability on a team."""
    org_id = context.org.id
    actor_id = context.user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        team = await db.scalar(
            select(OrgTeam).where(OrgTeam.id == team_id, OrgTeam.org_id == org_id)
        )
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")

        row = await db.scalar(
            select(OrgTeamCapability).where(
                OrgTeamCapability.team_id == team_id,
                OrgTeamCapability.capability == capability,
            )
        )
        if row is not None:
            await db.delete(row)
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="org_team_capability_disabled",
                target_type="organization",
                target_id=org_id,
                metadata={"team_id": str(team_id), "capability": capability},
            )

    await _sync_team_member_roles(db, team_id)


async def admin_list_orgs(
    db: AsyncSession,
    *,
    query: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> AdminOrgsResponse:
    """List/search organizations for platform administration."""
    filters = []
    if query:
        filters.append(
            or_(
                Organization.name.ilike(f"%{query}%"),
                Organization.slug.ilike(f"%{query}%"),
            )
        )

    stmt = select(Organization).where(*filters)
    total_stmt = select(func.count()).select_from(Organization).where(*filters)

    total = await db.scalar(total_stmt) or 0

    stmt = (
        stmt.order_by(Organization.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    orgs = (await db.execute(stmt)).scalars().all()

    if not orgs:
        return AdminOrgsResponse(orgs=[], total=total, page=page, page_size=page_size)

    org_ids = [org.id for org in orgs]

    member_counts_rows = (
        await db.execute(
            select(OrgMember.org_id, func.count())
            .where(OrgMember.org_id.in_(org_ids))
            .group_by(OrgMember.org_id)
        )
    ).all()
    member_counts = {org_id: count for org_id, count in member_counts_rows}

    capabilities_rows = (
        (
            await db.execute(
                select(OrgCapability).where(OrgCapability.org_id.in_(org_ids))
            )
        )
        .scalars()
        .all()
    )

    capabilities_by_org: dict[UUID, list[OrgCapability]] = {}
    for cap in capabilities_rows:
        capabilities_by_org.setdefault(cap.org_id, []).append(cap)

    results = []
    for org in orgs:
        caps = capabilities_by_org.get(org.id, [])
        cap_dict = {cap.capability: cap.status for cap in caps}
        results.append(
            AdminOrgResponse(
                id=org.id,
                slug=org.slug,
                name=org.name,
                country=org.country,
                member_count=member_counts.get(org.id, 0),
                capabilities=cap_dict,
                suspended_at=org.suspended_at,
                deactivated_at=org.deactivated_at,
                created_at=org.created_at,
            )
        )

    return AdminOrgsResponse(
        orgs=results,
        total=total,
        page=page,
        page_size=page_size,
    )


async def admin_suspend_org(
    db: AsyncSession,
    *,
    admin: User,
    org_id: UUID,
) -> None:
    """Suspend an organization platform-wide (idempotent)."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        org = await db.scalar(
            select(Organization).where(Organization.id == org_id).with_for_update()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")

        if org.suspended_at:
            return

        org.suspended_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_suspended",
            target_type="organization",
            target_id=org_id,
        )

        members = (
            (
                await db.execute(
                    select(OrgMember.user_id).where(OrgMember.org_id == org_id)
                )
            )
            .scalars()
            .all()
        )

    for user_id in members:
        await sync_derived_roles(db, user_id=user_id)


async def admin_reinstate_org(
    db: AsyncSession,
    *,
    admin: User,
    org_id: UUID,
) -> None:
    """Lift a platform-wide org suspension (idempotent)."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        org = await db.scalar(
            select(Organization).where(Organization.id == org_id).with_for_update()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")

        if not org.suspended_at:
            return

        org.suspended_at = None
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_reinstated",
            target_type="organization",
            target_id=org_id,
        )

        members = (
            (
                await db.execute(
                    select(OrgMember.user_id).where(OrgMember.org_id == org_id)
                )
            )
            .scalars()
            .all()
        )

    for user_id in members:
        await sync_derived_roles(db, user_id=user_id)


async def export_user_org_memberships(
    db: AsyncSession, *, user_id: UUID
) -> list[dict[str, object]]:
    """Return the user's org memberships for the GDPR export bundle."""
    rows = (
        await db.execute(
            select(
                Organization.slug,
                Organization.name,
                OrgMember.role,
                OrgMember.joined_at,
            )
            .join(OrgMember, OrgMember.org_id == Organization.id)
            .where(OrgMember.user_id == user_id)
        )
    ).all()
    return [
        {
            "org_slug": slug,
            "org_name": name,
            "role": role,
            "joined_at": joined_at.isoformat(),
        }
        for slug, name, role, joined_at in rows
    ]


async def user_deletion_org_blockers(
    db: AsyncSession, *, user_id: UUID
) -> list[AccountDeletionBlockedReason]:
    """Names of orgs blocking account deletion (sole owner + active capability)."""
    rows = (
        await db.execute(
            select(Organization.name)
            .join(OrgMember, OrgMember.org_id == Organization.id)
            .join(OrgCapability, OrgCapability.org_id == Organization.id)
            .where(
                OrgMember.user_id == user_id,
                OrgMember.role == "owner",
                OrgCapability.status == "active",
                Organization.deactivated_at.is_(None),
            )
            .distinct()
        )
    ).all()
    return [
        AccountDeletionBlockedReason(
            code="sole_owner",
            message=f"You are the sole owner of active organization: {name}",
            count=1,
        )
        for (name,) in rows
    ]
