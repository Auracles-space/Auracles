"""SQLAlchemy models for GDPR data-rights workflows.

Defines durable request state for data exports, account deletion cooling-off,
and append-only consent logs.
"""

from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ENUM, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DATA_EXPORT_STATUS_ENUM = ENUM(
    "pending",
    "processing",
    "ready",
    "failed",
    "expired",
    name="data_export_status_enum",
    create_type=False,
)
ACCOUNT_DELETION_STATUS_ENUM = ENUM(
    "pending",
    "scheduled",
    "blocked",
    "cancelled",
    "completed",
    name="account_deletion_status_enum",
    create_type=False,
)
CONSENT_DOCUMENT_ENUM = ENUM(
    "terms_of_service",
    "privacy_policy",
    name="consent_document_enum",
    create_type=False,
)


class DataExportRequest(Base):
    """User-owned async request for a private GDPR export bundle."""

    __tablename__ = "data_export_requests"
    __table_args__ = (
        Index("idx_data_export_requests_user_status", "user_id", "status"),
        Index(
            "uq_data_export_requests_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing')"),
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
    status: Mapped[str] = mapped_column(
        DATA_EXPORT_STATUS_ENUM,
        nullable=False,
        server_default=text("'pending'"),
    )
    bundle_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AccountDeletionRequest(Base):
    """User-owned account deletion request with cooling-off state."""

    __tablename__ = "account_deletion_requests"
    __table_args__ = (
        Index(
            "idx_account_deletion_requests_status_scheduled",
            "status",
            "scheduled_for",
        ),
        Index(
            "uq_account_deletion_requests_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'scheduled')"),
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
    status: Mapped[str] = mapped_column(
        ACCOUNT_DELETION_STATUS_ENUM,
        nullable=False,
        server_default=text("'pending'"),
    )
    blocked_reasons: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ConsentLog(Base):
    """Append-only record of a user's accepted legal document version."""

    __tablename__ = "consent_logs"
    __table_args__ = (
        Index(
            "idx_consent_logs_user_document_accepted",
            "user_id",
            "document_type",
            text("accepted_at DESC"),
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
    document_type: Mapped[str] = mapped_column(
        CONSENT_DOCUMENT_ENUM,
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(
        INET,
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
