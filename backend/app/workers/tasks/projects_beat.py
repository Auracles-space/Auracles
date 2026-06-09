"""Scheduled Project maintenance tasks for Phase 4a."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.database import async_session_factory
from app.modules.projects.models import Project, Proposal
from app.workers.async_runner import run_async
from app.workers.celery_app import app


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
