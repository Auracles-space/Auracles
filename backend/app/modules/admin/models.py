"""SQLAlchemy models for admin analytics state.

Stores daily UTC snapshot rows that back trend charts and CSV export without
recomputing historical aggregates on every admin request.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Index, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalyticsDailySnapshot(Base):
    """Frozen UTC daily aggregate row for admin dashboard trends and export."""

    __tablename__ = "analytics_daily_snapshots"
    __table_args__ = (
        Index("idx_analytics_daily_snapshots_computed_at", "computed_at"),
    )

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    gmv_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gmv_by_source: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    active_users: Mapped[int] = mapped_column(nullable=False)
    new_registrations: Mapped[int] = mapped_column(nullable=False)
    frameworks_published: Mapped[int] = mapped_column(nullable=False)
    attestations_issued: Mapped[int] = mapped_column(nullable=False)
    disputes_open: Mapped[int] = mapped_column(nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
