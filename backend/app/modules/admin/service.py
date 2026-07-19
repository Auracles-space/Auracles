"""Admin service logic.

Handles platform configuration, moderation overrides, escrow overrides, and
admin analytics read models for the Auracles back office, including the daily
snapshot aggregates that back dashboard trend charts and exports.
"""

import csv
import io
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict, cast
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import ColumnElement, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.admin.models import AnalyticsDailySnapshot
from app.modules.attestation.models import Attestation, AttestationDispute
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import ApiKey, DeveloperAccount
from app.modules.financials import escrow_service
from app.modules.financials.models import (
    Escrow,
    Payout,
    PayoutAccount,
    PlatformConfig,
    Transaction,
)
from app.modules.frameworks.models import Framework, License
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.modules.frameworks.pipeline_gate import (
    NEAR_DUPLICATE_JACCARD_THRESHOLD,
    evaluate_framework_pipeline,
)
from app.modules.frameworks.service import current_artifacts_block_publish
from app.modules.notifications.service import create_notification
from app.modules.projects.models import Dispute
from app.modules.reputation import weights as reputation_weights
from app.shared.models.audit_log import AuditLog
from app.workers.tasks.processing.minhash_index import (
    index_framework_artifacts,
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
    "attestation_dispute_window_business_days",
    "saved_search_alert_cadence_hours",
    "consent_version_terms_of_service",
    "consent_version_privacy_policy",
    "account_deletion_grace_days",
    "data_export_expiry_days",
    "reputation_weights_framework",
    "reputation_weights_contributor",
    "reputation_weights_operator",
    "reputation_weights_attestor",
    "reputation_min_activity_framework",
    "reputation_min_activity_contributor",
    "reputation_min_activity_operator",
    "reputation_prior",
    "reputation_prior_strength_k",
    "reputation_dispute_penalty",
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
REPUTATION_WEIGHT_KEYS = {
    "reputation_weights_framework",
    "reputation_weights_contributor",
    "reputation_weights_operator",
    "reputation_weights_attestor",
}
REPUTATION_MIN_ACTIVITY_KEYS = {
    "reputation_min_activity_framework",
    "reputation_min_activity_contributor",
    "reputation_min_activity_operator",
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
    "attestation_dispute_window_business_days": (1, 30),
}
GMV_SOURCE_KEYS = (
    "framework_purchase",
    "collection_purchase",
    "project_milestone",
    "attestation_fee",
)
ACTIVE_DISPUTE_STATUSES = ("open", "under_review")
ATTESTATION_ISSUED_STATUSES = ("report_submitted", "closed")
MODERATION_QUEUE_TYPES = ("rarity_review", "near_duplicate_block", "pii_review")
MODERATION_QUEUE_SORT_PRIORITY = {
    "pii_review": 0,
    "near_duplicate_block": 1,
    "rarity_review": 2,
}
ADMIN_USER_DIRECTORY_STATUSES = ("all", "active", "suspended", "kyc_pending")
ADMIN_PAYOUT_STATUSES = ("all", "pending", "processing", "completed", "failed")
ADMIN_PAYOUT_PROVIDERS = ("all", "stripe", "paystack")


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
    result = await db.scalar(select(func.count(Framework.id)).where(*filters))
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
    result = await db.scalar(select(func.count(Attestation.id)).where(*filters))
    return int(result or 0)


async def _count_open_project_disputes(db: AsyncSession) -> int:
    """Count currently open or under-review Project disputes."""
    result = await db.scalar(
        select(func.count(Dispute.id)).where(
            Dispute.status.in_(ACTIVE_DISPUTE_STATUSES)
        )
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


class DailySnapshotPayload(TypedDict):
    """Typed daily analytics snapshot, so consumers get real field types."""

    snapshot_date: date
    gmv_total: Decimal
    gmv_by_source: dict[str, str]
    active_users: int
    new_registrations: int
    frameworks_published: int
    attestations_issued: int
    disputes_open: int


async def compute_daily_snapshot_payload(
    db: AsyncSession,
    *,
    snapshot_date: date,
) -> DailySnapshotPayload:
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


async def list_snapshot_history(
    db: AsyncSession,
    *,
    from_date: date,
    to_date: date,
) -> list[AnalyticsDailySnapshot]:
    """Return frozen snapshot rows for an inclusive UTC date range."""
    result = await db.execute(
        select(AnalyticsDailySnapshot)
        .where(
            AnalyticsDailySnapshot.snapshot_date >= from_date,
            AnalyticsDailySnapshot.snapshot_date <= to_date,
        )
        .order_by(AnalyticsDailySnapshot.snapshot_date)
    )
    return list(result.scalars().all())


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


def _csv_row(
    *,
    row_type: str,
    snapshot_date: str = "",
    window: str = "",
    gmv_total: str = "",
    gmv_framework_purchase: str = "",
    gmv_collection_purchase: str = "",
    gmv_project_milestone: str = "",
    gmv_attestation_fee: str = "",
    active_users: str = "",
    new_registrations: str = "",
    frameworks_published: str = "",
    frameworks_published_total: str = "",
    attestations_issued: str = "",
    disputes_open_total: str = "",
    disputes_open_projects: str = "",
    disputes_open_attestations: str = "",
    computed_at: str = "",
) -> dict[str, str]:
    """Build one flat admin analytics CSV row."""
    return {
        "row_type": row_type,
        "snapshot_date": snapshot_date,
        "window": window,
        "gmv_total": gmv_total,
        "gmv_framework_purchase": gmv_framework_purchase,
        "gmv_collection_purchase": gmv_collection_purchase,
        "gmv_project_milestone": gmv_project_milestone,
        "gmv_attestation_fee": gmv_attestation_fee,
        "active_users": active_users,
        "new_registrations": new_registrations,
        "frameworks_published": frameworks_published,
        "frameworks_published_total": frameworks_published_total,
        "attestations_issued": attestations_issued,
        "disputes_open_total": disputes_open_total,
        "disputes_open_projects": disputes_open_projects,
        "disputes_open_attestations": disputes_open_attestations,
        "computed_at": computed_at,
    }


def _serialize_snapshot_csv_row(snapshot: AnalyticsDailySnapshot) -> dict[str, str]:
    """Convert one frozen snapshot row into the flat CSV contract."""
    return _csv_row(
        row_type="snapshot",
        snapshot_date=snapshot.snapshot_date.isoformat(),
        gmv_total=_money_string(snapshot.gmv_total),
        gmv_framework_purchase=str(
            snapshot.gmv_by_source.get("framework_purchase", "0.00")
        ),
        gmv_collection_purchase=str(
            snapshot.gmv_by_source.get("collection_purchase", "0.00")
        ),
        gmv_project_milestone=str(
            snapshot.gmv_by_source.get("project_milestone", "0.00")
        ),
        gmv_attestation_fee=str(snapshot.gmv_by_source.get("attestation_fee", "0.00")),
        active_users=str(snapshot.active_users),
        new_registrations=str(snapshot.new_registrations),
        frameworks_published=str(snapshot.frameworks_published),
        attestations_issued=str(snapshot.attestations_issued),
        disputes_open_total=str(snapshot.disputes_open),
        computed_at=snapshot.computed_at.isoformat(),
    )


def _serialize_window_csv_row(
    dashboard: dict[str, object],
    *,
    window: str,
    gmv_total_key: str,
    gmv_sources_key: str,
    active_users_key: str,
    registrations_key: str,
    frameworks_key: str,
    attestations_key: str,
) -> dict[str, str]:
    """Convert one live dashboard window into the flat CSV contract."""
    # The live dashboard is a nested dynamic mapping; cast each window section.
    gmv = cast("dict[str, Any]", dashboard["gmv"])
    active_users = cast("dict[str, Any]", dashboard["active_users"])
    registrations = cast("dict[str, Any]", dashboard["new_registrations"])
    frameworks = cast("dict[str, Any]", dashboard["frameworks_published"])
    attestations = cast("dict[str, Any]", dashboard["attestations_issued"])
    by_source = cast("dict[str, Any]", gmv[gmv_sources_key])
    return _csv_row(
        row_type="current_window",
        window=window,
        gmv_total=str(gmv[gmv_total_key]),
        gmv_framework_purchase=str(by_source["framework_purchase"]),
        gmv_collection_purchase=str(by_source["collection_purchase"]),
        gmv_project_milestone=str(by_source["project_milestone"]),
        gmv_attestation_fee=str(by_source["attestation_fee"]),
        active_users=str(active_users[active_users_key]),
        new_registrations=str(registrations[registrations_key]),
        frameworks_published=str(frameworks[frameworks_key]),
        attestations_issued=str(attestations[attestations_key]),
    )


def _serialize_current_state_csv_row(dashboard: dict[str, object]) -> dict[str, str]:
    """Convert non-windowed live dashboard counts into the flat CSV contract."""
    disputes = cast("dict[str, Any]", dashboard["disputes_open"])
    frameworks = cast("dict[str, Any]", dashboard["frameworks_published"])
    return _csv_row(
        row_type="current_state",
        frameworks_published_total=str(frameworks["total"]),
        disputes_open_total=str(disputes["total"]),
        disputes_open_projects=str(disputes["projects"]),
        disputes_open_attestations=str(disputes["attestations"]),
    )


def _render_admin_analytics_csv(rows: list[dict[str, str]]) -> str:
    """Render the flat admin analytics row set as CSV text."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "row_type",
            "snapshot_date",
            "window",
            "gmv_total",
            "gmv_framework_purchase",
            "gmv_collection_purchase",
            "gmv_project_milestone",
            "gmv_attestation_fee",
            "active_users",
            "new_registrations",
            "frameworks_published",
            "frameworks_published_total",
            "attestations_issued",
            "disputes_open_total",
            "disputes_open_projects",
            "disputes_open_attestations",
            "computed_at",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


async def export_dashboard_csv(
    db: AsyncSession,
    *,
    admin: User,
    from_date: date,
    to_date: date,
) -> tuple[str, str]:
    """Export admin analytics as one flat CSV stream and audit the export."""
    if to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'to' must be on or after 'from'.",
        )
    if (to_date - from_date).days + 1 > 366:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Date range cannot exceed 366 days.",
        )

    snapshots = await list_snapshot_history(db, from_date=from_date, to_date=to_date)
    dashboard = await get_dashboard_analytics(db)
    rows = [_serialize_snapshot_csv_row(snapshot) for snapshot in snapshots]
    rows.extend(
        [
            _serialize_window_csv_row(
                dashboard,
                window="today",
                gmv_total_key="today_total",
                gmv_sources_key="today_by_source",
                active_users_key="last_24_hours",
                registrations_key="last_24_hours",
                frameworks_key="last_24_hours",
                attestations_key="last_24_hours",
            ),
            _serialize_window_csv_row(
                dashboard,
                window="last_7_days",
                gmv_total_key="last_7_days_total",
                gmv_sources_key="last_7_days_by_source",
                active_users_key="last_7_days",
                registrations_key="last_7_days",
                frameworks_key="last_7_days",
                attestations_key="last_7_days",
            ),
            _serialize_window_csv_row(
                dashboard,
                window="last_30_days",
                gmv_total_key="last_30_days_total",
                gmv_sources_key="last_30_days_by_source",
                active_users_key="last_30_days",
                registrations_key="last_30_days",
                frameworks_key="last_30_days",
                attestations_key="last_30_days",
            ),
            _serialize_current_state_csv_row(dashboard),
        ]
    )
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="analytics_exported",
        target_type="analytics_export",
        metadata={
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "row_count": len(rows),
        },
    )
    await db.commit()
    filename = f"admin-analytics-{from_date.isoformat()}-to-{to_date.isoformat()}.csv"
    return filename, _render_admin_analytics_csv(rows)


def _decimal_4_string(value: Decimal | None) -> str | None:
    """Serialize a four-decimal review score without float drift."""
    if value is None:
        return None
    return format(value.quantize(Decimal("0.0001")), ".4f")


def _admin_action_link(*, rel: str, path: str) -> dict[str, str]:
    """Build one admin-authenticated moderation action link."""
    return {
        "rel": rel,
        "method": "POST",
        "path": path,
        "actor_role": "admin",
    }


def _contributor_action_link(*, rel: str, path: str) -> dict[str, str]:
    """Build one contributor-authenticated moderation action link."""
    return {
        "rel": rel,
        "method": "POST",
        "path": path,
        "actor_role": "contributor",
    }


def _framework_suspend_action_links(framework: Framework) -> list[dict[str, str]]:
    """Return framework suspension actions relevant to the current state."""
    if framework.status != "published":
        return []
    return [
        _admin_action_link(
            rel="suspend_framework",
            path=f"/v1/admin/frameworks/{framework.id}/suspend",
        )
    ]


async def _list_rarity_review_rows(
    db: AsyncSession,
) -> list[tuple[Artifact, Framework, User, ArtifactRarityAudit | None]]:
    """Return current artifact rows that require rarity moderation review."""
    result = await db.execute(
        select(Artifact, Framework, User, ArtifactRarityAudit)
        .join(Framework, Framework.id == Artifact.framework_id)
        .join(User, User.id == Framework.contributor_id)
        .outerjoin(
            ArtifactRarityAudit,
            ArtifactRarityAudit.artifact_id == Artifact.id,
        )
        .where(
            Artifact.current_for_framework.is_(True),
            Artifact.processing_status == "flagged_rarity",
        )
    )
    # The outer join makes the audit nullable, but the select() types it
    # non-optional; the declared return type is the accurate one.
    return cast(
        "list[tuple[Artifact, Framework, User, ArtifactRarityAudit | None]]",
        list(result.all()),
    )


async def _latest_pii_audits_by_artifact(
    db: AsyncSession,
    artifact_ids: Sequence[UUID],
) -> dict[UUID, Any]:
    """Return the latest PII audit row for each requested artifact."""
    if not artifact_ids:
        return {}
    result = await db.execute(
        select(ArtifactPiiAudit).where(ArtifactPiiAudit.artifact_id.in_(artifact_ids))
    )
    latest: dict[UUID, Any] = {}
    for audit in result.scalars().all():
        existing = latest.get(audit.artifact_id)
        if existing is None or audit.processed_at > existing.processed_at:
            latest[audit.artifact_id] = audit
    return latest


def _rarity_review_item(
    *,
    artifact: Artifact,
    framework: Framework,
    contributor: User,
    rarity_audit: ArtifactRarityAudit | None,
) -> dict[str, Any]:
    """Serialize one artifact-level rarity review row."""
    details: dict[str, Any] = {
        "internal_jaccard": _decimal_4_string(
            rarity_audit.internal_jaccard if rarity_audit else None
        ),
        "blended_score": _decimal_4_string(
            rarity_audit.blended_score if rarity_audit else None
        ),
        "external_phrases_queried": list(
            rarity_audit.external_phrases_queried if rarity_audit else []
        ),
        "external_hit_counts": list(
            rarity_audit.external_hit_counts if rarity_audit else []
        ),
    }
    signal_at = (
        rarity_audit.created_at if rarity_audit is not None else artifact.created_at
    )
    signal_id = str(rarity_audit.id) if rarity_audit is not None else str(artifact.id)
    return {
        "signal_id": signal_id,
        "queue_type": "rarity_review",
        "framework_id": framework.id,
        "framework_title": framework.title,
        "contributor_id": contributor.id,
        "contributor_name": contributor.display_name,
        "artifact_id": artifact.id,
        "artifact_name": artifact.name,
        "signal_at": signal_at,
        "details": details,
        "action_links": _framework_suspend_action_links(framework),
    }


def _near_duplicate_block_item(
    *,
    framework: Framework,
    contributor: User,
    blocked_artifacts: Sequence[Artifact],
    rarity_audits: dict[UUID, ArtifactRarityAudit | None],
) -> dict[str, Any]:
    """Serialize one framework-level near-duplicate block row."""

    def _internal_jaccard_key(artifact: Artifact) -> Decimal:
        """Rank by internal Jaccard, treating missing audits as zero."""
        audit = rarity_audits.get(artifact.id)
        if audit is not None and audit.internal_jaccard is not None:
            return audit.internal_jaccard
        return Decimal("0.0000")

    ranked_artifacts = sorted(
        blocked_artifacts,
        key=_internal_jaccard_key,
        reverse=True,
    )
    primary_artifact = ranked_artifacts[0]
    primary_audit = rarity_audits.get(primary_artifact.id)
    signal_at = (
        primary_audit.created_at if primary_audit is not None else framework.updated_at
    )
    return {
        "signal_id": f"{framework.id}:near_duplicate_block",
        "queue_type": "near_duplicate_block",
        "framework_id": framework.id,
        "framework_title": framework.title,
        "contributor_id": contributor.id,
        "contributor_name": contributor.display_name,
        "artifact_id": primary_artifact.id,
        "artifact_name": primary_artifact.name,
        "signal_at": signal_at,
        "details": {
            "blocked_artifact_ids": [str(artifact.id) for artifact in ranked_artifacts],
            "internal_jaccard": _decimal_4_string(
                primary_audit.internal_jaccard if primary_audit else None
            ),
            "blended_score": _decimal_4_string(
                primary_audit.blended_score if primary_audit else None
            ),
            "external_phrases_queried": list(
                primary_audit.external_phrases_queried if primary_audit else []
            ),
            "external_hit_counts": list(
                primary_audit.external_hit_counts if primary_audit else []
            ),
        },
        "action_links": [
            _admin_action_link(
                rel="override_rarity_block",
                path=f"/v1/admin/frameworks/{framework.id}/rarity-block/override",
            ),
            *_framework_suspend_action_links(framework),
        ],
    }


def _pii_review_item(
    *,
    artifact: Artifact,
    framework: Framework,
    contributor: User,
    pii_audit: Any | None,
) -> dict[str, Any]:
    """Serialize one artifact-level PII review row."""
    redaction = dict((artifact.metadata_vector or {}).get("redaction") or {})
    signal_at = pii_audit.processed_at if pii_audit is not None else artifact.created_at
    action_links: list[dict[str, str]] = []
    if artifact.clean_file_key:
        action_links.append(
            _contributor_action_link(
                rel="accept_redaction",
                path=(
                    f"/v1/frameworks/{framework.id}/artifacts/"
                    f"{artifact.id}/accept-redaction"
                ),
            )
        )
    action_links.append(
        _contributor_action_link(
            rel="resolve_pii_review",
            path=(
                f"/v1/frameworks/{framework.id}/artifacts/"
                f"{artifact.id}/resolve-pii-review"
            ),
        )
    )
    return {
        "signal_id": (
            str(pii_audit.id) if pii_audit is not None else f"{artifact.id}:pii_review"
        ),
        "queue_type": "pii_review",
        "framework_id": framework.id,
        "framework_title": framework.title,
        "contributor_id": contributor.id,
        "contributor_name": contributor.display_name,
        "artifact_id": artifact.id,
        "artifact_name": artifact.name,
        "signal_at": signal_at,
        "details": {
            "pii_types_found": list(pii_audit.pii_types_found if pii_audit else []),
            "auto_redacted": bool(pii_audit.auto_redacted) if pii_audit else False,
            "redaction_status": (
                str(redaction.get("status")) if redaction.get("status") else None
            ),
            "redaction_accepted": bool(redaction.get("accepted")),
            "redaction_available": artifact.clean_file_key is not None,
        },
        "action_links": action_links,
    }


async def list_moderation_queue(
    db: AsyncSession,
    *,
    admin: User,
    queue_type: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Aggregate moderation rows across rarity, near-duplicate, and PII signals."""
    if queue_type not in {"all", *MODERATION_QUEUE_TYPES}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unknown moderation queue type.",
        )

    rarity_rows = await _list_rarity_review_rows(db)
    rarity_audits_by_artifact = {
        artifact.id: rarity_audit for artifact, _, _, rarity_audit in rarity_rows
    }
    items: list[dict[str, Any]] = [
        _rarity_review_item(
            artifact=artifact,
            framework=framework,
            contributor=contributor,
            rarity_audit=rarity_audit,
        )
        for artifact, framework, contributor, rarity_audit in rarity_rows
    ]

    framework_maps: dict[UUID, tuple[Framework, User, list[Artifact]]] = {}
    for artifact, framework, contributor, _ in rarity_rows:
        blocked_ids = (framework.pipeline_failure_reasons or {}).get("internal_rarity")
        if not isinstance(blocked_ids, list):
            blocked_ids = []
        blocked_id_set = {
            UUID(value) for value in blocked_ids if isinstance(value, str)
        }
        if artifact.id not in blocked_id_set:
            continue
        existing = framework_maps.get(framework.id)
        if existing is None:
            framework_maps[framework.id] = (framework, contributor, [artifact])
            continue
        existing[2].append(artifact)
    items.extend(
        _near_duplicate_block_item(
            framework=framework,
            contributor=contributor,
            blocked_artifacts=artifacts,
            rarity_audits=rarity_audits_by_artifact,
        )
        for framework, contributor, artifacts in framework_maps.values()
    )

    pii_result = await db.execute(
        select(Artifact, Framework, User)
        .join(Framework, Framework.id == Artifact.framework_id)
        .join(User, User.id == Framework.contributor_id)
        .where(
            Artifact.current_for_framework.is_(True),
            Artifact.pii_review_needed.is_(True),
        )
    )
    pii_rows = list(pii_result.all())
    latest_pii_audits = await _latest_pii_audits_by_artifact(
        db,
        [artifact.id for artifact, _, _ in pii_rows],
    )
    items.extend(
        _pii_review_item(
            artifact=artifact,
            framework=framework,
            contributor=contributor,
            pii_audit=latest_pii_audits.get(artifact.id),
        )
        for artifact, framework, contributor in pii_rows
    )

    if queue_type != "all":
        items = [item for item in items if item["queue_type"] == queue_type]
    items.sort(
        key=lambda item: (
            item["signal_at"],
            -MODERATION_QUEUE_SORT_PRIORITY[item["queue_type"]],
        ),
        reverse=True,
    )
    total = len(items)
    offset = (page - 1) * page_size
    paginated_items = items[offset : offset + page_size]

    await write_audit(
        db=db,
        actor_id=admin.id,
        action="moderation_queue_viewed",
        target_type="moderation_queue",
        metadata={
            "type": queue_type,
            "page": page,
            "page_size": page_size,
            "returned_count": len(paginated_items),
            "total": total,
        },
    )
    await db.commit()
    return {
        "items": paginated_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def list_admin_users(
    db: AsyncSession,
    *,
    query: str | None,
    status_filter: str,
    page: int,
    page_size: int,
) -> dict[str, object]:
    """Return a paginated admin-facing user directory."""
    if status_filter not in ADMIN_USER_DIRECTORY_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported user directory filter.",
        )

    filters: list[ColumnElement[bool]] = []
    if status_filter == "active":
        filters.append(User.suspended_at.is_(None))
    elif status_filter == "suspended":
        filters.append(User.suspended_at.is_not(None))
    elif status_filter == "kyc_pending":
        filters.append(User.kyc_status == "pending")

    normalized_query = (query or "").strip()
    if normalized_query:
        like_value = f"%{normalized_query}%"
        filters.append(
            or_(
                User.display_name.ilike(like_value),
                User.email.ilike(like_value),
            )
        )

    total = await db.scalar(select(func.count(User.id)).where(*filters))
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(*filters)
        .order_by(desc(User.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    users = list(result.scalars().all())

    return {
        "items": [
            {
                "user_id": user.id,
                "display_name": user.display_name,
                "email": user.email,
                "roles": sorted(role.role for role in user.roles),
                "created_at": user.created_at,
                "suspended": user.suspended_at is not None,
                "suspended_at": user.suspended_at,
                "is_superadmin": user.is_superadmin,
                "kyc_status": user.kyc_status,
            }
            for user in users
        ],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


async def list_admin_payouts(
    db: AsyncSession,
    *,
    status_filter: str,
    provider_filter: str,
    page: int,
    page_size: int,
) -> dict[str, object]:
    """Return a paginated, read-only payout directory for admin oversight.

    Joins each payout to its payout account for the provider label and maps the
    contributor/org XOR to an explicit beneficiary type. Payout-account details
    are never included — only the provider and transfer reference — so no
    sensitive destination data leaks into the list.

    Args:
        db: Async database session.
        status_filter: One of ``ADMIN_PAYOUT_STATUSES``.
        provider_filter: One of ``ADMIN_PAYOUT_PROVIDERS``.
        page: 1-indexed page number.
        page_size: Rows per page.

    Returns:
        A dict with ``items``, ``total``, ``page``, and ``page_size``.

    Raises:
        HTTPException(422): If a filter value is unsupported.
    """
    if status_filter not in ADMIN_PAYOUT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported payout status filter.",
        )
    if provider_filter not in ADMIN_PAYOUT_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported payout provider filter.",
        )

    filters: list[ColumnElement[bool]] = []
    if status_filter != "all":
        filters.append(Payout.status == status_filter)
    if provider_filter != "all":
        filters.append(PayoutAccount.provider == provider_filter)

    base = (
        select(Payout, PayoutAccount)
        .join(PayoutAccount, PayoutAccount.id == Payout.payout_account_id)
        .where(*filters)
    )
    total = await db.scalar(
        select(func.count())
        .select_from(Payout)
        .join(PayoutAccount, PayoutAccount.id == Payout.payout_account_id)
        .where(*filters)
    )
    result = await db.execute(
        base.order_by(desc(Payout.initiated_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    items = []
    for payout, account in result.all():
        is_contributor = payout.contributor_id is not None
        items.append(
            {
                "payout_id": payout.id,
                "beneficiary_type": "contributor" if is_contributor else "org",
                "beneficiary_id": (
                    payout.contributor_id if is_contributor else payout.org_id
                ),
                "provider": account.provider,
                "amount": str(payout.amount),
                "commission_deducted": str(payout.commission_deducted),
                "net_amount": str(payout.net_amount),
                "currency": payout.currency,
                "status": payout.status,
                "provider_ref": payout.provider_ref,
                "initiated_at": payout.initiated_at,
                "completed_at": payout.completed_at,
            }
        )

    return {
        "items": items,
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
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
            UserRole.source == ("derived" if role == "attestor" else "self"),
        )
    )
    if existing is None:
        existing = UserRole(
            user_id=target_user_id,
            role=role,
            source="derived" if role == "attestor" else "self",
        )
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
) -> User:
    """Manually override a user's identity-verification status.

    Identity verification is normally automated via Persona; this admin path is
    the override for appeals and cases Persona cannot resolve. It sets the user's
    KYC status directly — there is no document to review — audits the action, and
    notifies the user of the verdict.

    Args:
        db: Async DB session.
        admin: The acting admin (audited as actor).
        target_user_id: The user whose status is overridden.
        review_status: ``verified`` or ``rejected``.
        notes: Optional reason recorded in the audit metadata.

    Returns:
        The updated User.

    Raises:
        HTTPException(404): If the target user does not exist.
    """
    target = await db.scalar(select(User).where(User.id == target_user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    target.kyc_status = review_status
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="kyc_status_change",
        target_type="user",
        target_id=target_user_id,
        metadata={
            "status": review_status,
            "source": "admin_override",
            "notes": notes,
        },
    )
    # Notify the user of the verdict so an override surfaces without polling.
    # Dedupe on the user + verdict so a repeated override collapses to one.
    if review_status in ("verified", "rejected"):
        verified = review_status == "verified"
        await create_notification(
            db=db,
            user_id=target_user_id,
            notification_type="kyc_verified" if verified else "kyc_rejected",
            title=(
                "Identity verified"
                if verified
                else "Identity verification needs attention"
            ),
            body=(
                "Your identity is verified. You can now request payouts."
                if verified
                else "Your identity could not be verified. Start a new "
                "verification from settings to try again."
            ),
            link="/settings/kyc",
            payload={"status": review_status, "source": "admin_override"},
            dedupe_key=f"kyc-override:{target_user_id}:{review_status}",
        )
    await db.commit()
    return target


async def list_admin_frameworks(
    db: AsyncSession,
    query: str | None = None,
) -> dict[str, Any]:
    """List published Frameworks with their owners for admin delist control.

    Surfaces arbitrary published Frameworks — not just signal-flagged ones —
    so an admin can take down any Framework on request. Joined to the owning
    Contributor so the UI can show who is affected.

    Args:
        db: Async database session.
        query: Optional case-insensitive title substring to narrow the list.

    Returns:
        A dict with an ``items`` list of published-Framework summaries, newest
        publication first.
    """
    statement = (
        select(Framework, User)
        .join(User, User.id == Framework.contributor_id)
        .where(Framework.status == "published")
    )
    if query:
        statement = statement.where(Framework.title.ilike(f"%{query.strip()}%"))
    statement = statement.order_by(
        Framework.published_at.desc().nullslast(), Framework.title
    )
    rows = (await db.execute(statement)).all()

    return {
        "items": [
            {
                "framework_id": framework.id,
                "title": framework.title,
                "contributor_id": contributor.id,
                "contributor_name": contributor.display_name,
                "status": framework.status,
                "published_at": framework.published_at,
            }
            for framework, contributor in rows
        ]
    }


async def list_suspended_frameworks(db: AsyncSession) -> dict[str, Any]:
    """List every Framework currently suspended from the marketplace.

    Joins each suspended Framework to its owning Contributor and the timestamp
    of its most recent ``framework_suspended`` audit entry so the admin UI can
    show who is affected and when the takedown happened.

    Args:
        db: Async database session.

    Returns:
        A dict with an ``items`` list of suspended-Framework summaries, newest
        suspension first.
    """
    suspended_at_subquery = (
        select(
            AuditLog.target_id.label("target_id"),
            func.max(AuditLog.created_at).label("suspended_at"),
        )
        .where(
            AuditLog.action == "framework_suspended",
            AuditLog.target_type == "framework",
        )
        .group_by(AuditLog.target_id)
        .subquery()
    )

    rows = (
        await db.execute(
            select(Framework, User, suspended_at_subquery.c.suspended_at)
            .join(User, User.id == Framework.contributor_id)
            .outerjoin(
                suspended_at_subquery,
                suspended_at_subquery.c.target_id == Framework.id,
            )
            .where(Framework.status == "suspended")
            .order_by(
                suspended_at_subquery.c.suspended_at.desc().nullslast(),
                Framework.title,
            )
        )
    ).all()

    return {
        "items": [
            {
                "framework_id": framework.id,
                "title": framework.title,
                "contributor_id": contributor.id,
                "contributor_name": contributor.display_name,
                "reason": framework.rejection_reason,
                "suspended_at": suspended_at,
            }
            for framework, contributor, suspended_at in rows
        ]
    }


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


async def reinstate_framework(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
) -> Framework:
    """Reverse an admin takedown, returning a suspended Framework to the catalog.

    The inverse of :func:`suspend_framework`. Re-runs the safety-critical trust
    gates (virus, scan error, unfinished processing, PII) against the live
    Artifact state before republishing, so a Framework that drifted while
    suspended can never silently re-enter the public catalog. Refuses anything
    that is not currently suspended.

    Args:
        db: Async database session.
        admin: Acting admin user (RBAC enforced at the router).
        framework_id: UUID of the suspended Framework to reinstate.

    Returns:
        The reinstated Framework with status ``published``.

    Raises:
        HTTPException(404): If the Framework does not exist.
        HTTPException(409): If the Framework is not suspended, or an Artifact
            now fails a trust gate.
    """
    framework = await db.scalar(select(Framework).where(Framework.id == framework_id))
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    if framework.status != "suspended":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only suspended Frameworks can be reinstated.",
        )
    if await current_artifacts_block_publish(db, framework.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This framework can't be reinstated because an artifact failed a "
                "trust check (virus or PII). The Contributor must resolve it with "
                "a new version."
            ),
        )

    framework.status = "published"
    framework.rejection_reason = None
    framework.published_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="framework_reinstated",
        target_type="framework",
        target_id=framework.id,
        metadata={},
    )
    await db.commit()
    try:
        await index_framework_artifacts(framework.id)
    except Exception as exc:
        logger.bind(
            module="admin",
            action="reindex_framework_on_reinstate",
            user_id=admin.id,
            framework_id=framework.id,
        ).error("artifact_lsh_index_failed", error=str(exc))
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


async def _is_active_admin(db: AsyncSession, user_id: UUID) -> bool:
    """Return whether a user is currently an unsuspended approved admin."""
    active_admin = await db.scalar(
        select(UserRole.id)
        .join(User, User.id == UserRole.user_id)
        .where(
            UserRole.user_id == user_id,
            UserRole.role == "admin",
            UserRole.approved_at.is_not(None),
            User.deactivated_at.is_(None),
            User.suspended_at.is_(None),
        )
        .limit(1)
    )
    return active_admin is not None


async def _count_active_admins(db: AsyncSession) -> int:
    """Return the number of currently active approved admin accounts."""
    return int(
        await db.scalar(
            select(func.count(User.id))
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                UserRole.role == "admin",
                UserRole.approved_at.is_not(None),
                User.deactivated_at.is_(None),
                User.suspended_at.is_(None),
            )
        )
        or 0
    )


