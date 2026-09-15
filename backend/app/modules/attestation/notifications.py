"""Attestation notification and deferred reputation-event helpers.

The current reputation module has no persistent scoring ledger yet, so this
slice emits outcome breadcrumbs through audit logs and durable user
notifications. Phase 5 can consume the same event names when scoring exists.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from loguru import logger

from app.modules.admin.notifications import notify_admins_review_pending
from app.modules.attestation.models import Attestation, AttestationOffer
from app.workers.tasks.project_notifications import dispatch_project_notification


def _attestation_link(attestation_id: UUID) -> str:
    """Return the dashboard route for an Attestation detail page."""
    return f"/attestations/{attestation_id}"


def _attestor_onboarding_link() -> str:
    """Return the dashboard route for Attestor onboarding prerequisites."""
    return "/attestor/onboarding"


def _workspace_link(org_id: UUID, attestation_id: UUID) -> str:
    """Return the attestor org's review workspace for one attestation."""
    return f"/dashboard/organizations/{org_id}/attestations/{attestation_id}"


def _offers_link(org_id: UUID) -> str:
    """Return the attestor org's offers tab."""
    return f"/dashboard/organizations/{org_id}/offers"


def _org_side_link(attestation: Attestation) -> str:
    """Return the page an attestor-side recipient should land on.

    The workspace when the attestation is staffed to an org; the requestor
    detail page is never the right landing for an attestor, but it is the only
    page that exists when no org is attached (revoked assignments).
    """
    if attestation.attestor_org_id is not None:
        return _workspace_link(attestation.attestor_org_id, attestation.id)
    return _attestation_link(attestation.id)


def _due_date(value: datetime | None) -> str:
    """Format a deadline for notification copy, e.g. ``2 Oct 2026``."""
    if value is None:
        return "the new deadline"
    return value.strftime("%-d %b %Y")


def _payload(attestation: Attestation, **extra: str | int | None) -> dict[str, str]:
    """Build the common notification payload for Attestation events."""
    payload = {
        "attestation_id": str(attestation.id),
        "target_type": attestation.target_type,
        "target_id": str(attestation.target_id),
        "status": attestation.status,
    }
    if attestation.outcome is not None:
        payload["outcome"] = attestation.outcome
    for key, value in extra.items():
        if value is not None:
            payload[key] = str(value)
    return payload


def _dispatch(
    *,
    user_id: UUID,
    notification_type: str,
    title: str,
    body: str,
    attestation: Attestation,
    dedupe_suffix: str,
    extra_payload: dict[str, str | int | None] | None = None,
    link: str | None = None,
) -> None:
    """Queue one durable notification with realtime and email fanout.

    ``link`` defaults to the requestor detail page; attestor-side recipients
    pass their workspace or offers tab instead.
    """
    payload = _payload(attestation, **(extra_payload or {}))
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
            link=link or _attestation_link(attestation.id),
            dedupe_key=f"{notification_type}:{attestation.id}:{dedupe_suffix}",
        )
    except Exception as exc:
        logger.bind(
            module="attestation",
            action="queue_attestation_notification",
            user_id=user_id,
            attestation_id=attestation.id,
            notification_type=notification_type,
        ).error("notification_dispatch_failed", error=str(exc))


