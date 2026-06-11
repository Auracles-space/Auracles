"""SQLAlchemy models for Operator saved searches.

Defines Phase 5b-2 Slice 1 storage for owner-scoped Explore filter snapshots
and later alert delivery idempotency rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin


class SavedSearch(UpdatedAtMixin, Base):
    """Operator-owned Explore query saved for reruns and optional alerts."""

    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_saved_searches_user_name"),
        Index("idx_saved_searches_user", "user_id"),
        Index(
            "idx_saved_searches_alerts",
            "user_id",
            postgresql_where=text("alert_enabled = true"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    filter_version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    alert_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    last_alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_alerted_framework_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="SET NULL"),
        nullable=True,
    )

    deliveries: Mapped[list[SavedSearchAlertDelivery]] = relationship(
        back_populates="saved_search",
        cascade="all, delete-orphan",
    )


class SavedSearchAlertDelivery(CreatedAtMixin, Base):
    """Idempotency row recording one Framework delivered for one saved search."""

    __tablename__ = "saved_search_alert_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "saved_search_id",
            "framework_id",
            name="uq_saved_search_alert_deliveries_search_framework",
        ),
        Index(
            "idx_saved_search_alert_deliveries_search",
            "saved_search_id",
        ),
        Index(
            "idx_saved_search_alert_deliveries_framework",
            "framework_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    saved_search_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("saved_searches.id", ondelete="CASCADE"),
        nullable=False,
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    saved_search: Mapped[SavedSearch] = relationship(back_populates="deliveries")
