"""Organization country changes.

The country picks an organization's payout rail (Paystack for NG, Stripe
elsewhere) and gives its registration number meaning, so it is fixed once
anything depends on it. Owners may correct it only while business
verification is neither pending nor verified and no payout account exists.
A rejected verification unlocks it: a wrong country is a likely reason for
the rejection.

The HTTP route (owner role + step-up) calls ``change_org_country``; the owner
check inside is defence in depth.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.financials.models import PayoutAccount
from app.modules.organizations import notifications as org_notifications
from app.modules.organizations.models import Organization, OrgLegalProfile, OrgMember
from app.shared.errors import error_detail

# Verification states whose review is bound to the current country.
COUNTRY_LOCKING_KYB_STATUSES = frozenset({"pending", "verified"})


async def country_change_blocker(db: AsyncSession, org_id: UUID) -> str | None:
    """Return why the organization's country is locked, or ``None``.

    Args:
        db: Async database session.
        org_id: Organization to check.

    Returns:
        A user-facing sentence when verification is pending or verified or a
        payout account exists; ``None`` when the country may change.
    """
    kyb_status = await db.scalar(
        select(OrgLegalProfile.kyb_status).where(OrgLegalProfile.org_id == org_id)
    )
    if kyb_status in COUNTRY_LOCKING_KYB_STATUSES:
        return (
            "The country can't change once business verification is submitted "
            "or approved."
        )
    payout_account = await db.scalar(
        select(PayoutAccount.id).where(PayoutAccount.org_id == org_id).limit(1)
    )
    if payout_account is not None:
        return "The country can't change once a payout account is connected."
    return None


async def change_org_country(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_user_id: UUID,
    actor_name: str,
    new_country: str,
) -> Organization:
    """Change an organization's country while nothing depends on it.

    Runs in one transaction with the organization row locked ``FOR UPDATE``
    so a concurrent verification submit or payout onboarding serializes
    behind it. Writes an ``org_country_changed`` audit row with
    ``{from, to}`` and tells the other owners after commit.

    Args:
        db: Async database session (any open transaction is rolled back).
        org_id: Organization whose country changes.
        actor_user_id: Requesting user; must be an owner of the org.
        actor_name: Display name used in the other owners' notice.
        new_country: Uppercase ISO 3166-1 alpha-2 code.

    Returns:
        The refreshed Organization carrying the new country.

    Raises:
        HTTPException(404): Unknown or deactivated organization.
        HTTPException(403): The actor is not an owner of the organization.
        HTTPException(409): Organization suspended, or the country is locked.
        HTTPException(422): The code is already the organization's country.
    """
    log = logger.bind(
        module="organizations",
        action="change_org_country",
        user_id=str(actor_user_id),
        org_id=str(org_id),
    )
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        organization = await db.scalar(
            select(Organization).where(Organization.id == org_id).with_for_update()
        )
        if organization is None or organization.deactivated_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        actor_role = await db.scalar(
            select(OrgMember.role).where(
                OrgMember.org_id == org_id, OrgMember.user_id == actor_user_id
            )
        )
        if actor_role != "owner":
            log.warning("access_denied", role=actor_role)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an owner can change the organization's country.",
            )
        if organization.suspended_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A suspended organization cannot change its country.",
            )

        old_country = organization.country
        if new_country == old_country:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="That is already this organization's country.",
            )

        blocker = await country_change_blocker(db, org_id)
        if blocker is not None:
            log.info("country_change_refused_locked")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail("org_country_locked", blocker),
            )

        organization.country = new_country
        org_name = organization.name
        await write_audit(
            db=db,
            actor_id=actor_user_id,
            action="org_country_changed",
            target_type="organization",
            target_id=org_id,
            metadata={"from": old_country, "to": new_country},
        )
        other_owner_ids = [
            owner_id
            for owner_id in await org_notifications.org_owner_ids(db, org_id)
            if owner_id != actor_user_id
        ]

    await db.refresh(organization)
    log.info("org_country_changed", from_country=old_country, to_country=new_country)
    if other_owner_ids:
        org_notifications.notify_org_profile_updated(
            other_owner_ids,
            org_id=org_id,
            org_name=org_name,
            actor_name=actor_name,
            changed_fields=["country"],
        )
    return organization
