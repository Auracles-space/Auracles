"""Admin service logic.

Handles platform configuration, moderation overrides, escrow overrides, and
admin analytics read models for the Auracles back office, including the daily
snapshot aggregates that back dashboard trend charts and exports.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.admin.models import AnalyticsDailySnapshot
from app.modules.attestation.models import Attestation, AttestationDispute
from app.modules.auth import service as auth_service
from app.modules.auth.models import KycDocument, User, UserRole
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import Artifact, ArtifactRarityAudit
from app.modules.frameworks.pipeline_gate import (
    NEAR_DUPLICATE_JACCARD_THRESHOLD,
    evaluate_framework_pipeline,
)
from app.modules.projects.models import Dispute
from app.shared.models.audit_log import AuditLog
from app.workers.tasks.processing.minhash_index import (
    remove_framework_artifacts_from_index,
)

EDITABLE_PLATFORM_CONFIG_KEYS = {
    "commission_rate",
    "min_payout_usd",
    "refund_window_hours",
    "attestation_fee_framework",
    "attestation_fee_contributor",
    "attestation_fee_operator",
    "attestation_fee_credential",
    "attestation_cohort_size",
    "attestation_completion_sla_days_framework",
    "attestation_completion_sla_days_contributor",
    "attestation_completion_sla_days_operator",
    "attestation_completion_sla_days_credential",
    "attestation_offer_accept_hours",
    "attestation_dispute_window_days",
    "saved_search_alert_cadence_hours",
    "consent_version_terms_of_service",
    "consent_version_privacy_policy",
    "account_deletion_grace_days",
    "data_export_expiry_days",
}
COMMISSION_RATE_MAX = Decimal("0.50")
MIN_PAYOUT_USD_MIN = Decimal("1.00")
MIN_PAYOUT_USD_MAX = Decimal("100000.00")
REFUND_WINDOW_HOURS_MIN = 0
REFUND_WINDOW_HOURS_MAX = 720
SAVED_SEARCH_ALERT_CADENCE_HOURS_MIN = 1
SAVED_SEARCH_ALERT_CADENCE_HOURS_MAX = 168
GDPR_RETENTION_DAYS_MIN = 1
GDPR_RETENTION_DAYS_MAX = 30
CONSENT_VERSION_KEYS = {
    "consent_version_terms_of_service",
    "consent_version_privacy_policy",
}
GDPR_RETENTION_DAY_KEYS = {
    "account_deletion_grace_days",
    "data_export_expiry_days",
}
ATTESTATION_FEE_RANGES = {
    "attestation_fee_framework": (Decimal("25.00"), Decimal("100000.00")),
    "attestation_fee_contributor": (Decimal("25.00"), Decimal("100000.00")),
    "attestation_fee_operator": (Decimal("25.00"), Decimal("100000.00")),
    "attestation_fee_credential": (Decimal("10.00"), Decimal("100000.00")),
}
ATTESTATION_INTEGER_RANGES = {
    "attestation_cohort_size": (1, 10),
    "attestation_completion_sla_days_framework": (1, 30),
    "attestation_completion_sla_days_contributor": (1, 30),
    "attestation_completion_sla_days_operator": (1, 30),
    "attestation_completion_sla_days_credential": (1, 30),
    "attestation_offer_accept_hours": (1, 168),
    "attestation_dispute_window_days": (1, 30),
}
GMV_SOURCE_KEYS = (
    "framework_purchase",
    "collection_purchase",
    "project_milestone",
    "attestation_fee",
)
ACTIVE_DISPUTE_STATUSES = ("open", "under_review")
ATTESTATION_ISSUED_STATUSES = ("report_submitted", "closed")


def _money(value: Decimal | str | int | None) -> Decimal:
    """Normalize nullable money-like values to a two-decimal Decimal."""
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


def _money_string(value: Decimal | str | int | None) -> str:
    """Serialize a money value as a plain string for API responses."""
    return format(_money(value), ".2f")


def _empty_gmv_sources() -> dict[str, Decimal]:
    """Return a zeroed GMV source breakdown."""
    return {key: Decimal("0.00") for key in GMV_SOURCE_KEYS}


def _transaction_source_key(transaction: Transaction) -> str | None:
    """Map a transaction row to one analytics GMV source bucket."""
    if transaction.transaction_type == "purchase":
        if transaction.ref_type == "collection":
            return "collection_purchase"
        return "framework_purchase"
    if (
        transaction.transaction_type == "milestone"
        and transaction.ref_type == "project_milestone"
    ):
        return "project_milestone"
    if (
        transaction.transaction_type == "attestation_fee"
        and transaction.ref_type == "attestation"
    ):
        return "attestation_fee"
    return None


def _serialize_gmv_sources(values: dict[str, Decimal]) -> dict[str, str]:
    """Convert a Decimal GMV source map into string-valued API output."""
    return {key: _money_string(values[key]) for key in GMV_SOURCE_KEYS}


async def _list_gmv_transactions(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
) -> list[Transaction]:
    """Return completed USD marketplace transactions within a time range."""
    filters = [
        Transaction.currency == "USD",
        Transaction.status == "completed",
        Transaction.transaction_type.in_(("purchase", "milestone", "attestation_fee")),
        Transaction.created_at >= since,
    ]
    if until is not None:
        filters.append(Transaction.created_at < until)
    result = await db.execute(select(Transaction).where(*filters))
    return list(result.scalars().all())


def _sum_gmv_sources(transactions: list[Transaction]) -> dict[str, Decimal]:
    """Aggregate qualifying transactions into admin GMV source buckets."""
    sources = _empty_gmv_sources()
    for transaction in transactions:
        source_key = _transaction_source_key(transaction)
        if source_key is None:
            continue
        sources[source_key] += _money(transaction.amount)
    return sources


async def _count_distinct_audit_actors(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
) -> int:
    """Count distinct authenticated actors seen in audit logs within a window."""
    filters = [
        AuditLog.actor_id.is_not(None),
        AuditLog.created_at >= since,
    ]
    if until is not None:
        filters.append(AuditLog.created_at < until)
    result = await db.scalar(
        select(func.count(func.distinct(AuditLog.actor_id))).where(
            *filters,
        )
    )
    return int(result or 0)


async def _count_users_created_since(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
) -> int:
    """Count user registrations created within the given window."""
    filters = [User.created_at >= since]
    if until is not None:
        filters.append(User.created_at < until)
    result = await db.scalar(select(func.count(User.id)).where(*filters))
    return int(result or 0)


async def _count_published_frameworks_total(db: AsyncSession) -> int:
    """Count currently published Frameworks."""
    result = await db.scalar(
        select(func.count(Framework.id)).where(Framework.status == "published")
    )
    return int(result or 0)


async def _count_published_frameworks_since(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
) -> int:
    """Count Frameworks published within the given window."""
    filters = [
        Framework.status == "published",
        Framework.published_at.is_not(None),
        Framework.published_at >= since,
    ]
    if until is not None:
        filters.append(Framework.published_at < until)
    result = await db.scalar(
        select(func.count(Framework.id)).where(*filters)
    )
    return int(result or 0)


async def _count_attestations_issued_since(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
) -> int:
    """Count Attestations issued within the given window."""
    issued_at_expr = func.coalesce(
        Attestation.issued_at,
        Attestation.closed_at,
        Attestation.created_at,
    )
    filters = [
        Attestation.status.in_(ATTESTATION_ISSUED_STATUSES),
        Attestation.outcome.is_not(None),
        issued_at_expr >= since,
    ]
    if until is not None:
        filters.append(issued_at_expr < until)
    result = await db.scalar(
        select(func.count(Attestation.id)).where(*filters)
    )
    return int(result or 0)


async def _count_open_project_disputes(db: AsyncSession) -> int:
    """Count currently open or under-review Project disputes."""
    result = await db.scalar(
        select(func.count(Dispute.id)).where(Dispute.status.in_(ACTIVE_DISPUTE_STATUSES))
    )
    return int(result or 0)


async def _count_open_attestation_disputes(db: AsyncSession) -> int:
    """Count currently open or under-review Attestation disputes."""
    result = await db.scalar(
        select(func.count(AttestationDispute.id)).where(
            AttestationDispute.status.in_(ACTIVE_DISPUTE_STATUSES)
        )
    )
    return int(result or 0)


async def compute_daily_snapshot_payload(
    db: AsyncSession,
    *,
    snapshot_date: date,
) -> dict[str, object]:
    """Compute one frozen UTC daily analytics snapshot payload."""
    day_start = datetime(
        snapshot_date.year,
        snapshot_date.month,
        snapshot_date.day,
        tzinfo=UTC,
    )
    day_end = day_start + timedelta(days=1)
    gmv_sources = _sum_gmv_sources(
        await _list_gmv_transactions(
            db,
            since=day_start,
            until=day_end,
        )
    )
    project_disputes = await _count_open_project_disputes(db)
    attestation_disputes = await _count_open_attestation_disputes(db)
    return {
        "snapshot_date": snapshot_date,
        "gmv_total": _money(sum(gmv_sources.values(), Decimal("0.00"))),
        "gmv_by_source": _serialize_gmv_sources(gmv_sources),
        "active_users": await _count_distinct_audit_actors(
            db,
            since=day_start,
            until=day_end,
        ),
        "new_registrations": await _count_users_created_since(
            db,
            since=day_start,
            until=day_end,
        ),
        "frameworks_published": await _count_published_frameworks_since(
            db,
            since=day_start,
            until=day_end,
        ),
        "attestations_issued": await _count_attestations_issued_since(
            db,
            since=day_start,
            until=day_end,
        ),
        "disputes_open": project_disputes + attestation_disputes,
    }


async def list_dashboard_trend(
    db: AsyncSession,
    *,
    limit: int = 30,
) -> list[AnalyticsDailySnapshot]:
    """Return frozen daily snapshot rows ordered oldest to newest."""
    result = await db.execute(
        select(AnalyticsDailySnapshot)
        .order_by(desc(AnalyticsDailySnapshot.snapshot_date))
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return rows


async def get_dashboard_analytics(db: AsyncSession) -> dict[str, object]:
    """Return current-state analytics plus frozen trend rows for the admin dashboard."""
    now = datetime.now(UTC)
    today_since = now - timedelta(days=1)
    seven_day_since = now - timedelta(days=7)
    thirty_day_since = now - timedelta(days=30)

    qualifying_transactions = await _list_gmv_transactions(
        db,
        since=thirty_day_since,
    )

    today_sources = _empty_gmv_sources()
    seven_day_sources = _empty_gmv_sources()
    thirty_day_sources = _empty_gmv_sources()
    for transaction in qualifying_transactions:
        source_key = _transaction_source_key(transaction)
        if source_key is None:
            continue
        amount = _money(transaction.amount)
        if transaction.created_at >= thirty_day_since:
            thirty_day_sources[source_key] += amount
        if transaction.created_at >= seven_day_since:
            seven_day_sources[source_key] += amount
        if transaction.created_at >= today_since:
            today_sources[source_key] += amount

    active_last_24h = await _count_distinct_audit_actors(db, since=today_since)
    active_last_7d = await _count_distinct_audit_actors(db, since=seven_day_since)
    active_last_30d = await _count_distinct_audit_actors(db, since=thirty_day_since)

    registrations_last_24h = await _count_users_created_since(db, since=today_since)
    registrations_last_7d = await _count_users_created_since(db, since=seven_day_since)
    registrations_last_30d = await _count_users_created_since(
        db,
        since=thirty_day_since,
    )

    published_total = await _count_published_frameworks_total(db)
    published_last_24h = await _count_published_frameworks_since(
        db,
        since=today_since,
    )
    published_last_7d = await _count_published_frameworks_since(
        db,
        since=seven_day_since,
    )
    published_last_30d = await _count_published_frameworks_since(
        db,
        since=thirty_day_since,
    )

    attestations_last_24h = await _count_attestations_issued_since(
        db,
        since=today_since,
    )
    attestations_last_7d = await _count_attestations_issued_since(
        db,
        since=seven_day_since,
    )
    attestations_last_30d = await _count_attestations_issued_since(
        db,
        since=thirty_day_since,
    )

    project_disputes = await _count_open_project_disputes(db)
    attestation_disputes = await _count_open_attestation_disputes(db)
    trend_rows = await list_dashboard_trend(db=db)

    return {
        "gmv": {
            "today_total": _money_string(sum(today_sources.values(), Decimal("0.00"))),
            "last_7_days_total": _money_string(
                sum(seven_day_sources.values(), Decimal("0.00"))
            ),
            "last_30_days_total": _money_string(
                sum(thirty_day_sources.values(), Decimal("0.00"))
            ),
            "today_by_source": _serialize_gmv_sources(today_sources),
            "last_7_days_by_source": _serialize_gmv_sources(seven_day_sources),
            "last_30_days_by_source": _serialize_gmv_sources(thirty_day_sources),
        },
        "active_users": {
            "last_24_hours": active_last_24h,
            "last_7_days": active_last_7d,
            "last_30_days": active_last_30d,
        },
        "new_registrations": {
            "last_24_hours": registrations_last_24h,
            "last_7_days": registrations_last_7d,
            "last_30_days": registrations_last_30d,
        },
        "frameworks_published": {
            "total": published_total,
            "last_24_hours": published_last_24h,
            "last_7_days": published_last_7d,
            "last_30_days": published_last_30d,
        },
        "attestations_issued": {
            "last_24_hours": attestations_last_24h,
            "last_7_days": attestations_last_7d,
            "last_30_days": attestations_last_30d,
        },
        "disputes_open": {
            "total": project_disputes + attestation_disputes,
            "projects": project_disputes,
            "attestations": attestation_disputes,
        },
        "trend": [
            {
                "snapshot_date": row.snapshot_date,
                "gmv_total": _money_string(row.gmv_total),
                "active_users": row.active_users,
                "new_registrations": row.new_registrations,
                "frameworks_published": row.frameworks_published,
                "attestations_issued": row.attestations_issued,
                "disputes_open": row.disputes_open,
            }
            for row in trend_rows
        ],
    }


async def assign_user_role(
    db: AsyncSession,
    admin: User,
    target_user_id: UUID,
    role: str,
) -> UserRole:
    """Assign a user role, approving Attestor when an admin performs it."""
    target = await db.scalar(select(User).where(User.id == target_user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    existing = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == target_user_id,
            UserRole.role == role,
        )
    )
    if existing is None:
        existing = UserRole(user_id=target_user_id, role=role)
        db.add(existing)

    existing.approved_at = datetime.now(UTC)
    existing.approved_by = admin.id
    action = "attestor_approved" if role == "attestor" else "role_assigned"
    await write_audit(
        db=db,
        actor_id=admin.id,
        action=action,
        target_type="user",
        target_id=target_user_id,
        metadata={"role": role},
    )
    await db.commit()
    return existing


async def review_user_kyc(
    db: AsyncSession,
    admin: User,
    target_user_id: UUID,
    review_status: str,
    notes: str | None,
) -> KycDocument:
    """Review the latest KYC document and update the user's KYC status."""
    target = await db.scalar(select(User).where(User.id == target_user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    document = await db.scalar(
        select(KycDocument)
        .where(KycDocument.user_id == target_user_id)
        .order_by(desc(KycDocument.created_at))
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC document not found.",
        )

    document.status = review_status
    document.reviewed_by = admin.id
    document.reviewed_at = datetime.now(UTC)
    document.notes = notes
    target.kyc_status = review_status
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="kyc_status_change",
        target_type="user",
        target_id=target_user_id,
        metadata={"status": review_status, "document_id": str(document.id)},
    )
    await db.commit()
    return document


async def suspend_framework(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
    reason: str,
) -> Framework:
    """Suspend a published Framework after admin moderation review."""
    framework = await db.scalar(select(Framework).where(Framework.id == framework_id))
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    if framework.status == "suspended":
        return framework
    if framework.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only published Frameworks can be suspended.",
        )

    framework.status = "suspended"
    framework.rejection_reason = reason.strip()
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="framework_suspended",
        target_type="framework",
        target_id=framework.id,
        metadata={"reason": framework.rejection_reason},
    )
    await db.commit()
    try:
        await remove_framework_artifacts_from_index(framework.id)
    except Exception as exc:
        logger.bind(
            module="admin",
            action="remove_framework_from_lsh",
            user_id=admin.id,
            framework_id=framework.id,
        ).error("artifact_lsh_remove_failed", error=str(exc))
    return framework