def notify_fee_funded(attestation: Attestation) -> None:
    """Notify the requestor that Attestation fee escrow is funded."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_fee_funded",
        title="Attestation fee funded",
        body="Your Attestation fee is now held in escrow and matching has started.",
        attestation=attestation,
        dedupe_suffix="requestor",
    )


def notify_request_received_for_owner(
    attestation: Attestation,
    *,
    owner_id: UUID,
) -> None:
    """Notify a framework owner when someone else funds an Attestation request."""
    _dispatch(
        user_id=owner_id,
        notification_type="attestation_requested_on_your_framework",
        title="Attestation requested on your framework",
        body=(
            "Someone requested an independent attestation on your published framework."
        ),
        attestation=attestation,
        dedupe_suffix="owner",
    )


def notify_consent_requested(attestation: Attestation, *, owner_id: UUID) -> None:
    """Notify a framework owner that consent is required before funding starts."""
    _dispatch(
        user_id=owner_id,
        notification_type="attestation_consent_requested",
        title="Consent requested for framework attestation",
        body=(
            "An operator requested attestation on your published framework and "
            "needs your consent before payment can begin."
        ),
        attestation=attestation,
        dedupe_suffix="consent",
    )


def notify_consent_approved(attestation: Attestation) -> None:
    """Notify the requestor that framework-owner consent was approved."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_consent_approved",
        title="Framework attestation approved",
        body="The framework owner approved your attestation request for funding.",
        attestation=attestation,
        dedupe_suffix="consent-approved",
    )


def notify_consent_declined(attestation: Attestation) -> None:
    """Notify the requestor that framework-owner consent was declined."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_consent_declined",
        title="Framework attestation declined",
        body="The framework owner declined your attestation request.",
        attestation=attestation,
        dedupe_suffix="consent-declined",
    )


def notify_org_offer_received(
    attestation: Attestation,
    *,
    offer: AttestationOffer,
    recipient_id: UUID,
) -> None:
    """Notify one org owner/admin of a new cohort offer to their organization."""
    _dispatch(
        user_id=recipient_id,
        notification_type="attestation_offer_received",
        title="New Attestation offer",
        body="Your organization has a new Attestation request to review.",
        attestation=attestation,
        dedupe_suffix=f"offer:{offer.id}:{recipient_id}",
        extra_payload={
            "offer_id": str(offer.id),
            "cohort_index": offer.cohort_index,
        },
        link=_offers_link(offer.org_id) if offer.org_id else None,
    )


def notify_org_offer_accepted(attestation: Attestation, *, org_id: UUID) -> None:
    """Notify the requestor when an attestor org accepts and staffs the request."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_accepted",
        title="Attestation accepted",
        body="An attestor organization accepted your request and is now reviewing.",
        attestation=attestation,
        dedupe_suffix=f"accepted:{org_id}",
        extra_payload={"attestor_org_id": str(org_id)},
    )


def notify_reviewer_assigned(
    attestation: Attestation, *, reviewer_user_id: UUID
) -> None:
    """Notify an org member when they are staffed as the reviewing member.

    Fired both when an org accepts an offer and staffs a reviewer, and when a
    reviewer is reassigned to a different member before the review starts.

    Args:
        attestation: The attestation the member is now assigned to review.
        reviewer_user_id: User id of the newly assigned reviewing member.
    """
    _dispatch(
        user_id=reviewer_user_id,
        notification_type="attestation_assigned",
        title="Attestation assigned to you",
        body=(
            "You have been assigned to review an attestation. Open your queue to begin."
        ),
        attestation=attestation,
        dedupe_suffix=f"reviewer:{reviewer_user_id}",
        link=_org_side_link(attestation),
    )


def notify_reassigned(
    attestation: Attestation,
    *,
    old_attestor_id: UUID,
) -> None:
    """Notify parties after an overdue assignment returns to matching."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_reassigned",
        title="Attestation reassigned",
        body="The prior Attestor missed the completion SLA, so matching resumed.",
        attestation=attestation,
        dedupe_suffix=f"requestor:{old_attestor_id}",
        extra_payload={"old_attestor_id": str(old_attestor_id)},
    )
    _dispatch(
        user_id=old_attestor_id,
        notification_type="attestation_reassigned",
        title="Attestation assignment revoked",
        body="Your Attestation assignment was revoked after the completion SLA.",
        attestation=attestation,
        dedupe_suffix=f"attestor:{old_attestor_id}",
        extra_payload={"old_attestor_id": str(old_attestor_id)},
        link=_org_side_link(attestation),
    )


def notify_needs_admin(attestation: Attestation) -> None:
    """Notify the requestor and fan out to admins when matching needs help."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_needs_admin",
        title="Attestation needs admin review",
        body="Automated matching could not assign an Attestor yet.",
        attestation=attestation,
        dedupe_suffix="requestor",
    )
    # The requestor notification above only tells the requestor; admins must be
    # pinged too since manual assignment is theirs to perform.
    notify_admins_review_pending(
        domain="attestation",
        target_id=attestation.id,
        body="An attestation could not be auto-matched and needs manual assignment.",
        link="/admin/attestations",
    )


