"""SQLAlchemy model for durable payment webhook idempotency.

Each verified provider event is stored once using `(provider, provider_event_id)`
so retry delivery can return success without repeating side effects.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.financials.models import PAYMENT_PROVIDER_ENUM

WEBHOOK_EVENT_STATUS_ENUM = ENUM(
    "received",
    "processed",
    "failed",
    name="webhook_event_status_enum",
    create_type=False,
)


class WebhookEvent(Base):
    """Stored payment webhook event used for dedupe and audit."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_webhook_events_provider_event",
        ),
        Index("idx_webhook_events_status", "status"),
        Index("idx_webhook_events_received_at", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(PAYMENT_PROVIDER_ENUM, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        WEBHOOK_EVENT_STATUS_ENUM,
        nullable=False,
        server_default="received",
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
