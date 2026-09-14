"""Owner-facing organization notifications.

One place that turns an admin's decision about an organization (suspend,
reinstate, capability status, trial outcome) or a membership change into a
durable notification for the people it affects. Every helper is called after
the transaction that made the change has committed, so the worker reads
persisted state, and a queue failure is logged rather than raised so it can
never roll a decision back.

Slice C adds the money senders (payouts, purchases, invoices, shared-library
grants, org Framework moderation). Amounts are always rendered in their own
currency — Naira is the primary rail — never an assumed dollar sign.

Maps to: docs/superpowers/specs/2026-09-13-org-onboarding-journey-design.md §1
and docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slice B and §Slice C.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import Organization, OrgMember
from app.shared.models.audit_log import AuditLog
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


def notify_member_removed(
    user_id: UUID,
    *,
    org_id: UUID,
    org_name: str,
    revoked_grant_count: int = 0,
) -> None:
    """Tell a member an owner or admin removed them from the organization.

    When the removal also revoked shared-library grants, say so explicitly so
    the member knows why Frameworks they could open yesterday are gone.
    """
    body = (
        f"An administrator of {org_name} removed you. You no longer have "
        "access to its workspaces, queues, or libraries."
    )
    if revoked_grant_count > 0:
        noun = "Framework" if revoked_grant_count == 1 else "Frameworks"
        body += (
            f" Your shared library access to {revoked_grant_count} {noun} "
            "ended with your membership."
        )
    notify_users(
        [user_id],
        org_id=org_id,
        notification_type="org_member_removed",
        title=f"You were removed from {org_name}",
        body=body,
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


def notify_org_created(user_id: UUID, *, org_id: UUID, org_name: str) -> None:
    """Acknowledge a new organization to the member who created it."""
    notify_users(
        [user_id],
        org_id=org_id,
        notification_type="org_created",
        title=f"{org_name} is ready",
        body=(
            f"You created {org_name}. Invite your team, complete business "
            "verification, and activate the capabilities you need."
        ),
        link=f"/dashboard/organizations/{org_id}",
    )


def notify_org_profile_updated(
    owner_ids: list[UUID],
    *,
    org_id: UUID,
    org_name: str,
    actor_name: str,
    changed_fields: list[str],
) -> None:
    """Tell the other owners which profile fields changed, never the values.

    The acting owner is excluded by the caller; a notification about one's
    own edit is noise.
    """
    fields = ", ".join(changed_fields)
    notify_users(
        owner_ids,
        org_id=org_id,
        notification_type="org_profile_updated",
        title=f"{org_name}'s profile was updated",
        body=f"{actor_name} changed the organization's {fields}.",
        link=f"/dashboard/organizations/{org_id}",
        extra_payload={"fields": fields},
    )


def notify_org_deactivated(
    member_ids: list[UUID],
    *,
    org_id: UUID,
    org_name: str,
    closed_by_name: str,
    reason: str | None,
) -> None:
    """Tell every member the organization is closed and hidden, data retained."""
    reason_clause = f" Reason: {reason}" if reason else ""
    notify_users(
        member_ids,
        org_id=org_id,
        notification_type="org_deactivated",
        title=f"{org_name} has been closed",
        body=(
            f"{closed_by_name} closed {org_name}. It is now hidden from the "
            "marketplace and your dashboard; its data is retained and an "
            f"administrator can reopen it.{reason_clause} Contact "
            f"{closed_by_name} or support if you have questions."
        ),
        link="/dashboard/organizations",
    )


def notify_org_reactivated(
    owner_ids: list[UUID], *, org_id: UUID, org_name: str
) -> None:
    """Tell owners an administrator reopened the organization."""
    notify_users(
        owner_ids,
        org_id=org_id,
        notification_type="org_reactivated",
        title=f"{org_name} has been reopened",
        body=(
            f"An administrator reactivated {org_name}. It is visible again and "
            "every member has their access back."
        ),
        link=f"/dashboard/organizations/{org_id}",
    )


def notify_org_kyb_submitted(user_id: UUID, *, org_id: UUID, org_name: str) -> None:
    """Acknowledge a business-verification submission to the submitter."""
    notify_users(
        [user_id],
        org_id=org_id,
        notification_type="org_kyb_submitted",
        title=f"{org_name}'s verification is in review",
        body=(
            f"The business details for {org_name} are in review. We will "
            "notify you as soon as an administrator reaches a decision."
        ),
        link=f"/dashboard/organizations/{org_id}/verification",
    )


def notify_invitation_revoked(user_id: UUID, *, org_id: UUID, org_name: str) -> None:
    """Tell an invitee with an account that the invitation was withdrawn."""
    notify_users(
        [user_id],
        org_id=org_id,
        notification_type="org_invitation_revoked",
        title=f"Your invitation to {org_name} was withdrawn",
        body=(
            f"An administrator of {org_name} withdrew your invitation. "
            "Ask them for a new one if you still expect to join."
        ),
        link="/settings/organizations",
    )


def notify_invitation_expired(user_id: UUID, *, org_id: UUID, org_name: str) -> None:
    """Tell an invitee with an account that the invitation lapsed."""
    notify_users(
        [user_id],
        org_id=org_id,
        notification_type="org_invitation_expired",
        title=f"Your invitation to {org_name} expired",
        body=(
            f"The invitation to join {org_name} expired before it was "
            "accepted. Ask an administrator of the organization to send a "
            "new one."
        ),
        link="/settings/organizations",
    )


# ---------------------------------------------------------------------------
# Slice C — org money
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS: dict[str, str] = {"NGN": "₦", "USD": "$", "GBP": "£", "EUR": "€"}


def format_money(amount: Decimal, currency: str) -> str:
    """Render an amount with its own currency symbol and thousands grouping.

    Unknown currency codes stay explicit (``KES 7.00``) rather than borrowing a
    symbol that would misstate what the owner is being paid in.
    """
    code = currency.upper()
    quantized = Decimal(amount).quantize(Decimal("0.01"))
    grouped = f"{quantized:,.2f}"
    symbol = _CURRENCY_SYMBOLS.get(code)
    return f"{symbol}{grouped}" if symbol else f"{code} {grouped}"


def _with_extra(owner_ids: list[UUID], extra_id: UUID | None) -> list[UUID]:
    """Return owners plus one extra recipient, keeping order and dropping repeats."""
    recipients = list(dict.fromkeys(owner_ids))
    if extra_id is not None and extra_id not in recipients:
        recipients.append(extra_id)
    return recipients


def _financials_link(org_id: UUID) -> str:
    """Return the org financials tab path."""
    return f"/dashboard/organizations/{org_id}/financials"


def _library_link(org_id: UUID) -> str:
    """Return the org shared-library path."""
    return f"/dashboard/organizations/{org_id}/operator/library"


async def org_name(db: AsyncSession, org_id: UUID) -> str:
    """Return the organization's display name, or a neutral fallback."""
    name = await db.scalar(select(Organization.name).where(Organization.id == org_id))
    return name or "Your organization"