def notify_report_submitted(attestation: Attestation) -> None:
    """Notify the requestor that a report is ready for review."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_report_submitted",
        title="Attestation report submitted",
        body="Your Attestation report is ready for review.",
        attestation=attestation,
        dedupe_suffix="requestor",
    )


def notify_clarification_requested(
    attestation: Attestation,
    *,
    requestor_id: UUID,
    clarification_id: UUID,
) -> None:
    """Notify the requestor that the assigned attestor asked a question."""
    _dispatch(
        user_id=requestor_id,
        notification_type="attestation_clarification_requested",
        title="Clarification requested",
        body="The assigned attestor asked a question about your request.",
        attestation=attestation,
        dedupe_suffix=f"clarification-requested:{clarification_id}",
    )


def notify_clarification_answered(
    attestation: Attestation,
    *,
    attestor_id: UUID,
    clarification_id: UUID,
) -> None:
    """Notify the attestor that the requestor answered a clarification."""
    _dispatch(
        user_id=attestor_id,
        notification_type="attestation_clarification_answered",
        title="Clarification answered",
        body="The requestor answered your clarification question.",
        attestation=attestation,
        dedupe_suffix=f"clarification-answered:{clarification_id}",
        link=_org_side_link(attestation),
    )


def notify_released(
    attestation: Attestation,
    *,
    reason: str,
    recipient_id: UUID | None,
    owner_ids: Iterable[UUID] = (),
) -> None:
    """Notify everyone with a stake in a released attestation.

    The requestor learns the attestation is complete (their detail page). The
    reviewing member (``recipient_id``) and the org owners (``owner_ids``) learn
    the fee was credited, landing on the workspace. Both id sets are resolved
    by the caller while the DB session is live; overlaps are sent once.
    """
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_released",
        title="Attestation complete",
        body=(
            "Your attestation is complete and the report now stands. "
            "You can rate the attestor and download your invoice."
        ),
        attestation=attestation,
        dedupe_suffix=f"requestor:{reason}",
        extra_payload={"reason": reason},
    )
    org_side: list[UUID] = []
    for user_id in ([recipient_id] if recipient_id is not None else []) + list(
        owner_ids
    ):
        if user_id != attestation.requestor_id and user_id not in org_side:
            org_side.append(user_id)
    for user_id in org_side:
        _dispatch(
            user_id=user_id,
            notification_type="attestation_released",
            title="Attestation fee released",
            body="The Attestation fee has been released to the organization's "
            "earnings balance.",
            attestation=attestation,
            dedupe_suffix=f"attestor:{reason}:{user_id}",
            extra_payload={"reason": reason},
            link=_org_side_link(attestation),
        )


def notify_dispute_raised(
    attestation: Attestation,
    *,
    recipient_id: UUID | None,
    dispute_id: UUID | None = None,
) -> None:
    """Notify both parties that the requestor raised a dispute.

    The requestor gets a receipt (the dispute is theirs, but the page state
    changes under them and the admin timeline matters). ``recipient_id`` is
    the reviewing member's user id, resolved by the caller while the DB
    session is live; None when no reviewing member is staffed.
    """
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_disputed",
        title="Dispute received",
        body=(
            "Your dispute is with the trust team. Escrow stays held until an "
            "administrator decides; you will be notified of the outcome."
        ),
        attestation=attestation,
        dedupe_suffix="requestor",
    )
    if recipient_id is None:
        return
    _dispatch(
        user_id=recipient_id,
        notification_type="attestation_disputed",
        title="Attestation dispute raised",
        body="The requestor disputed your submitted Attestation report.",
        attestation=attestation,
        dedupe_suffix="attestor",
        link=_org_side_link(attestation),
    )
    # Admins resolve attestation disputes; without this only the requestor and
    # the attestor org heard about one, and the admin queue filled silently.
    notify_admins_review_pending(
        domain="attestation_dispute",
        target_id=dispute_id or attestation.id,
        body="A requestor disputed an attestation report and it needs resolution.",
        link="/admin/disputes?tab=attestation",
    )


def notify_dispute_resolved(
    attestation: Attestation, *, outcome: str, recipient_id: UUID | None
) -> None:
    """Notify both parties when an Attestation dispute is resolved.

    Args:
        attestation: The disputed attestation.
        outcome: The resolution verdict — ``rejected``, ``upheld_refund``, or
            ``upheld_revise``.
        recipient_id: The reviewing member's user id (attestor side), resolved
            by the caller while the DB session is live; None when unstaffed.
    """
    due = _due_date(attestation.completion_due_at)
    bodies: dict[str, tuple[str, str]] = {
        "rejected": (
            "The dispute was not upheld. The report stands and the fee has "
            "been released.",
            "The dispute against your report was not upheld. The report "
            "stands and the fee has been released.",
        ),
        "upheld_refund": (
            "The dispute was upheld. Your fee has been refunded.",
            "The dispute against your report was upheld and the fee refunded.",
        ),
        "upheld_revise": (
            f"The dispute was upheld. The attestor must revise the report by {due}.",
            f"The dispute was upheld. Revise and resubmit the report by {due}.",
        ),
    }
    requestor_body, attestor_body = bodies.get(
        outcome, ("Admin resolved an Attestation dispute.",) * 2
    )
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_dispute_resolved",
        title="Attestation dispute resolved",
        body=requestor_body,
        attestation=attestation,
        dedupe_suffix=f"{outcome}:{attestation.requestor_id}",
        extra_payload={"outcome": outcome},
    )
    if recipient_id is None or recipient_id == attestation.requestor_id:
        return
    _dispatch(
        user_id=recipient_id,
        notification_type="attestation_dispute_resolved",
        title="Attestation dispute resolved",
        body=attestor_body,
        attestation=attestation,
        dedupe_suffix=f"{outcome}:{recipient_id}",
        extra_payload={"outcome": outcome},
        link=_org_side_link(attestation),
    )


def notify_org_attestor_warning(
    recipient_id: UUID, *, org_id: UUID, reason: str
) -> bool:
    """Notify one org owner/admin that an upheld dispute warned the organization.

    The reviewing member who staffed the disputed attestation is never named;
    the warning attaches to the organization and its managers are notified.

    Args:
        recipient_id: An owner or admin of the warned organization.
        org_id: The warned attestor organization.
        reason: Short human-readable warning reason (no PII).

    Returns:
        True if the notification was enqueued; False if dispatch failed.
    """
    try:
        dispatch_project_notification.delay(
            user_id=str(recipient_id),
            notification_type="org_attestor_warning_issued",
            title="A dispute was upheld against your organization",
            body=(
                "An admin upheld a dispute on one of your organization's "
                "attestations and recorded a formal warning. Repeated warnings "
                "trigger a review."
            ),
            payload={"reason": reason, "org_id": str(org_id)},
            link=_attestor_onboarding_link(),
            dedupe_key=f"org_attestor_warning_issued:{org_id}:{recipient_id}:{reason}",
        )
    except Exception as exc:
        logger.bind(
            module="attestation",
            action="queue_org_attestor_warning_notification",
            org_id=org_id,
        ).error("notification_dispatch_failed", error=str(exc))
        return False
    return True


def notify_refunded(attestation: Attestation, *, reason: str) -> None:
    """Notify the requestor that an Attestation fee was refunded."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_refunded",
        title="Attestation fee refunded",
        body="Your Attestation fee has been refunded.",
        attestation=attestation,
        dedupe_suffix=f"requestor:{reason}",
        extra_payload={"reason": reason},
    )


