"""Developer analytics read-model service.

Aggregates Partner API usage logs and Partner commission sales data for the
Developer dashboard. Responses are intentionally aggregate-only and avoid buyer
identity, raw IP addresses, API secrets, or licensed artifact data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.developer.models import (
    ApiKey,
    ApiRequestLog,
    DeveloperAccount,
    PartnerCommission,
)
from app.modules.developer.schemas import (
    DeveloperSalesAnalyticsResponse,
    DeveloperSalesFrameworkBreakdown,
    DeveloperUsageAnalyticsResponse,
    DeveloperUsageEndpointBreakdown,
)
from app.modules.frameworks.models import Framework

COMMISSION_STATUSES = ("pending", "cleared", "paid", "voided")


def _average_response_ms(value: object) -> int:
    """Normalize a nullable database average into a rounded integer."""
    if value is None:
        return 0
    return int(round(float(value)))


def _money(value: object) -> Decimal:
    """Normalize nullable aggregate money values to two decimal places."""
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


async def get_usage_analytics(
    db: AsyncSession,
    *,
    developer_account: DeveloperAccount,
    days: int,
) -> DeveloperUsageAnalyticsResponse:
    """Return aggregate Partner API usage for one Developer account."""
    since = datetime.now(UTC) - timedelta(days=days)
    filters = [
        ApiKey.developer_account_id == developer_account.id,
        ApiRequestLog.created_at >= since,
    ]
    success_expr = case((ApiRequestLog.status_code < 400, 1), else_=0)
    client_error_expr = case(
        (
            (ApiRequestLog.status_code >= 400) & (ApiRequestLog.status_code < 500),
            1,
        ),
        else_=0,
    )
    server_error_expr = case((ApiRequestLog.status_code >= 500, 1), else_=0)

    totals = (
        await db.execute(
            select(
                func.count(ApiRequestLog.id),
                func.coalesce(func.sum(success_expr), 0),
                func.coalesce(func.sum(client_error_expr), 0),
                func.coalesce(func.sum(server_error_expr), 0),
                func.avg(ApiRequestLog.response_ms),
            )
            .join(ApiKey, ApiKey.id == ApiRequestLog.api_key_id)
            .where(*filters)
        )
    ).one()
    endpoint_rows = (
        await db.execute(
            select(
                ApiRequestLog.endpoint,
                ApiRequestLog.method,
                func.count(ApiRequestLog.id).label("request_count"),
                func.coalesce(func.sum(success_expr), 0).label("success_count"),
                func.coalesce(func.sum(client_error_expr), 0).label(
                    "client_error_count"
                ),
                func.coalesce(func.sum(server_error_expr), 0).label(
                    "server_error_count"
                ),
                func.avg(ApiRequestLog.response_ms).label("average_response_ms"),
            )
            .join(ApiKey, ApiKey.id == ApiRequestLog.api_key_id)
            .where(*filters)
            .group_by(ApiRequestLog.endpoint, ApiRequestLog.method)
            .order_by(func.count(ApiRequestLog.id).desc(), ApiRequestLog.endpoint)
        )
    ).all()

    return DeveloperUsageAnalyticsResponse(
        window_days=days,
        total_requests=int(totals[0] or 0),
        success_count=int(totals[1] or 0),
        client_error_count=int(totals[2] or 0),
        server_error_count=int(totals[3] or 0),
        average_response_ms=_average_response_ms(totals[4]),
        by_endpoint=[
            DeveloperUsageEndpointBreakdown(
                endpoint=row.endpoint,
                method=row.method,
                request_count=int(row.request_count),
                success_count=int(row.success_count),
                client_error_count=int(row.client_error_count),
                server_error_count=int(row.server_error_count),
                average_response_ms=_average_response_ms(row.average_response_ms),
            )
            for row in endpoint_rows
        ],
    )


async def get_sales_analytics(
    db: AsyncSession,
    *,
    developer_account: DeveloperAccount,
    days: int,
) -> DeveloperSalesAnalyticsResponse:
    """Return aggregate Partner sale and commission data for one Developer."""
    since = datetime.now(UTC) - timedelta(days=days)
    filters = [
        PartnerCommission.developer_account_id == developer_account.id,
        PartnerCommission.created_at >= since,
    ]
    totals = (
        await db.execute(
            select(
                func.count(PartnerCommission.id),
                func.coalesce(func.sum(PartnerCommission.sale_amount), 0),
                func.coalesce(func.sum(PartnerCommission.commission_amount), 0),
            ).where(*filters)
        )
    ).one()
    status_rows = (
        await db.execute(
            select(
                PartnerCommission.status,
                func.count(PartnerCommission.id),
                func.coalesce(func.sum(PartnerCommission.commission_amount), 0),
            )
            .where(*filters)
            .group_by(PartnerCommission.status)
        )
    ).all()
    counts_by_status = {status: 0 for status in COMMISSION_STATUSES}
    amounts_by_status = {status: Decimal("0.00") for status in COMMISSION_STATUSES}
    for status, count, amount in status_rows:
        counts_by_status[str(status)] = int(count)
        amounts_by_status[str(status)] = _money(amount)

    framework_rows = (
        await db.execute(
            select(
                PartnerCommission.framework_id,
                Framework.title,
                func.count(PartnerCommission.id).label("sale_count"),
                func.coalesce(func.sum(PartnerCommission.sale_amount), 0).label(
                    "gross_sale_amount"
                ),
                func.coalesce(
                    func.sum(PartnerCommission.commission_amount),
                    0,
                ).label("commission_amount"),
            )
            .join(Framework, Framework.id == PartnerCommission.framework_id)
            .where(*filters)
            .group_by(PartnerCommission.framework_id, Framework.title)
            .order_by(func.sum(PartnerCommission.sale_amount).desc(), Framework.title)
        )
    ).all()

    return DeveloperSalesAnalyticsResponse(
        window_days=days,
        total_sales=int(totals[0] or 0),
        gross_sale_amount=_money(totals[1]),
        total_commission_amount=_money(totals[2]),
        pending_commission_amount=amounts_by_status["pending"],
        cleared_commission_amount=amounts_by_status["cleared"],
        paid_commission_amount=amounts_by_status["paid"],
        voided_commission_amount=amounts_by_status["voided"],
        status_counts=counts_by_status,
        by_framework=[
            DeveloperSalesFrameworkBreakdown(
                framework_id=row.framework_id,
                framework_title=row.title,
                sale_count=int(row.sale_count),
                gross_sale_amount=_money(row.gross_sale_amount),
                commission_amount=_money(row.commission_amount),
            )
            for row in framework_rows
        ],
    )