async def override_rarity_block(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
    reason: str,
) -> Framework:
    """Override near-duplicate rarity hard blocks for one Framework."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await db.scalar(
            select(Framework).where(Framework.id == framework_id)
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        artifact_rows = (
            await db.execute(
                select(Artifact, ArtifactRarityAudit)
                .join(
                    ArtifactRarityAudit,
                    ArtifactRarityAudit.artifact_id == Artifact.id,
                )
                .where(
                    Artifact.framework_id == framework.id,
                    Artifact.current_for_framework.is_(True),
                    ArtifactRarityAudit.internal_jaccard
                    >= NEAR_DUPLICATE_JACCARD_THRESHOLD,
                    ArtifactRarityAudit.near_duplicate_overridden_at.is_(None),
                )
            )
        ).all()
        if not artifact_rows:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Framework has no active near-duplicate rarity block.",
            )
        now = datetime.now(UTC)
        normalized_reason = reason.strip()
        overridden_artifact_ids: list[str] = []
        for artifact, audit in artifact_rows:
            audit.near_duplicate_overridden_at = now
            audit.near_duplicate_overridden_by = admin_id
            audit.near_duplicate_override_reason = normalized_reason
            overridden_artifact_ids.append(str(artifact.id))
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="rarity_block_overridden",
            target_type="framework",
            target_id=framework.id,
            metadata={
                "artifact_ids": overridden_artifact_ids,
                "reason": normalized_reason,
            },
        )
        await evaluate_framework_pipeline(db, framework, force=True)
    await db.refresh(framework)
    logger.bind(
        module="admin",
        action="override_rarity_block",
        user_id=admin_id,
        framework_id=framework.id,
    ).info("rarity_block_overridden")
    return framework


async def grant_license(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
    operator_id: UUID,
    license_type: str,
    expires_at: datetime | None,
    seats_total: int | None,
) -> License:
    """Grant an Operator license to a Framework for Phase 2 admin flows."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await db.scalar(
            select(Framework).where(Framework.id == framework_id)
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        operator = await db.scalar(select(User).where(User.id == operator_id))
        if operator is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Operator not found.",
            )
        existing = await db.scalar(
            select(License).where(
                License.framework_id == framework_id,
                License.operator_id == operator_id,
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operator already has a license for this Framework.",
            )

        resolved_seats_total = seats_total
        if license_type == "team" and resolved_seats_total is None:
            resolved_seats_total = 10
        license_row = License(
            framework_id=framework.id,
            operator_id=operator.id,
            license_type=license_type,
            status="active",
            version_at_grant=framework.version,
            expires_at=expires_at,
            seats_used=1,
            seats_total=resolved_seats_total,
        )
        db.add(license_row)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="license_granted",
            target_type="license",
            target_id=license_row.id,
            metadata={
                "framework_id": str(framework.id),
                "operator_id": str(operator.id),
                "version_at_grant": framework.version,
                "type": license_type,
            },
        )
    return license_row


