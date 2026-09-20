"""Scheduled Project maintenance tasks for Phase 4a."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.modules.auth.models import UserRole
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow
from app.modules.projects import notifications as project_notifications
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
    ProposalAmendment,
)
from app.modules.projects.operator_ownership import (
    resolve_operator_recipient_user_ids,
)
from app.modules.workspace.models import WorkspaceMessage
from app.workers.async_runner import run_async
from app.workers.celery_app import app
from app.workers.tasks.project_notifications import dispatch_project_notification


async def _withdraw_pending_proposals_for_closed_projects() -> int:
    """Withdraw pending Proposals whose Project is already closed."""
    now = datetime.now(UTC)
    withdrawn_count = 0
    async with async_session_factory() as db:
        async with db.begin():
            proposals = (
                (
                    await db.execute(
                        select(Proposal)
                        .join(Project, Project.id == Proposal.project_id)
                        .where(
                            Project.status == "closed",
                            Proposal.status == "pending",
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for proposal in proposals:
                proposal.status = "withdrawn"
                proposal.withdrawn_at = now
                withdrawn_count += 1
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="proposal_expired",
                    target_type="proposal",
                    target_id=proposal.id,
                    metadata={"project_id": str(proposal.project_id)},
                )
    return withdrawn_count


async def _close_expired_projects() -> dict[str, int]:
    """Close open Projects past `expires_at` and withdraw pending Proposals."""
    now = datetime.now(UTC)
    closed_count = 0
    withdrawn_count = 0
    async with async_session_factory() as db:
        async with db.begin():
            projects = (
                (
                    await db.execute(
                        select(Project)
                        .where(Project.status == "open", Project.expires_at < now)
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for project in projects:
                project.status = "closed"
                project.closed_at = now
                closed_count += 1
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="project_closed",
                    target_type="project",
                    target_id=project.id,
                    metadata={"reason": "expired_without_accepted_proposal"},
                )

                proposals = (
                    (
                        await db.execute(
                            select(Proposal)
                            .where(
                                Proposal.project_id == project.id,
                                Proposal.status == "pending",
                            )
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                for proposal in proposals:
                    proposal.status = "withdrawn"
                    proposal.withdrawn_at = now
                    withdrawn_count += 1
                    await write_audit(
                        db=db,
                        actor_id=None,
                        action="proposal_expired",
                        target_type="proposal",
                        target_id=proposal.id,
                        metadata={"project_id": str(project.id)},
                    )
    return {"closed_count": closed_count, "withdrawn_count": withdrawn_count}


async def _expire_pending_amendments() -> int:
    """Expire pending Proposal Amendments whose seven-day window has elapsed."""
    now = datetime.now(UTC)
    expired_count = 0
    async with async_session_factory() as db:
        async with db.begin():
            rows = (
                await db.execute(
                    select(ProposalAmendment, Proposal.project_id)
                    .join(Proposal, Proposal.id == ProposalAmendment.proposal_id)
                    .where(
                        ProposalAmendment.status == "pending",
                        ProposalAmendment.expires_at < now,
                    )
                    .with_for_update()
                )
            ).all()
            for amendment, project_id in rows:
                amendment.status = "expired"
                amendment.responded_at = now
                db.add(
                    WorkspaceMessage(
                        project_id=project_id,
                        sender_id=None,
                        system_event="amendment_expired",
                        system_payload={
                            "amendment_id": str(amendment.id),
                            "proposal_id": str(amendment.proposal_id),
                        },
                    )
                )
                expired_count += 1
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="amendment_expired",
                    target_type="proposal_amendment",
                    target_id=amendment.id,
                    metadata={"project_id": str(project_id)},
                )
    return expired_count


async def _maybe_mark_project_delivered(
    *,
    db: Any,
    project: Project,
    now: datetime,
) -> None:
    """Mark Project delivered when every Milestone is terminally complete."""
    active_count = await db.scalar(
        select(Milestone.id)
        .where(
            Milestone.project_id == project.id,
            Milestone.status.notin_(("approved", "auto_approved", "cancelled")),
        )
        .limit(1)
    )
    if active_count is None:
        project.status = "delivered"
        project.delivered_at = project.delivered_at or now


async def _auto_approve_deliverables() -> int:
    """Auto-approve submitted Deliverables left idle past fourteen days."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=14)
    auto_approved_count = 0
    # Collect recipients during the transaction; notify after it commits so the
    # Contributor only hears about a durable auto-approval.
    auto_approved_notifications: list[tuple[UUID, UUID, UUID, UUID]] = []
    # Org-operated Projects have no single Operator user; collect the operating
    # org's owner/admin recipients so the Operator side is notified too.
    operator_notifications: list[tuple[list[UUID], UUID, UUID, UUID, UUID]] = []
    async with async_session_factory() as db:
        async with db.begin():
            rows = (
                await db.execute(
                    select(Deliverable, Milestone, Project)
                    .join(Milestone, Milestone.id == Deliverable.milestone_id)
                    .join(Project, Project.id == Milestone.project_id)
                    .where(
                        Deliverable.status == "submitted",
                        Deliverable.submitted_at < cutoff,
                        Milestone.status.notin_(
                            (
                                "disputed",
                                "revision_requested",
                                "auto_approved",
                                "approved",
                            )
                        ),
                    )
                    .with_for_update()
                )
            ).all()
            for deliverable, milestone, project in rows:
                active_dispute_id = await db.scalar(
                    select(Dispute.id)
                    .where(
                        Dispute.milestone_id == milestone.id,
                        Dispute.status.in_(("open", "under_review")),
                    )
                    .limit(1)
                )
                if active_dispute_id is not None or milestone.escrow_id is None:
                    continue
                await db.scalar(
                    select(Escrow)
                    .where(Escrow.id == milestone.escrow_id)
                    .with_for_update()
                )
                # actor_id is the individual Operator, or NULL for an org-operated
                # Project (a system-initiated release with no single acting user);
                # released_by and the audit actor both accept NULL.
                await escrow_service.release(
                    db,
                    escrow_id=milestone.escrow_id,
                    actor_id=project.operator_id,
                    reason="deliverable_auto_approved",
                )
                deliverable.status = "auto_approved"
                deliverable.auto_approved = True
                deliverable.approved_at = now
                milestone.status = "auto_approved"
                milestone.approved_at = now
                await _maybe_mark_project_delivered(db=db, project=project, now=now)
                db.add(
                    WorkspaceMessage(
                        project_id=project.id,
                        sender_id=None,
                        system_event="deliverable_auto_approved",
                        system_payload={
                            "milestone_id": str(milestone.id),
                            "deliverable_id": str(deliverable.id),
                        },
                    )
                )
                auto_approved_count += 1
                auto_approved_notifications.append(
                    (
                        deliverable.contributor_id,
                        project.id,
                        milestone.id,
                        deliverable.id,
                    )
                )
                if project.operator_org_id is not None:
                    operator_recipient_ids = (
                        await resolve_operator_recipient_user_ids(db, project=project)
                    )
                    operator_notifications.append(
                        (
                            operator_recipient_ids,
                            project.id,
                            milestone.id,
                            deliverable.id,
                            project.operator_org_id,
                        )
                    )
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="deliverable_auto_approved",
                    target_type="deliverable",
                    target_id=deliverable.id,
                    metadata={
                        "project_id": str(project.id),
                        "milestone_id": str(milestone.id),
                    },
                )

    for (
        contributor_id,
        project_id,
        milestone_id,
        deliverable_id,
    ) in auto_approved_notifications:
        # An org-Contributor Deliverable stamps contributor_org_id, not
        # contributor_id; skip the single-user notification when there is no
        # individual Contributor recipient to address.
        if contributor_id is None:
            continue
        project_notifications.notify_deliverable_auto_approved(
            contributor_id=contributor_id,
            project_id=project_id,
            milestone_id=milestone_id,
            deliverable_id=deliverable_id,
        )
    for (
        operator_recipient_ids,
        project_id,
        milestone_id,
        deliverable_id,
        operator_org_id,
    ) in operator_notifications:
        for operator_id in operator_recipient_ids:
            project_notifications.notify_operator_deliverable_auto_approved(
                operator_id=operator_id,
                project_id=project_id,
                milestone_id=milestone_id,
                deliverable_id=deliverable_id,
                operator_org_id=operator_org_id,
            )
    return auto_approved_count


