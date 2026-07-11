"""Celery tasks for artifact pipeline self-healing.

Reaps rows stuck in ``processing`` past the lease TTL (a crashed or never-run
scan worker would otherwise deadlock re-sync forever) and reconciles orphaned
S3 objects left by a rolled-back upload.

Maps to: spec decisions 5 (lease + reaper) and 6b (orphan sweep + safe
ordering) in the Connectors Phase C self-review notes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models_artifact import Artifact
from app.workers.celery_app import app

_ARTIFACT_PREFIX = "frameworks/"


async def _reap_stalled_artifacts_impl() -> dict[str, int]:
    """Fail stale processing rows and delete unreferenced S3 objects.

    Two independent self-healing passes:

    1. Lease reaper — any ``Artifact`` row still ``processing`` past
       ``artifact_processing_lease_minutes`` is flipped to ``failed``. This
       recovers rows orphaned by a scan worker that crashed or was never
       dispatched, which would otherwise block re-sync forever (BR guard on
       in-flight processing).
    2. Orphan sweep — S3 objects under the artifact prefix with no matching
       ``Artifact.file_key`` are deleted, but only if older than
       ``artifact_orphan_sweep_minutes``. Task 5's upload-then-commit
       ordering means an in-flight upload's bytes can exist in S3 before its
       row commits; the age floor prevents the sweep from deleting a live
       upload still mid-flight. ``source-preview/`` objects are never swept
       here — they have their own lifecycle (deleted on re-sync/detach/
       publish), not an Artifact row.

    Returns:
        Counts of rows reaped and S3 objects swept, for logging/monitoring.
    """
    settings = get_settings()
    lease_cutoff = datetime.now(UTC) - timedelta(
        minutes=settings.artifact_processing_lease_minutes
    )
    async with async_session_factory() as db:
        async with db.begin():
            result = await db.execute(
                update(Artifact)
                .where(
                    Artifact.processing_status == "processing",
                    Artifact.processing_started_at.is_not(None),
                    Artifact.processing_started_at < lease_cutoff,
                )
                .values(processing_status="failed")
                .returning(Artifact.id)
            )
            reaped = len(result.all())

        live_keys = set(
            (await db.execute(select(Artifact.file_key))).scalars().all()
        )

    sweep_cutoff = datetime.now(UTC) - timedelta(
        minutes=settings.artifact_orphan_sweep_minutes
    )
    swept = 0
    for last_modified, key in s3.storage.list_keys(
        settings.s3_artifacts_bucket, _ARTIFACT_PREFIX
    ):
        # source-preview cache has its own lifecycle — never treat as an orphan.
        if "/source-preview/" in key:
            continue
        # Upload-then-commit means an in-flight upload's bytes exist in S3 before
        # its row commits; the age floor protects those from a false-orphan delete.
        if last_modified >= sweep_cutoff:
            continue
        if key not in live_keys:
            s3.storage.delete_object(settings.s3_artifacts_bucket, key)
            swept += 1

    logger.bind(module="artifacts", action="reap_stalled_artifacts").info(
        "artifact_reap_complete", reaped=reaped, swept=swept
    )
    return {"reaped": reaped, "swept": swept}


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def reap_stalled_artifacts(self: Any) -> dict[str, int]:
    """Fail stalled artifact processing and reconcile orphaned S3 objects."""
    log = logger.bind(
        module="artifacts", action="reap_stalled_artifacts", task_id=self.request.id
    )
    log.info("task_started")
    try:
        from app.workers.async_runner import run_async

        return run_async(_reap_stalled_artifacts_impl())
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