async def list_platform_config(db: AsyncSession) -> list[PlatformConfig]:
    """Return platform financial configuration rows in stable key order."""
    result = await db.execute(select(PlatformConfig).order_by(PlatformConfig.key))
    return list(result.scalars().all())


def _format_decimal_config(value: Decimal) -> str:
    """Return a stable plain-string representation for decimal config values."""
    return format(value.normalize(), "f")


def _parse_decimal_config(key: str, raw_value: str) -> Decimal:
    """Parse a decimal admin config value or raise a 422 API error."""
    try:
        return Decimal(raw_value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{key} must be a valid decimal number.",
        ) from exc


def _parse_integer_config(key: str, raw_value: str) -> int:
    """Parse a whole-number admin config value or raise a 422 API error."""
    try:
        return int(raw_value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{key} must be a whole number.",
        ) from exc


def _normalise_platform_config_value(key: str, raw_value: str) -> str:
    """Validate and normalize an editable platform config value."""
    if key == "commission_rate":
        value = _parse_decimal_config(key, raw_value)
        if value < Decimal("0") or value > COMMISSION_RATE_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="commission_rate must be between 0 and 0.50.",
            )
        return _format_decimal_config(value.quantize(Decimal("0.0001")))

    if key == "min_payout_usd":
        value = _parse_decimal_config(key, raw_value)
        if value < MIN_PAYOUT_USD_MIN or value > MIN_PAYOUT_USD_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="min_payout_usd must be between 1.00 and 100000.00.",
            )
        return _format_decimal_config(value.quantize(Decimal("0.01")))

    if key == "refund_window_hours":
        try:
            hours = int(raw_value.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="refund_window_hours must be a whole number.",
            ) from exc
        if hours < REFUND_WINDOW_HOURS_MIN or hours > REFUND_WINDOW_HOURS_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="refund_window_hours must be between 0 and 720.",
            )
        return str(hours)

    if key in ATTESTATION_FEE_RANGES:
        value = _parse_decimal_config(key, raw_value)
        minimum, maximum = ATTESTATION_FEE_RANGES[key]
        if value < minimum or value > maximum:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} must be between {minimum} and {maximum}.",
            )
        return _format_decimal_config(value.quantize(Decimal("0.01")))

    if key in ATTESTATION_INTEGER_RANGES:
        integer_value = _parse_integer_config(key, raw_value)
        integer_minimum, integer_maximum = ATTESTATION_INTEGER_RANGES[key]
        if integer_value < integer_minimum or integer_value > integer_maximum:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"{key} must be between "
                    f"{integer_minimum} and {integer_maximum}."
                ),
            )
        return str(integer_value)

    if key == "saved_search_alert_cadence_hours":
        hours = _parse_integer_config(key, raw_value)
        if (
            hours < SAVED_SEARCH_ALERT_CADENCE_HOURS_MIN
            or hours > SAVED_SEARCH_ALERT_CADENCE_HOURS_MAX
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="saved_search_alert_cadence_hours must be between 1 and 168.",
            )
        return str(hours)

    if key in CONSENT_VERSION_KEYS:
        version = raw_value.strip()
        if not version:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} must not be empty.",
            )
        return version

    if key in GDPR_RETENTION_DAY_KEYS:
        days = _parse_integer_config(key, raw_value)
        if days < GDPR_RETENTION_DAYS_MIN or days > GDPR_RETENTION_DAYS_MAX:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} must be between 1 and 30.",
            )
        return str(days)

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"{key} is not editable.",
    )