def notify_offer_expired_for_requestor(attestation: Attestation) -> None:
    """Tell the requestor a cohort lapsed and matching moved on.

    Fired by the offer-expiry beat once per lapsed cohort; the dedupe key
    carries the current status so a later cohort lapse is a fresh message.
    """
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_offer_expired",
        title="Still finding an attestor",
        body=(
            "The attestors we offered your request to did not respond in time. "
            "We are offering it to the next eligible organizations."
        ),
        attestation=attestation,
        dedupe_suffix=f"requestor:{datetime.now(UTC).isoformat()}",
    )


def notify_clarification_expired(
    attestation: Attestation, *, clarification_id: UUID
) -> None:
    """Tell the requestor a clarification lapsed unanswered."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_clarification_expired",
        title="Clarification lapsed",
        body=(
            "A question from your attestor went unanswered and has lapsed. "
            "The review continues on the information already provided."
        ),
        attestation=attestation,
        dedupe_suffix=f"clarification-expired:{clarification_id}",
        extra_payload={"clarification_id": str(clarification_id)},
    )


def notify_withdrawn(
    attestation: Attestation, *, org_id: UUID, recipient_id: UUID
) -> None:
    """Tell an org manager that a request they held an open offer on was withdrawn."""
    _dispatch(
        user_id=recipient_id,
        notification_type="attestation_withdrawn",
        title="Attestation request withdrawn",
        body="The requestor withdrew a request your organization had been offered.",
        attestation=attestation,
        dedupe_suffix=f"withdrawn:{org_id}:{recipient_id}",
        extra_payload={"org_id": str(org_id)},
        link=_offers_link(org_id),
    )


def notify_coi_expiring(user_id: UUID, *, expires_at: datetime) -> bool:
    """Notify an Attestor that their CoI declaration expires within 30 days.

    Returns:
        True if the reminder was enqueued; False if dispatch failed. The caller
        uses this to avoid marking an attestor reminded when the broker is down.
    """
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type="attestor_coi_expiring",
            title="Your conflict-of-interest declaration is expiring",
            body=(
                "Re-sign your conflict-of-interest declaration before it expires "
                "to keep receiving attestation requests."
            ),
            payload={"expires_at": expires_at.isoformat()},
            link=_attestor_onboarding_link(),
            dedupe_key=f"attestor_coi_expiring:{user_id}:{expires_at.isoformat()}",
        )
    except Exception as exc:
        logger.bind(
            module="attestation",
            action="queue_coi_expiring_notification",
            user_id=user_id,
        ).error("notification_dispatch_failed", error=str(exc))
        return False
    return True


def notify_coi_lapsed(user_id: UUID, *, expires_at: datetime) -> bool:
    """Notify an Attestor that their CoI declaration has lapsed.

    Returns:
        True if the reminder was enqueued; False if dispatch failed. The caller
        uses this to avoid marking an attestor reminded when the broker is down.
    """
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type="attestor_coi_lapsed",
            title="Your conflict-of-interest declaration has lapsed",
            body=(
                "Your conflict-of-interest declaration has expired. Re-sign it "
                "to resume receiving attestation requests."
            ),
            payload={"expires_at": expires_at.isoformat()},
            link=_attestor_onboarding_link(),
            dedupe_key=f"attestor_coi_lapsed:{user_id}:{expires_at.isoformat()}",
        )
    except Exception as exc:
        logger.bind(
            module="attestation",
            action="queue_coi_lapsed_notification",
            user_id=user_id,
        ).error("notification_dispatch_failed", error=str(exc))
        return False
    return True