async def suspend_user(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    target_user_id: UUID,
    reason: str,
    totp_code: str,
) -> User:
    """Suspend one user, revoke sessions, and revoke developer API keys."""
    admin_id = admin.id
    normalized_reason = reason.strip()
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        await _verify_admin_2fa(
            db=db,
            redis=redis,
            admin_id=admin_id,
            totp_code=totp_code,
        )
        target = await db.get(User, target_user_id, with_for_update=True)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )
        if target.id == admin_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Admins cannot suspend themselves.",
            )
        if target.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The super-admin account cannot be suspended.",
            )
        if target.suspended_at is None and await _is_active_admin(db, target.id):
            if await _count_active_admins(db) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot suspend the final active admin.",
                )

        now = datetime.now(UTC)
        developer_account = await db.scalar(
            select(DeveloperAccount)
            .where(DeveloperAccount.user_id == target.id)
            .with_for_update()
        )
        if target.suspended_at is None:
            target.suspended_at = now
            target.suspended_by = admin_id
            target.suspension_reason = normalized_reason
            target.access_revoked_before = now
            if developer_account is not None:
                developer_account.status = "suspended"
            api_keys = (
                (
                    await db.execute(
                        select(ApiKey).where(
                            ApiKey.developer_account_id == developer_account.id
                        )
                    )
                )
                .scalars()
                .all()
                if developer_account is not None
                else []
            )
            for api_key in api_keys:
                if api_key.status != "revoked":
                    api_key.status = "revoked"
                    api_key.revoked_at = now
            await write_audit(
                db=db,
                actor_id=admin_id,
                action="user_suspended",
                target_type="user",
                target_id=target.id,
                metadata={"reason": normalized_reason, "idempotent": False},
            )
        else:
            await write_audit(
                db=db,
                actor_id=admin_id,
                action="user_suspended",
                target_type="user",
                target_id=target.id,
                metadata={
                    "reason": target.suspension_reason,
                    "idempotent": True,
                },
            )
    await auth_service.revoke_all_user_sessions(redis, target)
    return target