async def update_platform_config(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    updates: list[tuple[str, str]],
    reason: str,
    totp_code: str,
) -> list[PlatformConfig]:
    """Apply audited admin platform configuration changes."""
    admin_id = admin.id
    seen_keys: set[str] = set()
    normalised_updates: list[tuple[str, str]] = []
    for key, raw_value in updates:
        if key in seen_keys:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} can only be updated once per request.",
            )
        seen_keys.add(key)
        normalised_updates.append(
            (key, _normalise_platform_config_value(key, raw_value))
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _verify_admin_2fa(
            db=db,
            redis=redis,
            admin_id=admin_id,
            totp_code=totp_code,
        )
        for key, value in normalised_updates:
            config = await db.get(PlatformConfig, key)
            if config is None:
                config = PlatformConfig(key=key, value=value, updated_by=admin_id)
                db.add(config)
                old_value = None
            else:
                old_value = config.value
                config.value = value
                config.updated_by = admin_id
                config.updated_at = datetime.now(UTC)

            if old_value != value:
                await write_audit(
                    db=db,
                    actor_id=admin_id,
                    action="platform_config_updated",
                    target_type="platform_config",
                    metadata={
                        "key": key,
                        "old_value": old_value,
                        "new_value": value,
                        "reason": reason.strip(),
                    },
                )

    return await list_platform_config(db)


async def _verify_admin_2fa(
    db: AsyncSession,
    redis: Redis,
    admin_id: UUID,
    totp_code: str,
) -> None:
    """Require a valid admin TOTP or backup code before sensitive admin writes."""
    admin = await db.get(User, admin_id, with_for_update=True)
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        )
    await auth_service.verify_totp_for_sensitive_action(
        db=db,
        redis=redis,
        user=admin,
        code=totp_code,
    )