async def _auto_close_delivered_projects() -> int:
    """Archive delivered Projects after the seven-day operational delay."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=7)
    closed_count = 0
    async with async_session_factory() as db:
        async with db.begin():
            projects = (
                (
                    await db.execute(
                        select(Project)
                        .where(
                            Project.status == "delivered",
                            Project.delivered_at < cutoff,
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for project in projects:
                active_dispute_id = await db.scalar(
                    select(Dispute.id)
                    .where(
                        Dispute.project_id == project.id,
                        Dispute.status.in_(("open", "under_review")),
                    )
                    .limit(1)
                )
                if active_dispute_id is not None:
                    continue
                project.status = "closed"
                project.closed_at = now
                closed_count += 1
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="project_closed",
                    target_type="project",
                    target_id=project.id,
                    metadata={"reason": "delivered_project_archive_delay_elapsed"},
                )
    return closed_count


async def _escalate_disputes() -> int:
    """Move stale open Disputes into admin review."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=7)
    escalated_count = 0
    admin_user_ids: list[str] = []
    escalated_dispute_ids: list[str] = []
    async with async_session_factory() as db:
        async with db.begin():
            disputes = (
                (
                    await db.execute(
                        select(Dispute)
                        .where(
                            Dispute.status == "open",
                            Dispute.created_at < cutoff,
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            if disputes:
                admin_user_ids = [
                    str(user_id)
                    for user_id in (
                        (
                            await db.execute(
                                select(UserRole.user_id).where(
                                    UserRole.role == "admin",
                                    UserRole.approved_at.is_not(None),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                ]
            for dispute in disputes:
                dispute.status = "under_review"
                dispute.escalated_at = now
                escalated_count += 1
                escalated_dispute_ids.append(str(dispute.id))
                await write_audit(
                    db=db,
                    actor_id=None,
                    action="dispute_escalated",
                    target_type="dispute",
                    target_id=dispute.id,
                    metadata={
                        "project_id": str(dispute.project_id),
                        "milestone_id": str(dispute.milestone_id),
                    },
                )

    for dispute_id in escalated_dispute_ids:
        for user_id in admin_user_ids:
            dispatch_project_notification.delay(
                user_id=user_id,
                notification_type="dispute_escalated",
                title="Project dispute needs review",
                body="A project dispute has escalated to admin review.",
                payload={"dispute_id": dispute_id},
                link="/admin/disputes",
                dedupe_key=f"dispute_escalated:{dispute_id}:{user_id}",
            )
    return escalated_count


@app.task(bind=True)  # type: ignore[untyped-decorator]
def expire_open_proposals(self: Any) -> dict[str, int]:
    """Withdraw pending Proposals attached to closed Projects."""
    log = logger.bind(
        module="projects",
        action="expire_open_proposals",
        task_id=self.request.id,
    )
    log.info("task_started")
    withdrawn_count = run_async(_withdraw_pending_proposals_for_closed_projects())
    result = {"withdrawn_count": withdrawn_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def close_expired_projects(self: Any) -> dict[str, int]:
    """Close open Projects whose proposal window has expired."""
    log = logger.bind(
        module="projects",
        action="close_expired_projects",
        task_id=self.request.id,
    )
    log.info("task_started")
    result = run_async(_close_expired_projects())
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def expire_pending_amendments(self: Any) -> dict[str, int]:
    """Expire stale Proposal Amendments that were not accepted or rejected."""
    log = logger.bind(
        module="projects",
        action="expire_pending_amendments",
        task_id=self.request.id,
    )
    log.info("task_started")
    expired_count = run_async(_expire_pending_amendments())
    result = {"expired_count": expired_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def auto_approve_deliverables(self: Any) -> dict[str, int]:
    """Auto-approve overdue submitted Deliverables and release escrow."""
    log = logger.bind(
        module="projects",
        action="auto_approve_deliverables",
        task_id=self.request.id,
    )
    log.info("task_started")
    auto_approved_count = run_async(_auto_approve_deliverables())
    result = {"auto_approved_count": auto_approved_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def auto_close_delivered_projects(self: Any) -> dict[str, int]:
    """Close delivered Projects after their archive delay expires."""
    log = logger.bind(
        module="projects",
        action="auto_close_delivered_projects",
        task_id=self.request.id,
    )
    log.info("task_started")
    closed_count = run_async(_auto_close_delivered_projects())
    result = {"closed_count": closed_count}
    log.info("task_completed", result=result)
    return result


@app.task(bind=True)  # type: ignore[untyped-decorator]
def escalate_disputes(self: Any) -> dict[str, int]:
    """Escalate stale open Disputes into admin review."""
    log = logger.bind(
        module="projects",
        action="escalate_disputes",
        task_id=self.request.id,
    )
    log.info("task_started")
    escalated_count = run_async(_escalate_disputes())
    result = {"escalated_count": escalated_count}
    log.info("task_completed", result=result)
    return result
