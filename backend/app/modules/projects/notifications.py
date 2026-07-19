"""Project lifecycle notification helpers.

Project services call these fire-and-forget helpers after committing their own
domain state. Each helper queues a durable in-app notification with realtime
and email fanout via `dispatch_project_notification`, mirroring the attestation
notification module. Recipients are the counterparty to the action: the
Operator hears about inbound bids and submitted work, the Contributor hears
about acceptance, funding, and approval outcomes.

Maps to the Project event types exposed in notification preferences
(FR-SET-008) so the settings toggles control notifications that actually fire.
"""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.modules.projects.models import Proposal
from app.workers.tasks.project_notifications import dispatch_project_notification


def _project_link(project_id: UUID, operator_org_id: UUID | None = None) -> str:
    """Return the dashboard route an Operator uses to open a Project.

    Org-operated Projects live under the organization namespace; an org owner
    or admin has no individual-Operator access, so the plain ``/projects/{id}``
    detail route resolves to "Project is not visible to this user". When the
    recipient is on the operating org's side, deep-link to the org route
    instead so the notification opens the page they can actually see.
    """
    if operator_org_id is not None:
        return f"/dashboard/organizations/{operator_org_id}/projects/{project_id}"
    return f"/projects/{project_id}"


def _dispatch(
    *,
    user_id: UUID,
    notification_type: str,
    title: str,
    body: str,
    project_id: UUID,
    dedupe_key: str | None,
    extra_payload: dict[str, str] | None = None,
    operator_org_id: UUID | None = None,
) -> None:
    """Queue one durable Project notification with realtime and email fanout."""
    payload = {"project_id": str(project_id)}
    if extra_payload is not None:
        payload.update(extra_payload)
    try:
        dispatch_project_notification.delay(
            user_id=str(user_id),
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
            link=_project_link(project_id, operator_org_id),
            dedupe_key=dedupe_key,
        )
    except Exception as exc:  # noqa: BLE001 — never break the request on fanout.
        logger.bind(
            module="projects",
            action="queue_project_notification",
            user_id=user_id,
            project_id=project_id,
            notification_type=notification_type,
        ).error("notification_dispatch_failed", error=str(exc))


def notify_proposal_submitted(
    *,
    operator_id: UUID,
    proposal: Proposal,
    operator_org_id: UUID | None = None,
) -> None:
    """Notify the Operator that a Contributor submitted a Proposal."""
    _dispatch(
        user_id=operator_id,
        notification_type="proposal_submitted",
        title="New proposal received",
        body="A Contributor submitted a proposal on your Project.",
        project_id=proposal.project_id,
        dedupe_key=f"proposal_submitted:{proposal.id}",
        extra_payload={"proposal_id": str(proposal.id)},
        operator_org_id=operator_org_id,
    )


def notify_proposal_withdrawn(
    *,
    operator_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    operator_org_id: UUID | None = None,
) -> None:
    """Notify the Operator that a Contributor withdrew their pending Proposal."""
    _dispatch(
        user_id=operator_id,
        notification_type="proposal_withdrawn",
        title="Proposal withdrawn",
        body="A Contributor withdrew their proposal on your Project.",
        project_id=project_id,
        dedupe_key=f"proposal_withdrawn:{proposal_id}",
        extra_payload={"proposal_id": str(proposal_id)},
        operator_org_id=operator_org_id,
    )


def notify_proposal_rejected(
    *,
    contributor_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
) -> None:
    """Notify a Contributor that their Proposal was rejected.

    Takes plain ids because rejected bids are bulk-updated rather than loaded
    as ORM objects when a competing Proposal is accepted.
    """
    _dispatch(
        user_id=contributor_id,
        notification_type="proposal_rejected",
        title="Proposal not selected",
        body="The Operator selected a different proposal for this Project.",
        project_id=project_id,
        dedupe_key=f"proposal_rejected:{proposal_id}",
        extra_payload={"proposal_id": str(proposal_id)},
    )


