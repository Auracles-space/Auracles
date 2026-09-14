"""Organization slug changes and public slug resolution.

Decision 5 of the organizations end-to-end design (docs/superpowers/specs/
2026-09-14-organizations-end-to-end-design.md §Slug change): owners may change
their organization's slug. Every previous slug is written to
``org_slug_history`` and stays reserved to the organization, so ``/orgs/{old}``
resolves to the current profile and no other organization can claim an old
slug to impersonate this one.

The HTTP route (owner role + step-up) and the public profile wiring call the
functions here; the owner check inside ``change_org_slug`` is defence in depth.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.organizations import notifications as org_notifications
from app.modules.organizations.models import Organization, OrgMember, OrgSlugHistory

SLUG_TAKEN_DETAIL = "That slug is taken."

# Namespace for slug advisory locks so they cannot share a key with the other
# advisory lock families in the codebase (e.g. ``payout:{contributor_id}``).
SLUG_LOCK_NAMESPACE = "org_slug:"


async def lock_slug(db: AsyncSession, slug: str) -> None:
    """Serialize every claim on one slug for the rest of the transaction.

    A slug can be claimed two ways: as a new organization's slug or as an
    existing organization's new slug. Both check ``organizations`` and
    ``org_slug_history`` before writing, and no cross-table constraint links
    the two tables, so without this lock a same-instant creation and change
    could each pass their check and claim one slug (Decision 5). The lock is
    transaction-scoped and released on commit or rollback.

    Args:
        db: Async session with an open transaction.
        slug: Slug being claimed; normalized here so variants share one key.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"{SLUG_LOCK_NAMESPACE}{slug.strip().lower()}"},
    )


def notify_org_slug_changed(
    owner_ids: list[UUID],
    *,
    actor_user_id: UUID,
    org_id: UUID,
    old_slug: str,
    new_slug: str,
) -> None:
    """Tell every owner except the actor that the public address moved.

    Called after commit. The acting owner is skipped: a notification about
    one's own change is noise.
    """
    recipients = [owner_id for owner_id in owner_ids if owner_id != actor_user_id]
    if not recipients:
        return
    org_notifications.notify_users(
        recipients,
        org_id=org_id,
        notification_type="org_slug_changed",
        title="Public profile address changed",
        body=(
            f"The organization's public profile is now at /orgs/{new_slug}. "
            f"Links to /orgs/{old_slug} now redirect there."
        ),
        link=f"/dashboard/organizations/{org_id}",
        extra_payload={"from": old_slug, "to": new_slug},
    )


async def change_org_slug(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_user_id: UUID,
    new_slug: str,
) -> Organization:
    """Change an organization's slug, reserving the old one to the org.

    Runs in one transaction with the organization row locked ``FOR UPDATE``:
    the old slug is written to history, the new slug set, and an
    ``org_slug_changed`` audit row recorded with ``{from, to}``. A slug from
    the org's own history may be reclaimed; its history row is removed.
    Other owners are notified after commit.

    Args:
        db: Async database session (any open transaction is rolled back).
        org_id: Organization whose slug changes.
        actor_user_id: Requesting user; must be an owner of the org.
        new_slug: Already-normalized slug (see ``OrgSlugChangeRequest``).

    Returns:
        The refreshed Organization carrying the new slug.

    Raises:
        HTTPException(404): Unknown or deactivated organization.
        HTTPException(403): The actor is not an owner of the organization.
        HTTPException(409): Organization suspended, or the slug belongs to
            another organization now or in its history (including a race).
        HTTPException(422): The slug is already the organization's slug.
    """
    log = logger.bind(
        module="organizations",
        action="change_org_slug",
        user_id=str(actor_user_id),
        org_id=str(org_id),
    )
    if db.in_transaction():
        await db.rollback()

    owner_ids: list[UUID] = []
    try:
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
                    detail="Only an owner can change the organization's slug.",
                )
            if organization.suspended_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A suspended organization cannot change its slug.",
                )

            old_slug = organization.slug
            if new_slug == old_slug:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="That is already this organization's slug.",
                )

            # Taken after the org row lock and before the check, so a
            # concurrent claim on the same slug commits before we read.
            await lock_slug(db, new_slug)
            current_holder = await db.scalar(
                select(Organization.id).where(Organization.slug == new_slug)
            )
            history_holder = await db.scalar(
                select(OrgSlugHistory.org_id).where(OrgSlugHistory.slug == new_slug)
            )
            if current_holder is not None or (
                history_holder is not None and history_holder != org_id
            ):
                log.info("slug_change_refused_taken")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=SLUG_TAKEN_DETAIL
                )

            if history_holder == org_id:
                # Reclaiming an own old slug: free the row before it becomes
                # current, otherwise it would be both current and historical.
                await db.execute(
                    delete(OrgSlugHistory).where(
                        OrgSlugHistory.org_id == org_id,
                        OrgSlugHistory.slug == new_slug,
                    )
                )

            db.add(OrgSlugHistory(org_id=org_id, slug=old_slug))
            organization.slug = new_slug
            await db.flush()
            await write_audit(
                db=db,
                actor_id=actor_user_id,
                action="org_slug_changed",
                target_type="organization",
                target_id=org_id,
                metadata={"from": old_slug, "to": new_slug},
            )
            owner_ids = await org_notifications.org_owner_ids(db, org_id)
    except IntegrityError as exc:
        # A concurrent change or creation claimed the slug between the check
        # and the write; the unique constraints are the final arbiter.
        log.warning("slug_change_conflict_race", error=str(exc.orig))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=SLUG_TAKEN_DETAIL
        ) from exc

    await db.refresh(organization)
    log.info("org_slug_changed", from_slug=old_slug, to_slug=new_slug)
    notify_org_slug_changed(
        owner_ids,
        actor_user_id=actor_user_id,
        org_id=org_id,
        old_slug=old_slug,
        new_slug=new_slug,
    )
    return organization


async def resolve_public_slug(
    db: AsyncSession, slug: str
) -> tuple[Organization, str] | None:
    """Resolve a current or historical slug to an active organization.

    Args:
        db: Async database session.
        slug: Slug from the public URL (current or previously used).

    Returns:
        ``(organization, canonical_slug)`` when the slug belongs, now or in
        history, to an organization that is neither deactivated nor
        suspended; ``None`` otherwise. Callers redirect when
        ``canonical_slug`` differs from ``slug``.
    """
    organization = await db.scalar(
        select(Organization).where(Organization.slug == slug)
    )
    if organization is None:
        organization = await db.scalar(
            select(Organization)
            .join(OrgSlugHistory, OrgSlugHistory.org_id == Organization.id)
            .where(OrgSlugHistory.slug == slug)
        )
    if (
        organization is None
        or organization.deactivated_at is not None
        or organization.suspended_at is not None
    ):
        return None
    return organization, organization.slug
