"""SQLAlchemy models for notification delivery, delivery markers, and preferences.

Notifications are persisted before realtime fanout or email dispatch, so
clients can recover missed Redis pub/sub events by refetching from Postgres.
User preference rows stay event-type based and default to enabled when absent.
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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

NOTIFICATION_TYPE_ENUM = ENUM(
    "project_created",
    "project_extended",
    "project_closed",
    "proposal_submitted",
    "proposal_accepted",
    "proposal_rejected",
    "proposal_withdrawn",
    "proposal_expired",
    "amendment_proposed",
    "amendment_accepted",
    "amendment_rejected",
    "amendment_withdrawn",
    "amendment_expired",
    "milestone_created",
    "milestone_updated",
    "milestone_funded",
    "deliverable_submitted",
    "deliverable_approved",
    "deliverable_auto_approved",
    "deliverable_revision_requested",
    "dispute_raised",
    "dispute_escalated",
    "dispute_resolved_release",
    "dispute_resolved_refund",
    "dispute_resolved_split",
    "workspace_file_quarantined",
    "attestation_requested",
    "attestation_fee_funded",
    "attestation_offer_received",
    "attestation_assigned",
    "attestation_accepted",
    "attestation_declined",
    "attestation_offer_expired",
    "attestation_reassigned",
    "attestation_needs_admin",
    "attestation_report_submitted",
    "attestation_published",
    "attestation_rejected",
    "attestation_released",
    "attestation_disputed",
    "attestation_dispute_resolved",
    "attestation_refunded",
    "attestation_annual_summary_ready",
    "api_rate_limit_threshold",
    "saved_search_alert",
    "kyc_verified",
    "kyc_rejected",
    name="notification_type_enum",
    create_type=False,
)
NOTIFICATION_CHANNEL_ENUM = ENUM(
    "email",
    "in_app",
    name="notification_channel_enum",
    create_type=False,
)
NOTIFICATION_CATEGORY_ENUM = ENUM(
    "project",
    "attestation",
    "financial",
    "discovery",
    "account",
    name="notification_category_enum",
    create_type=False,
)


class Notification(CreatedAtMixin, Base):
    """Recoverable in-app notification addressed to one user."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "idx_notifications_user_read_created",
            "user_id",
            text("read_at NULLS FIRST"),
            text("created_at DESC"),
        ),
        Index(
            "uq_notifications_user_dedupe_key",
            "user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    notification_type: Mapped[str] = mapped_column(
        "type",
        NOTIFICATION_TYPE_ENUM,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class NotificationPreference(UpdatedAtMixin, Base):
    """Per-user per-event per-channel notification preference override."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "notification_type",
            "channel",
            name="uq_notification_preferences_user_type_channel",
        ),
        Index(
            "idx_notification_preferences_user_type",
            "user_id",
            "notification_type",
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
    notification_type: Mapped[str] = mapped_column(
        NOTIFICATION_TYPE_ENUM,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        NOTIFICATION_CATEGORY_ENUM,
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(
        NOTIFICATION_CHANNEL_ENUM,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )


class NotificationDeliveryMarker(CreatedAtMixin, Base):
    """Durable dedup marker for notification channels without in-app rows."""

    __tablename__ = "notification_delivery_markers"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "dedupe_key",
            "channel",
            name="uq_notification_delivery_markers_user_dedupe_channel",
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
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(
        NOTIFICATION_CHANNEL_ENUM,
        nullable=False,
    )