async def unsuspend_user(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    target_user_id: UUID,
    totp_code: str,
) -> User:
    """Clear suspension state for one user without restoring revoked keys."""
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
        target = await db.get(User, target_user_id, with_for_update=True)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )
        developer_account = await db.scalar(
            select(DeveloperAccount)
            .where(DeveloperAccount.user_id == target.id)
            .with_for_update()
        )
        if target.suspended_at is None:
            await write_audit(
                db=db,
                actor_id=admin_id,
                action="user_unsuspended",
                target_type="user",
                target_id=target.id,
                metadata={"idempotent": True},
            )
            return target

        target.suspended_at = None
        target.suspended_by = None
        target.suspension_reason = None
        if developer_account is not None:
            developer_account.status = "active"
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="user_unsuspended",
            target_type="user",
            target_id=target.id,
            metadata={"idempotent": False},
        )
    return target


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
                    f"{key} must be between {integer_minimum} and {integer_maximum}."
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

    if key in REPUTATION_WEIGHT_KEYS:
        subject_type = key.removeprefix("reputation_weights_")
        try:
            parsed_json = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} must be a JSON object of factor weights.",
            ) from exc
        if not isinstance(parsed_json, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} must be a JSON object of factor weights.",
            )
        try:
            parsed = {
                factor: Decimal(str(value)) for factor, value in parsed_json.items()
            }
            reputation_weights.validate_weight_map(
                parsed,
                subject_type=subject_type,
            )
        except (ArithmeticError, ValueError) as exc:
            detail = str(exc)
            if "must use keys" in detail:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"{key} must contain exactly these factors: "
                        f"{sorted(reputation_weights.expected_weight_keys(subject_type))}."
                    ),
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} weights must be non-negative and sum to 1.0.",
            ) from exc
        return json.dumps(
            {
                factor: f"{value.quantize(Decimal('0.0001')):.4f}"
                for factor, value in sorted(parsed.items())
            },
            separators=(",", ":"),
        )

    if key in REPUTATION_MIN_ACTIVITY_KEYS:
        count = _parse_integer_config(key, raw_value)
        if count < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} must be at least 1.",
            )
        return str(count)

    if key == "reputation_prior":
        value = _parse_decimal_config(key, raw_value)
        if value < Decimal("0") or value > Decimal("1"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="reputation_prior must be between 0 and 1.",
            )
        return _format_decimal_config(value.quantize(Decimal("0.0001")))

    if key == "reputation_prior_strength_k":
        value = _parse_decimal_config(key, raw_value)
        if value < Decimal("0"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "reputation_prior_strength_k must be greater than or equal to 0."
                ),
            )
        return _format_decimal_config(value.quantize(Decimal("0.0001")))

    if key == "reputation_dispute_penalty":
        value = _parse_decimal_config(key, raw_value)
        if value < Decimal("0") or value > Decimal("1"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="reputation_dispute_penalty must be between 0 and 1.",
            )
        return _format_decimal_config(value.quantize(Decimal("0.0001")))

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