async def release_escrow_override(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    escrow_id: UUID,
    reason: str,
    totp_code: str,
) -> Escrow:
    """Release held escrow funds through an audited admin override."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _verify_admin_2fa(
            db=db,
            redis=redis,
            admin_id=admin_id,
            totp_code=totp_code,
        )
        escrow = await escrow_service.release(
            db,
            escrow_id=escrow_id,
            actor_id=admin_id,
            reason=reason,
            admin_override=True,
        )
    return escrow


async def refund_escrow_override(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    escrow_id: UUID,
    reason: str,
    totp_code: str,
) -> Escrow:
    """Refund held escrow funds through an audited admin override."""
    admin_id = admin.id

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _verify_admin_2fa(
            db=db,
            redis=redis,
            admin_id=admin_id,
            totp_code=totp_code,
        )
        escrow = await db.get(Escrow, escrow_id, with_for_update=True)
        if escrow is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escrow not found.",
            )
        if escrow.status == "refunded":
            return escrow
        if escrow.status == "released":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Released escrow cannot be refunded.",
            )
        transaction = await db.get(
            Transaction,
            escrow.transaction_id,
            with_for_update=True,
        )
        if transaction is None or transaction.provider_ref is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Escrow funding transaction is missing provider metadata.",
            )
        if transaction.provider != "stripe":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Unsupported escrow payment provider.",
            )
        try:
            await stripe.create_refund(
                payment_intent_id=transaction.provider_ref,
                amount=transaction.amount,
                currency=transaction.currency,
                idempotency_key=f"escrow_refund:{escrow_id}",
            )
        except StripeProviderError as exc:
            logger.bind(
                module="admin",
                action="refund_escrow_override",
                user_id=admin_id,
                escrow_id=escrow_id,
            ).error("stripe_escrow_refund_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payment provider is unavailable.",
            ) from exc
        escrow = await escrow_service.refund(
            db,
            escrow_id=escrow_id,
            actor_id=admin_id,
            reason=reason,
            admin_override=True,
        )
    return escrow
