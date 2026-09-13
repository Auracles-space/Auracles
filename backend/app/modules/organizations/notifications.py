"""Owner-facing organization notifications.

One place that turns an admin's decision about an organization (suspend,
reinstate, capability status, trial outcome) or a membership change into a
durable notification for the people it affects. Every helper is called after
the transaction that made the change has committed, so the worker reads
persisted state, and a queue failure is logged rather than raised so it can
never roll a decision back.

Maps to: docs/superpowers/specs/2026-09-13-org-onboarding-journey-design.md §1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import OrgMember
from app.workers.tasks.project_notifications import dispatch_project_notification

CAPABILITY_LABELS: dict[str, str] = {
    "attestor": "Attestor",
    "contributor": "Contributor",
    "operator": "Operator",
}


async def org_owner_ids(db: AsyncSession, org_id: UUID) -> list[UUID]:
    """Return the user ids of every owner of ``org_id``.

    Read inside the caller's transaction so the list reflects the membership
    at the moment of the decision.
    """
    rows = await db.execute(
        select(OrgMember.user_id).where(
            OrgMember.org_id == org_id,
            OrgMember.role == "owner",
        )
    )
    return list(rows.scalars().all())


def notify_users(
    user_ids: list[UUID],
    *,
    org_id: UUID,
    notification_type: str,
    title: str,
    body: str,
    link: str,
    dedupe_token: str | None = None,
    extra_payload: dict[str, str] | None = None,
) -> None:
    """Queue one preference-gated notification per user about an org event.

    ``dedupe_token`` defaults to the current timestamp so a repeated decision
    (suspend, lift, suspend again) reaches the owner each time while a
    Celery retry of the same dispatch stays idempotent.
    """
    token = dedupe_token or datetime.now(UTC).isoformat()
    payload = {"org_id": str(org_id), **(extra_payload or {})}
    for user_id in user_ids:
        try:
            dispatch_project_notification.delay(
                user_id=str(user_id),
                notification_type=notification_type,
                title=title,
                body=body,
                payload=payload,
                link=link,
                dedupe_key=f"{notification_type}:{org_id}:{user_id}:{token}",
            )
        except Exception as exc:  # pragma: no cover - defensive queue guard
            logger.bind(
                module="organizations",
                action="notify_org_users",
                org_id=str(org_id),
                user_id=str(user_id),
            ).error("notification_dispatch_failed", error=str(exc))


def notify_org_suspended(
    owner_ids: list[UUID], *, org_id: UUID, org_name: str, reason: str
) -> None:
    """Tell owners the platform suspended their organization and why."""
    notify_users(
        owner_ids,
        org_id=org_id,
        notification_type="org_suspended",
        title=f"{org_name} has been suspended",
        body=(
            f"An administrator suspended {org_name}. Reason: {reason} "
            "Members keep read access; every other action is paused until "
            "the suspension is lifted."
        ),
        link=f"/dashboard/organizations/{org_id}",
    )


def notify_org_reinstated(
    owner_ids: list[UUID], *, org_id: UUID, org_name: str
) -> None:
    """Tell owners the suspension was lifted."""
    notify_users(
        owner_ids,
        org_id=org_id,
        notification_type="org_reinstated",
        title=f"{org_name} has been reinstated",
        body=(
            f"The suspension on {org_name} was lifted. All actions are available again."
        ),
        link=f"/dashboard/organizations/{org_id}",
    )


def notify_capability_status(
    owner_ids: list[UUID],
    *,
    org_id: UUID,
    org_name: str,
    capability: str,
    status_value: str,
    reason: str | None,
) -> None:
    """Tell owners a capability was suspended, reinstated, or revoked.

    ``status_value`` is the new capability status (``suspended``, ``active``,
    ``revoked``); ``active`` means reinstated here because self-activation
    never routes through this helper.
    """
    label = CAPABILITY_LABELS.get(capability, capability.title())
    link = f"/dashboard/organizations/{org_id}"
    if capability == "attestor":
        link = f"{link}/attestor"
    if status_value == "active":
        notify_users(
            owner_ids,
            org_id=org_id,
            notification_type="org_capability_reinstated",
            title=f"{label} capability reinstated for {org_name}",
            body=f"The {label} capability on {org_name} is active again.",
            link=link,
            extra_payload={"capability": capability},
        )
        return
    verb = "revoked" if status_value == "revoked" else "suspended"
    consequence = (
        "It cannot be reactivated; contact support if you believe this is wrong."
        if status_value == "revoked"
        else "It stays paused until an administrator reinstates it."
    )
    notify_users(
        owner_ids,
        org_id=org_id,
        notification_type=f"org_capability_{verb}",
        title=f"{label} capability {verb} for {org_name}",
        body=(
            f"An administrator {verb} the {label} capability on {org_name}. "
            f"Reason: {reason or 'No reason given.'} {consequence}"
        ),
        link=link,
        extra_payload={"capability": capability},
    )


def notify_member_removed(user_id: UUID, *, org_id: UUID, org_name: str) -> None:
    """Tell a member an owner or admin removed them from the organization."""
    notify_users(
        [user_id],
        org_id=org_id,
        notification_type="org_member_removed",
        title=f"You were removed from {org_name}",
        body=(
            f"An administrator of {org_name} removed you. You no longer have "
            "access to its workspaces, queues, or libraries."
        ),
        link="/dashboard/organizations",
    )


def notify_member_role_changed(
    user_id: UUID, *, org_id: UUID, org_name: str, new_role: str
) -> None:
    """Tell a member their organization role changed."""
    notify_users(
        [user_id],
        org_id=org_id,
        notification_type="org_member_role_changed",
        title=f"Your role at {org_name} is now {new_role}",
        body=f"An owner of {org_name} changed your role to {new_role}.",
        link=f"/dashboard/organizations/{org_id}",
        extra_payload={"role": new_role},
    )


def notify_ownership_transferred(user_id: UUID, *, org_id: UUID, org_name: str) -> None:
    """Tell the incoming owner the organization is now theirs."""
    notify_users(
        [user_id],
        org_id=org_id,
        notification_type="org_ownership_transferred",
        title=f"You now own {org_name}",
        body=(
            f"Ownership of {org_name} was transferred to you. You can manage "
            "members, capabilities, billing, and the danger zone."
        ),
        link=f"/dashboard/organizations/{org_id}",
    )


def notify_trial_decided(
    *,
    nominee_user_id: UUID | None,
    owner_ids: list[UUID],
    org_id: UUID,
    org_name: str,
    passed: bool,
    feedback: str | None,
) -> None:
    """Tell the nominee and the owners how the calibration trial was decided.

    A nominee who is also an owner gets the nominee version only, so nobody
    receives the same verdict twice.
    """
    outcome = "passed" if passed else "did not pass"
    detail = f" Feedback: {feedback}" if feedback else ""
    if nominee_user_id is not None:
        notify_users(
            [nominee_user_id],
            org_id=org_id,
            notification_type="org_attestor_trial_decided",
            title=f"Your calibration trial {outcome}",
            body=(
                f"An administrator reviewed your calibration trial for {org_name}."
                f"{detail}"
            ),
            link=f"/dashboard/organizations/{org_id}/attestor-trial",
            extra_payload={"result": "pass" if passed else "fail"},
        )
    remaining = [owner for owner in owner_ids if owner != nominee_user_id]
    notify_users(
        remaining,
        org_id=org_id,
        notification_type="org_attestor_trial_decided",
        title=f"{org_name}'s calibration trial {outcome}",
        body=(
            f"The trial attestation for {org_name}'s attestor application "
            f"{outcome}.{detail}"
        ),
        link=f"/dashboard/organizations/{org_id}/attestor",
        extra_payload={"result": "pass" if passed else "fail"},
    )