def notify_proposal_accepted(*, contributor_id: UUID, proposal: Proposal) -> None:
    """Notify the Contributor that their Proposal was accepted."""
    _dispatch(
        user_id=contributor_id,
        notification_type="proposal_accepted",
        title="Proposal accepted",
        body="The Operator accepted your proposal. You can start the Project.",
        project_id=proposal.project_id,
        dedupe_key=f"proposal_accepted:{proposal.id}",
        extra_payload={"proposal_id": str(proposal.id)},
    )


def notify_milestone_plan_finalized(
    *,
    operator_id: UUID,
    project_id: UUID,
    operator_org_id: UUID | None = None,
) -> None:
    """Notify the Operator that the Contributor finalized the Milestone plan.

    Finalization is the Contributor's signal that the budget breakdown is set
    and the Operator can fund the first Milestone's escrow, so the counterparty
    (the Operator, or every owner/admin of the operating org) must hear about
    it to move the Project forward.
    """
    _dispatch(
        user_id=operator_id,
        notification_type="milestone_plan_finalized",
        title="Milestone plan finalized",
        body="A Contributor finalized the Milestone plan. Fund the first "
        "Milestone to start the work.",
        project_id=project_id,
        # No dedupe key: a plan can be reopened and finalized again, and each
        # genuine finalization must re-notify. The finalize service is state
        # guarded (draft-only), so a single transition fires exactly one notice.
        dedupe_key=None,
        operator_org_id=operator_org_id,
    )


def notify_milestone_funded(
    *,
    contributor_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
) -> None:
    """Notify the assigned Contributor that a Milestone's escrow is funded."""
    _dispatch(
        user_id=contributor_id,
        notification_type="milestone_funded",
        title="Milestone funded",
        body="Escrow is funded for a Milestone. You can start the work.",
        project_id=project_id,
        dedupe_key=f"milestone_funded:{milestone_id}",
        extra_payload={"milestone_id": str(milestone_id)},
    )


def notify_deliverable_submitted(
    *,
    operator_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    operator_org_id: UUID | None = None,
) -> None:
    """Notify the Operator that a Deliverable was submitted for review."""
    _dispatch(
        user_id=operator_id,
        notification_type="deliverable_submitted",
        title="Deliverable submitted",
        body="A Contributor submitted a Deliverable for your review.",
        project_id=project_id,
        dedupe_key=f"deliverable_submitted:{deliverable_id}",
        extra_payload={
            "milestone_id": str(milestone_id),
            "deliverable_id": str(deliverable_id),
        },
        operator_org_id=operator_org_id,
    )


def notify_deliverable_revision_requested(
    *,
    contributor_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
) -> None:
    """Notify the Contributor that the Operator requested a Deliverable revision."""
    _dispatch(
        user_id=contributor_id,
        notification_type="deliverable_revision_requested",
        title="Revision requested",
        body="The Operator requested changes to your submitted Deliverable.",
        project_id=project_id,
        dedupe_key=f"deliverable_revision_requested:{deliverable_id}",
        extra_payload={
            "milestone_id": str(milestone_id),
            "deliverable_id": str(deliverable_id),
        },
    )


def notify_deliverable_approved(
    *,
    contributor_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
) -> None:
    """Notify the Contributor that a Deliverable was approved and escrow released."""
    _dispatch(
        user_id=contributor_id,
        notification_type="deliverable_approved",
        title="Deliverable approved",
        body="The Operator approved your Deliverable and released the escrow.",
        project_id=project_id,
        dedupe_key=f"deliverable_approved:{deliverable_id}",
        extra_payload={
            "milestone_id": str(milestone_id),
            "deliverable_id": str(deliverable_id),
        },
    )


def notify_deliverable_auto_approved(
    *,
    contributor_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
) -> None:
    """Notify the Contributor that an idle Deliverable auto-approved on timeout."""
    _dispatch(
        user_id=contributor_id,
        notification_type="deliverable_auto_approved",
        title="Deliverable auto-approved",
        body=(
            "The Operator did not act in time, so your Deliverable auto-approved "
            "and the escrow was released."
        ),
        project_id=project_id,
        dedupe_key=f"deliverable_auto_approved:{deliverable_id}",
        extra_payload={
            "milestone_id": str(milestone_id),
            "deliverable_id": str(deliverable_id),
        },
    )