async def audit_actor_id(
    db: AsyncSession, *, action: str, target_type: str, target_id: UUID
) -> UUID | None:
    """Return the user who performed the earliest audited ``action`` on a target.

    Used to recover who requested a payout or started a purchase, which the
    money rows themselves do not record.
    """
    return await db.scalar(
        select(AuditLog.actor_id)
        .where(
            AuditLog.action == action,
            AuditLog.target_type == target_type,
            AuditLog.target_id == target_id,
            AuditLog.actor_id.is_not(None),
        )
        .order_by(AuditLog.created_at.asc())
        .limit(1)
    )


def notify_org_payout_requested(
    owner_ids: list[UUID],
    *,
    org_id: UUID,
    org_name: str,
    payout_id: UUID,
    amount: Decimal,
    currency: str,
) -> None:
    """Tell owners a payout of the org balance was requested."""
    notify_users(
        owner_ids,
        org_id=org_id,
        notification_type="org_payout_requested",
        title=f"Payout requested for {org_name}",
        body=(
            f"A payout of {format_money(amount, currency)} was requested from "
            f"{org_name}'s available balance. We will let you know when it lands."
        ),
        link=_financials_link(org_id),
        dedupe_token=str(payout_id),
        extra_payload={"payout_id": str(payout_id)},
    )


def notify_org_payout_completed(
    owner_ids: list[UUID],
    *,
    requester_id: UUID | None,
    org_id: UUID,
    org_name: str,
    payout_id: UUID,
    amount: Decimal,
    currency: str,
) -> None:
    """Tell owners and the requester that an org payout reached the bank."""
    notify_users(
        _with_extra(owner_ids, requester_id),
        org_id=org_id,
        notification_type="org_payout_completed",
        title=f"{org_name}'s payout was paid",
        body=(
            f"The payout of {format_money(amount, currency)} from {org_name} "
            "has been sent to the organization's payout account."
        ),
        link=_financials_link(org_id),
        dedupe_token=str(payout_id),
        extra_payload={"payout_id": str(payout_id)},
    )


def notify_org_payout_failed(
    owner_ids: list[UUID],
    *,
    requester_id: UUID | None,
    org_id: UUID,
    org_name: str,
    payout_id: UUID,
    amount: Decimal,
    currency: str,
    failure_reason: str | None,
) -> None:
    """Tell owners and the requester an org payout failed, with the cause if known."""
    reason_clause = f" Reason: {failure_reason}" if failure_reason else ""
    notify_users(
        _with_extra(owner_ids, requester_id),
        org_id=org_id,
        notification_type="org_payout_failed",
        title=f"{org_name}'s payout failed",
        body=(
            f"The payout of {format_money(amount, currency)} from {org_name} "
            f"could not be completed.{reason_clause} Check the payout account "
            "and contact support if it persists."
        ),
        link=_financials_link(org_id),
        dedupe_token=str(payout_id),
        extra_payload={"payout_id": str(payout_id)},
    )


