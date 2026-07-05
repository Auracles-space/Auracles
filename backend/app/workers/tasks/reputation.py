"""Reputation recompute Celery tasks (Phase 5e).

``recompute_reputation`` (Beat, daily) recomputes every subject.
``recompute_subject`` recomputes one subject and is reused by the admin manual
trigger. All recompute is idempotent: each run reads current source aggregates
and upserts the resulting score.

Maps to: BR-ATT-005.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.frameworks.models import Framework
from app.modules.reputation import factors
from app.modules.reputation import service as reputation_service
from app.modules.reputation.weights import load_config
from app.workers.async_runner import run_async
from app.workers.celery_app import app

_FACTOR_FN = {
    "framework": factors.framework_factors,
    "contributor": factors.contributor_factors,
    "operator": factors.operator_factors,
    "attestor": factors.attestor_factors,
    "attestor_org": factors.org_attestor_factors,
}


async def recompute_subject(*, subject_type: str, subject_id: UUID) -> None:
    """Recompute and upsert one subject's reputation in its own transaction.

    Args:
        subject_type: One of ``framework``, ``contributor``, ``operator``,
            ``attestor``.
        subject_id: UUID of the subject to score.
    """
    async with async_session_factory() as db:
        async with db.begin():
            cfg = await load_config(db, subject_type=subject_type)
            factor_results = await _FACTOR_FN[subject_type](db, subject_id, cfg)
            result = reputation_service.combine_factors(cfg, factor_results)
            await reputation_service.upsert_score(
                db,
                subject_type=subject_type,
                subject_id=subject_id,
                result=result,
            )
            if subject_type == "attestor":
                from app.modules.attestation.certification_service import (
                    evaluate_attestor_certification,
                )

                await evaluate_attestor_certification(
                    db,
                    attestor_id=subject_id,
                    cfg=cfg,
                )
            elif subject_type == "attestor_org":
                from app.modules.attestation.certification_service import (
                    evaluate_org_attestor_certification,
                )

                await evaluate_org_attestor_certification(
                    db,
                    org_id=subject_id,
                    cfg=cfg,
                )


async def _recompute_all_impl() -> dict[str, int]:
    """Recompute every scorable subject; frameworks first for contributor rollups."""
    from app.modules.attestation.models import AttestorProfile
    from app.modules.auth.models import UserRole
    from app.modules.organizations.models import OrgAttestorProfile

    counts = {
        "framework": 0,
        "contributor": 0,
        "operator": 0,
        "attestor": 0,
        "attestor_org": 0,
    }
    async with async_session_factory() as db:
        framework_ids = (
            (
                await db.execute(
                    select(Framework.id).where(
                        Framework.status.in_(("published", "unpublished", "suspended"))
                    )
                )
            )
            .scalars()
            .all()
        )
        contributor_ids = (
            (
                await db.execute(
                    select(UserRole.user_id).where(UserRole.role == "contributor")
                )
            )
            .scalars()
            .all()
        )
        operator_ids = (
            (
                await db.execute(
                    select(UserRole.user_id).where(UserRole.role == "operator")
                )
            )
            .scalars()
            .all()
        )
        attestor_ids = (
            (
                await db.execute(
                    select(AttestorProfile.user_id).where(
                        AttestorProfile.active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        attestor_org_ids = (
            (
                await db.execute(
                    select(OrgAttestorProfile.org_id).where(
                        OrgAttestorProfile.active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )

    # Frameworks before contributors: contributor framework_performance reads
    # already-computed framework scores.
    for fid in framework_ids:
        await recompute_subject(subject_type="framework", subject_id=fid)
        counts["framework"] += 1
    for cid in set(contributor_ids):
        await recompute_subject(subject_type="contributor", subject_id=cid)
        counts["contributor"] += 1
    for oid in set(operator_ids):
        await recompute_subject(subject_type="operator", subject_id=oid)
        counts["operator"] += 1
    for aid in set(attestor_ids):
        await recompute_subject(subject_type="attestor", subject_id=aid)
        counts["attestor"] += 1
    for org_id in set(attestor_org_ids):
        await recompute_subject(subject_type="attestor_org", subject_id=org_id)
        counts["attestor_org"] += 1
    return counts


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def recompute_reputation(self: Any) -> dict[str, int]:
    """Daily full reputation recompute across all subjects."""
    log = logger.bind(
        module="reputation",
        action="recompute_reputation",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        result = run_async(_recompute_all_impl())
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=300) from exc
    log.info("task_completed", result=result)
    return result


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def recompute_subject_task(
    self: Any, subject_type: str, subject_id: str
) -> dict[str, str]:
    """Queue-safe single-subject recompute used by the admin endpoint."""
    log = logger.bind(
        module="reputation",
        action="recompute_subject",
        task_id=self.request.id,
        subject_type=subject_type,
        subject_id=subject_id,
    )
    log.info("task_started")
    try:
        run_async(
            recompute_subject(subject_type=subject_type, subject_id=UUID(subject_id))
        )
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=300) from exc
    log.info("task_completed")
    return {"status": "completed"}
