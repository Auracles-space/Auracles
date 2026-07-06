"""Attestation notification and deferred reputation-event helpers.

The current reputation module has no persistent scoring ledger yet, so this
slice emits outcome breadcrumbs through audit logs and durable user
notifications. Phase 5 can consume the same event names when scoring exists.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from loguru import logger

from app.modules.attestation.models import Attestation, AttestationOffer
from app.workers.tasks.project_notifications import dispatch_project_notification


def _attestation_link(attestation_id: UUID) -> str:
    """Return the dashboard route for an Attestation detail page."""
    return f"/attestations/{attestation_id}"


def _attestor_onboarding_link() -> str:
    """Return the dashboard route for Attestor onboarding prerequisites."""
    return "/attestor/onboarding"


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
) -> None:
    """Queue one durable notification with realtime and email fanout."""
    payload = _payload(attestation, **(extra_payload or {}))
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
            link=_attestation_link(attestation.id),
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
    )


def notify_needs_admin(attestation: Attestation) -> None:
    """Notify the requestor when automated matching requires Admin help."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_needs_admin",
        title="Attestation needs admin review",
        body="Automated matching could not assign an Attestor yet.",
        attestation=attestation,
        dedupe_suffix="requestor",
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
    )


def notify_released(
    attestation: Attestation, *, reason: str, recipient_id: UUID | None
) -> None:
    """Notify the reviewing member that the org's attestation fee was released.

    ``recipient_id`` is the user id of the reviewing member who performed the
    review, resolved by the caller while the DB session is live. When no
    reviewing member is recorded, no notification is dispatched.
    """
    if recipient_id is None:
        return
    _dispatch(
        user_id=recipient_id,
        notification_type="attestation_released",
        title="Attestation fee released",
        body="The Attestation fee has been released to the organization's "
        "earnings balance.",
        attestation=attestation,
        dedupe_suffix=f"attestor:{reason}",
        extra_payload={"reason": reason},
    )


def notify_dispute_raised(
    attestation: Attestation, *, recipient_id: UUID | None
) -> None:
    """Notify the reviewing member that the requestor raised a dispute.

    ``recipient_id`` is the reviewing member's user id, resolved by the caller
    while the DB session is live. None when no reviewing member is staffed.
    """
    if recipient_id is None:
        return
    _dispatch(
        user_id=recipient_id,
        notification_type="attestation_disputed",
        title="Attestation dispute raised",
        body="The requestor disputed your submitted Attestation report.",
        attestation=attestation,
        dedupe_suffix="attestor",
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
    recipients = [attestation.requestor_id]
    if recipient_id is not None:
        recipients.append(recipient_id)
    for user_id in recipients:
        _dispatch(
            user_id=user_id,
            notification_type="attestation_dispute_resolved",
            title="Attestation dispute resolved",
            body="Admin resolved an Attestation dispute.",
            attestation=attestation,
            dedupe_suffix=f"{outcome}:{user_id}",
            extra_payload={"outcome": outcome},
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