async def recompute_reputation_subject(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    subject_type: str,
    subject_id: UUID,
    reason: str,
    totp_code: str,
) -> None:
    """Queue a single-subject reputation recompute behind an audited 2FA gate.

    Verifies the admin's TOTP, confirms the subject exists, records an audit
    entry, then dispatches the idempotent Celery recompute task. Raises before
    dispatch on any failure so a denied request never enqueues work.

    Args:
        db: Async session.
        redis: Redis client for the TOTP rate-limit guard.
        admin: The authenticated admin user.
        subject_type: One of ``framework``, ``contributor``, ``operator``.
        subject_id: UUID of the subject to recompute.
        reason: Human-readable justification, recorded in the audit log.
        totp_code: Admin TOTP or backup code.

    Raises:
        HTTPException(404): Subject type unknown or subject does not exist.
    """
    from app.modules.reputation import service as reputation_service
    from app.workers.tasks.reputation import recompute_subject_task

    admin_id = admin.id
    if subject_type not in reputation_service.VALID_SUBJECT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown reputation subject type.",
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
        if not await reputation_service.subject_exists(
            db, subject_type=subject_type, subject_id=subject_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reputation subject not found.",
            )
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="reputation_recompute_requested",
            target_type=subject_type,
            target_id=subject_id,
            metadata={"reason": reason},
        )
    recompute_subject_task.delay(subject_type, str(subject_id))
