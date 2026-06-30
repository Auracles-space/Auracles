"""Attestation notification and deferred reputation-event helpers.

The current reputation module has no persistent scoring ledger yet, so this
slice emits outcome breadcrumbs through audit logs and durable user
notifications. Phase 5 can consume the same event names when scoring exists.
"""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.modules.attestation.models import Attestation, AttestationOffer
from app.workers.tasks.project_notifications import dispatch_project_notification


def _attestation_link(attestation_id: UUID) -> str:
    """Return the dashboard route for an Attestation detail page."""
    return f"/attestations/{attestation_id}"


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
            "Someone requested an independent attestation on your published "
            "framework."
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


def notify_offers(attestation: Attestation, offers: list[AttestationOffer]) -> None:
    """Notify each Attestor in a newly offered cohort."""
    for offer in offers:
        _dispatch(
            user_id=offer.attestor_id,
            notification_type="attestation_offer_received",
            title="New Attestation offer",
            body="You have a new Attestation request to review.",
            attestation=attestation,
            dedupe_suffix=f"offer:{offer.id}",
            extra_payload={
                "offer_id": str(offer.id),
                "cohort_index": offer.cohort_index,
            },
        )


def notify_offer_accepted(attestation: Attestation, attestor_id: UUID) -> None:
    """Notify the requestor when an Attestor accepts the assignment."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_accepted",
        title="Attestation accepted",
        body="An Attestor accepted your request and is now reviewing the target.",
        attestation=attestation,
        dedupe_suffix=f"accepted:{attestor_id}",
        extra_payload={"attestor_id": str(attestor_id)},
    )


def notify_offer_declined(attestation: Attestation, attestor_id: UUID) -> None:
    """Notify the requestor when an Attestor declines an offered assignment."""
    _dispatch(
        user_id=attestation.requestor_id,
        notification_type="attestation_declined",
        title="Attestation offer declined",
        body="An Attestor declined your Attestation request.",
        attestation=attestation,
        dedupe_suffix=f"declined:{attestor_id}",
        extra_payload={"attestor_id": str(attestor_id)},
    )


def notify_offer_expired(attestation: Attestation, offer: AttestationOffer) -> None:
    """Notify an Attestor when their pending offer expires."""
    _dispatch(
        user_id=offer.attestor_id,
        notification_type="attestation_offer_expired",
        title="Attestation offer expired",
        body="An Attestation offer expired before it was accepted.",
        attestation=attestation,
        dedupe_suffix=f"offer:{offer.id}",
        extra_payload={
            "offer_id": str(offer.id),
            "cohort_index": offer.cohort_index,
        },
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


def notify_released(attestation: Attestation, *, reason: str) -> None:
    """Notify the assigned Attestor that escrow has been released."""
    if attestation.attestor_id is None:
        return
    _dispatch(
        user_id=attestation.attestor_id,
        notification_type="attestation_released",
        title="Attestation fee released",
        body="The Attestation fee has been released to your earnings balance.",
        attestation=attestation,
        dedupe_suffix=f"attestor:{reason}",
        extra_payload={"reason": reason},
    )


def notify_dispute_raised(attestation: Attestation) -> None:
    """Notify the assigned Attestor that the requestor raised a dispute."""
    if attestation.attestor_id is None:
        return
    _dispatch(
        user_id=attestation.attestor_id,
        notification_type="attestation_disputed",
        title="Attestation dispute raised",
        body="The requestor disputed your submitted Attestation report.",
        attestation=attestation,
        dedupe_suffix="attestor",
    )


def notify_dispute_resolved(attestation: Attestation, *, resolution_type: str) -> None:
    """Notify both parties when an Attestation dispute is resolved."""
    recipients = [attestation.requestor_id]
    if attestation.attestor_id is not None:
        recipients.append(attestation.attestor_id)
    for user_id in recipients:
        _dispatch(
            user_id=user_id,
            notification_type="attestation_dispute_resolved",
            title="Attestation dispute resolved",
            body="Admin resolved an Attestation dispute.",
            attestation=attestation,
            dedupe_suffix=f"{resolution_type}:{user_id}",
            extra_payload={"resolution_type": resolution_type},
        )


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


def notify_manual_assignment(attestation: Attestation, attestor_id: UUID) -> None:
    """Notify both parties after Admin manually assigns an Attestor."""
    notify_offer_accepted(attestation, attestor_id)
    _dispatch(
        user_id=attestor_id,
        notification_type="attestation_assigned",
        title="Attestation assigned",
        body="Admin assigned you to an Attestation request.",
        attestation=attestation,
        dedupe_suffix=f"manual:{attestor_id}",
        extra_payload={"attestor_id": str(attestor_id)},
    )