def notify_operator_deliverable_auto_approved(
    *,
    operator_id: UUID,
    project_id: UUID,
    milestone_id: UUID,
    deliverable_id: UUID,
    operator_org_id: UUID | None = None,
) -> None:
    """Notify a Project Operator that inaction auto-approved a Deliverable.

    Sent to the operating organization's owners/admins on an org-operated
    Project so the Operator side learns the escrow released because no one acted
    within the timeout. The individual-Operator path already surfaces this in the
    workspace; this helper resolves the org's several admins rather than a single
    operator user.
    """
    _dispatch(
        user_id=operator_id,
        notification_type="deliverable_auto_approved",
        title="Deliverable auto-approved",
        body=(
            "No one acted on a submitted Deliverable in time, so it auto-approved "
            "and the escrow was released to the Contributor."
        ),
        project_id=project_id,
        dedupe_key=f"deliverable_auto_approved_operator:{deliverable_id}:{operator_id}",
        extra_payload={
            "milestone_id": str(milestone_id),
            "deliverable_id": str(deliverable_id),
        },
        operator_org_id=operator_org_id,
    )


def _amendment_payload(proposal_id: UUID, amendment_id: UUID) -> dict[str, str]:
    """Build the shared payload for Proposal amendment notifications."""
    return {
        "proposal_id": str(proposal_id),
        "amendment_id": str(amendment_id),
    }


def notify_amendment_proposed(
    *,
    counterparty_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
) -> None:
    """Notify the counterparty that a Proposal amendment awaits their response."""
    _dispatch(
        user_id=counterparty_id,
        notification_type="amendment_proposed",
        title="Amendment proposed",
        body="The other party proposed an amendment to the agreed Proposal.",
        project_id=project_id,
        dedupe_key=f"amendment_proposed:{amendment_id}",
        extra_payload=_amendment_payload(proposal_id, amendment_id),
    )


def notify_amendment_accepted(
    *,
    proposer_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
) -> None:
    """Notify the proposer that their Proposal amendment was accepted."""
    _dispatch(
        user_id=proposer_id,
        notification_type="amendment_accepted",
        title="Amendment accepted",
        body="The counterparty accepted your proposed amendment.",
        project_id=project_id,
        dedupe_key=f"amendment_accepted:{amendment_id}",
        extra_payload=_amendment_payload(proposal_id, amendment_id),
    )


def notify_amendment_rejected(
    *,
    proposer_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
) -> None:
    """Notify the proposer that their Proposal amendment was rejected."""
    _dispatch(
        user_id=proposer_id,
        notification_type="amendment_rejected",
        title="Amendment rejected",
        body="The counterparty rejected your proposed amendment.",
        project_id=project_id,
        dedupe_key=f"amendment_rejected:{amendment_id}",
        extra_payload=_amendment_payload(proposal_id, amendment_id),
    )


def notify_amendment_withdrawn(
    *,
    counterparty_id: UUID,
    project_id: UUID,
    proposal_id: UUID,
    amendment_id: UUID,
) -> None:
    """Notify the counterparty that the proposer withdrew a pending amendment."""
    _dispatch(
        user_id=counterparty_id,
        notification_type="amendment_withdrawn",
        title="Amendment withdrawn",
        body="The other party withdrew their pending amendment.",
        project_id=project_id,
        dedupe_key=f"amendment_withdrawn:{amendment_id}",
        extra_payload=_amendment_payload(proposal_id, amendment_id),
    )


def notify_workspace_file_quarantined(
    *,
    uploader_id: UUID,
    project_id: UUID,
    message_id: UUID,
) -> None:
    """Notify the uploader that a Workspace attachment was quarantined."""
    _dispatch(
        user_id=uploader_id,
        notification_type="workspace_file_quarantined",
        title="File quarantined",
        body="A file you uploaded to the Workspace failed the virus scan.",
        project_id=project_id,
        dedupe_key=f"workspace_file_quarantined:{message_id}",
        extra_payload={"message_id": str(message_id)},
    )
