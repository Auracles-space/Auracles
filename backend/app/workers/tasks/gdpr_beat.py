"""Celery tasks for GDPR data-rights background work."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.integrations import s3
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials.models import PlatformConfig
from app.modules.gdpr import anonymise, deletion_service
from app.modules.gdpr.models import AccountDeletionRequest, DataExportRequest
from app.workers.celery_app import app


async def _generate_data_export_impl(request_id: str) -> dict[str, str]:
    """Generate one GDPR export bundle and update request status."""
    parsed_request_id = UUID(request_id)
    async with async_session_factory() as db:
        async with db.begin():
            export_request = await db.get(
                DataExportRequest,
                parsed_request_id,
                with_for_update=True,
            )
            if export_request is None:
                raise ValueError("Data export request not found.")
            if export_request.status == "ready" and export_request.bundle_key:
                return {
                    "request_id": str(export_request.id),
                    "status": "ready",
                    "bundle_key": export_request.bundle_key,
                }
            if export_request.status not in {"pending", "processing"}:
                raise ValueError("Data export request is not active.")
            export_request.status = "processing"
            export_request_id = export_request.id
            user_id = export_request.user_id

        from app.modules.gdpr import export_service

        bundle = await export_service.build_data_export_bundle(
            db=db,
            user_id=user_id,
        )
        bundle_key = f"gdpr-exports/{user_id}/{export_request_id}.json"
        body = json.dumps(bundle, sort_keys=True).encode("utf-8")
        settings = get_settings()
        s3.storage.upload_bytes(
            settings.s3_reports_bucket,
            bundle_key,
            body,
            "application/json",
        )

        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            export_request = await db.get(
                DataExportRequest,
                parsed_request_id,
                with_for_update=True,
            )
            if export_request is None:
                raise ValueError("Data export request not found.")
            expiry_days = await _data_export_expiry_days(db)
            export_request.status = "ready"
            export_request.bundle_key = bundle_key
            export_request.expires_at = datetime.now(UTC) + timedelta(days=expiry_days)
            export_request.completed_at = datetime.now(UTC)
            export_request.failure_reason = None
            await write_audit(
                db=db,
                actor_id=export_request.user_id,
                action="gdpr_export_ready",
                target_type="data_export_request",
                target_id=export_request.id,
                metadata={"bundle_key": bundle_key},
            )
    return {
        "request_id": str(parsed_request_id),
        "status": "ready",
        "bundle_key": bundle_key,
    }


async def _data_export_expiry_days(db: Any) -> int:
    """Return configured export expiry days with a safe default."""
    value = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "data_export_expiry_days"
        )
    )
    if value is None:
        return 7
    try:
        days = int(value)
    except ValueError:
        return 7
    return min(max(days, 1), 30)


async def _expire_data_exports_impl() -> dict[str, int]:
    """Delete expired export bundles and mark their requests expired."""
    settings = get_settings()
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        due_requests = list(
            (
                await db.execute(
                    select(DataExportRequest).where(
                        DataExportRequest.status == "ready",
                        DataExportRequest.expires_at.is_not(None),
                        DataExportRequest.expires_at <= now,
                    )
                )
            ).scalars().all()
        )
        due_request_ids = [request.id for request in due_requests]
        if not due_request_ids:
            return {"expired_count": 0}
        for export_request in due_requests:
            if export_request.bundle_key:
                s3.storage.delete_object(
                    settings.s3_reports_bucket,
                    export_request.bundle_key,
                )

        if db.in_transaction():
            await db.rollback()

        async with db.begin():
            locked_requests = list(
                (
                    await db.execute(
                        select(DataExportRequest)
                        .where(
                            DataExportRequest.id.in_(due_request_ids)
                        )
                        .with_for_update()
                    )
                ).scalars().all()
            )
            expired_count = 0
            for export_request in locked_requests:
                if (
                    export_request.status != "ready"
                    or export_request.expires_at is None
                    or export_request.expires_at > now
                ):
                    continue
                export_request.status = "expired"
                export_request.bundle_key = None
                expired_count += 1
    return {"expired_count": expired_count}


async def _process_account_deletions_impl(
    *,
    redis: Redis | None = None,
) -> dict[str, int]:
    """Anonymise due scheduled account deletions after a final obligation check."""
    cache = redis or get_redis()
    settings = get_settings()
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        due_requests = list(
            (
                await db.execute(
                    select(AccountDeletionRequest).where(
                        AccountDeletionRequest.status == "scheduled",
                        AccountDeletionRequest.scheduled_for.is_not(None),
                        AccountDeletionRequest.scheduled_for <= now,
                    )
                )
            ).scalars().all()
        )
        processed_count = 0
        skipped_count = 0
        for due_request in due_requests:
            user_id = due_request.user_id
            request_id = due_request.id
            reasons = await deletion_service.collect_blocked_reasons(
                db=db,
                user_id=user_id,
            )
            if reasons:
                skipped_count += 1
                if db.in_transaction():
                    await db.rollback()
                async with db.begin():
                    locked_request = await db.get(
                        AccountDeletionRequest,
                        request_id,
                        with_for_update=True,
                    )
                    if (
                        locked_request is None
                        or locked_request.status != "scheduled"
                    ):
                        continue
                    locked_request.blocked_reasons = [
                        reason.model_dump(mode="json") for reason in reasons
                    ]
                continue

            kyc_keys = await anonymise.collect_kyc_object_keys(db=db, user_id=user_id)
            user = await db.get(User, user_id)
            if user is not None:
                await auth_service.revoke_all_user_sessions(cache, user)
            for key in kyc_keys:
                s3.storage.delete_object(settings.s3_artifacts_bucket, key)

            if db.in_transaction():
                await db.rollback()
            async with db.begin():
                locked_request = await db.get(
                    AccountDeletionRequest,
                    request_id,
                    with_for_update=True,
                )
                if locked_request is None or locked_request.status != "scheduled":
                    continue
                reasons = await deletion_service.collect_blocked_reasons(
                    db=db,
                    user_id=user_id,
                )
                if reasons:
                    locked_request.blocked_reasons = [
                        reason.model_dump(mode="json") for reason in reasons
                    ]
                    skipped_count += 1
                    continue
                await anonymise.anonymise_user_records(
                    db=db,
                    user_id=user_id,
                    request_id=request_id,
                    completed_at=now,
                )
                processed_count += 1
        return {
            "processed_count": processed_count,
            "skipped_count": skipped_count,
        }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def generate_data_export(self: Any, request_id: str) -> dict[str, str]:
    """Generate a private JSON data export bundle for one request."""
    log = logger.bind(
        module="gdpr",
        action="generate_data_export",
        task_id=self.request.id,
        data_export_request_id=request_id,
    )
    log.info("task_started")
    try:
        from app.workers.async_runner import run_async

        result = run_async(_generate_data_export_impl(request_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def expire_data_exports(self: Any) -> dict[str, int]:
    """Expire past-due GDPR export bundles and delete their S3 objects."""
    log = logger.bind(
        module="gdpr",
        action="expire_data_exports",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        from app.workers.async_runner import run_async

        result = run_async(_expire_data_exports_impl())
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def process_account_deletions(self: Any) -> dict[str, int]:
    """Anonymise due scheduled GDPR deletion requests once obligations clear."""
    log = logger.bind(
        module="gdpr",
        action="process_account_deletions",
        task_id=self.request.id,
    )
    log.info("task_started")
    try:
        from app.workers.async_runner import run_async

        result = run_async(_process_account_deletions_impl())
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
