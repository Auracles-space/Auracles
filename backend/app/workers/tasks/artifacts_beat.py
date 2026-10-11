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
from sqlalchemy import and_, or_, select, update

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models_artifact import Artifact
from app.workers.celery_app import app

_ARTIFACT_PREFIX = "frameworks/"


async def _reap_stalled_artifacts_impl() -> dict[str, int]:
    """Fail stale processing rows and delete unreferenced S3 objects.

    Two independent self-healing passes:

    1. Lease reaper — flips to ``failed`` any row whose processing cannot
       still be in flight, which is two shapes, not one:

       * ``processing`` past ``artifact_processing_lease_minutes``, measured
         from ``processing_started_at``: a scan worker took the row and then
         crashed.
       * ``pending`` past the same TTL, measured from ``created_at`` because a
         never-started row has no other clock: the row committed but the scan
         was never dispatched at all. ``request_artifact_upload_url`` commits
         the Artifact before the browser uploads anything, so an upload
         abandoned between the presigned POST and the confirm call lands here.

       The second shape used to match nothing, even though this docstring
       claimed to cover a scan that was "never dispatched". The cost was not
       just a stuck row: ``pipeline_gate`` counts ``pending`` as in flight, so
       the Framework stayed at ``processing`` forever and could not be
       published, edited past the gate, or cleared by its owner. One
       production Framework sat frozen for two and a half days before anyone
       connected it to an upload that had quietly failed.
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
                    or_(
                        and_(
                            Artifact.processing_status == "processing",
                            Artifact.processing_started_at.is_not(None),
                            Artifact.processing_started_at < lease_cutoff,
                        ),
                        # A never-started row has no processing_started_at, so
                        # its own age is the only thing that can tell an
                        # abandoned upload from one still in the browser's
                        # hands. Same TTL: both mean "this cannot still be
                        # happening".
                        and_(
                            Artifact.processing_status == "pending",
                            Artifact.processing_started_at.is_(None),
                            Artifact.created_at < lease_cutoff,
                        ),
                    )
                )
                .values(processing_status="failed")
                .returning(Artifact.id)
            )
            reaped = len(result.all())

        # Live keys include BOTH the artifact bytes and the redacted PII-safe
        # review copy (clean_file_key). Both live under the swept frameworks/
        # prefix; omitting clean_file_key would delete every redacted copy.
        key_rows = (
            await db.execute(select(Artifact.file_key, Artifact.clean_file_key))
        ).all()
        live_keys = {row[0] for row in key_rows} | {
            row[1] for row in key_rows if row[1]
        }

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