def notify_org_purchase_completed(
    owner_ids: list[UUID],
    *,
    initiator_id: UUID | None,
    org_id: UUID,
    org_name: str,
    transaction_id: UUID,
    framework_title: str,
    amount: Decimal,
    currency: str,
) -> None:
    """Tell owners and the buyer the org License for a Framework is ready."""
    notify_users(
        _with_extra(owner_ids, initiator_id),
        org_id=org_id,
        notification_type="org_purchase_completed",
        title=f"{framework_title} is in {org_name}'s library",
        body=(
            f"{org_name} paid {format_money(amount, currency)} for "
            f"{framework_title}. Grant it to members from the shared library."
        ),
        link=_library_link(org_id),
        dedupe_token=str(transaction_id),
        extra_payload={"transaction_id": str(transaction_id)},
    )


def notify_org_purchase_failed(
    owner_ids: list[UUID],
    *,
    initiator_id: UUID | None,
    org_id: UUID,
    org_name: str,
    transaction_id: UUID,
    framework_title: str,
    amount: Decimal,
    currency: str,
    failure_reason: str | None,
) -> None:
    """Tell owners and the buyer an org purchase did not go through."""
    reason_clause = f" Reason: {failure_reason}" if failure_reason else ""
    notify_users(
        _with_extra(owner_ids, initiator_id),
        org_id=org_id,
        notification_type="org_purchase_failed",
        title=f"{org_name}'s purchase of {framework_title} failed",
        body=(
            f"The payment of {format_money(amount, currency)} for "
            f"{framework_title} did not complete.{reason_clause} No License "
            "was granted."
        ),
        link=_financials_link(org_id),
        dedupe_token=str(transaction_id),
        extra_payload={"transaction_id": str(transaction_id)},
    )


def notify_org_invoice_ready(
    owner_ids: list[UUID],
    *,
    org_id: UUID,
    org_name: str,
    transaction_id: UUID,
    framework_title: str,
) -> None:
    """Tell owners the purchase invoice PDF can be downloaded."""
    notify_users(
        owner_ids,
        org_id=org_id,
        notification_type="org_invoice_ready",
        title=f"Invoice ready for {org_name}",
        body=(
            f"The invoice for {org_name}'s purchase of {framework_title} is "
            "ready to download from billing."
        ),
        link=_financials_link(org_id),
        dedupe_token=str(transaction_id),
        extra_payload={"transaction_id": str(transaction_id)},
    )


def notify_org_license_granted(
    grantee_user_ids: list[UUID],
    *,
    actor_id: UUID | None,
    org_id: UUID,
    org_name: str,
    license_id: UUID,
    framework_title: str,
) -> None:
    """Tell grantees they can open a Framework from the org library.

    The acting member is skipped: granting to oneself is not news.
    """
    recipients = [
        user_id for user_id in dict.fromkeys(grantee_user_ids) if user_id != actor_id
    ]
    notify_users(
        recipients,
        org_id=org_id,
        notification_type="org_license_granted",
        title=f"You can now open {framework_title}",
        body=(
            f"{org_name} gave you access to {framework_title} in its shared library."
        ),
        link=_library_link(org_id),
        extra_payload={"license_id": str(license_id)},
    )


def notify_org_license_revoked(
    grantee_user_ids: list[UUID],
    *,
    actor_id: UUID | None,
    org_id: UUID,
    org_name: str,
    license_id: UUID,
    framework_title: str,
) -> None:
    """Tell former grantees their access to a Framework ended; skip the actor."""
    recipients = [
        user_id for user_id in dict.fromkeys(grantee_user_ids) if user_id != actor_id
    ]
    notify_users(
        recipients,
        org_id=org_id,
        notification_type="org_license_revoked",
        title=f"Your access to {framework_title} ended",
        body=(f"{org_name} removed your shared library access to {framework_title}."),
        link=_library_link(org_id),
        extra_payload={"license_id": str(license_id)},
    )


def notify_org_framework_suspended(
    owner_ids: list[UUID],
    *,
    org_id: UUID,
    org_name: str,
    framework_id: UUID,
    framework_title: str,
    reason: str | None,
) -> None:
    """Tell owners an administrator pulled one of the org's Frameworks."""
    reason_clause = f" Reason: {reason}" if reason else ""
    notify_users(
        owner_ids,
        org_id=org_id,
        notification_type="org_framework_suspended",
        title=f"{framework_title} was suspended",
        body=(
            f"An administrator removed {org_name}'s {framework_title} from the "
            f"marketplace.{reason_clause} Existing licensees keep access."
        ),
        link=f"/dashboard/organizations/{org_id}/frameworks/{framework_id}",
        extra_payload={"framework_id": str(framework_id)},
    )


def notify_org_framework_published(
    owner_ids: list[UUID],
    *,
    actor_id: UUID | None,
    org_id: UUID,
    org_name: str,
    framework_id: UUID,
    framework_title: str,
) -> None:
    """Tell the other owners an org Framework went live."""
    recipients = [owner for owner in owner_ids if owner != actor_id]
    notify_users(
        recipients,
        org_id=org_id,
        notification_type="org_framework_published",
        title=f"{framework_title} is live",
        body=f"{framework_title} is now published in the marketplace for {org_name}.",
        link=f"/dashboard/organizations/{org_id}/frameworks/{framework_id}",
        extra_payload={"framework_id": str(framework_id)},
    )
