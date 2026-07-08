"""Org contributor capability service.

Handles self-activation and platform-admin status changes for the organization
Contributor capability. RBAC lives in router dependencies; this layer assumes
the caller is already authorized for the requested action.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgContributorProfile,
    OrgMember,
)


async def _sync_org_member_roles(db: AsyncSession, org_id: UUID) -> None:
    """Re-evaluate derived roles for every member of one organization."""
    from app.modules.organizations import service as org_service

    member_ids = (
        await db.scalars(select(OrgMember.user_id).where(OrgMember.org_id == org_id))
    ).all()
    for user_id in member_ids:
        await org_service.sync_derived_roles(db, user_id=user_id)


async def contributor_capability_active(db: AsyncSession, *, org_id: UUID) -> bool:
    """Return whether the org Contributor capability is currently active."""
    capability_id = await db.scalar(
        select(OrgCapability.id)
        .where(
            OrgCapability.org_id == org_id,
            OrgCapability.capability == "contributor",
            OrgCapability.status == "active",
        )
        .limit(1)
    )
    return capability_id is not None


async def activate_contributor_capability(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
) -> OrgCapability:
    """Self-activate the org Contributor capability and seed its profile."""
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    async with db.begin():
        organization = await db.scalar(
            select(Organization).where(Organization.id == org_id).with_for_update()
        )
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found.",
            )
        if (
            organization.suspended_at is not None
            or organization.deactivated_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Organization is not eligible to activate contributor "
                    "capability."
                ),
            )

        capability = await db.scalar(
            select(OrgCapability)
            .where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == "contributor",
            )
            .with_for_update()
        )
        if capability is None:
            capability = OrgCapability(
                org_id=org_id,
                capability="contributor",
                status="active",
                activated_at=now,
            )
            db.add(capability)
        elif capability.status != "active":
            capability.status = "active"
            capability.activated_at = now

        profile = await db.scalar(
            select(OrgContributorProfile)
            .where(OrgContributorProfile.org_id == org_id)
            .with_for_update()
        )
        if profile is None:
            profile = OrgContributorProfile(
                org_id=org_id,
                active=True,
                activated_at=now,
            )
            db.add(profile)
        else:
            profile.active = True
            if profile.activated_at is None:
                profile.activated_at = now

        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_contributor_activated",
            target_type="organization",
            target_id=org_id,
            metadata={"status": capability.status},
        )

    await _sync_org_member_roles(db, org_id)
    assert capability is not None
    await db.refresh(capability)
    logger.bind(
        module="organizations",
        action="org_contributor_activated",
        user_id=str(actor_id),
        org_id=str(org_id),
    ).info("org_contributor_capability_activated")
    return capability


async def admin_set_contributor_capability_status(
    db: AsyncSession,
    *,
    org_id: UUID,
    admin_id: UUID,
    status_value: Literal["suspended", "active", "revoked"],
) -> None:
    """Set platform-admin status for the org Contributor capability."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        capability = await db.scalar(
            select(OrgCapability)
            .where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == "contributor",
            )
            .with_for_update()
        )
        if capability is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Org contributor capability not found.",
            )
        capability.status = status_value

        profile = await db.scalar(
            select(OrgContributorProfile)
            .where(OrgContributorProfile.org_id == org_id)
            .with_for_update()
        )
        if profile is not None:
            if status_value == "revoked":
                profile.active = False
            elif status_value == "active":
                profile.active = True

        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_contributor_capability_status_changed",
            target_type="organization",
            target_id=org_id,
            metadata={"status": status_value},
        )

    await _sync_org_member_roles(db, org_id)
    logger.bind(
        module="organizations",
        action="org_contributor_capability_status_changed",
        user_id=str(admin_id),
        org_id=str(org_id),
    ).info("org_contributor_capability_status_changed")
