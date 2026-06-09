"""SQLAlchemy models for Phase 4a project workspaces.

Workspace messages persist chat, system events, and attachment references.
Upload sessions bind S3 keys to a project member before the message create path
is allowed to attach those keys.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin

WORKSPACE_SCAN_STATUS_ENUM = ENUM(
    "pending_scan",
    "visible",
    "quarantined",
    name="workspace_scan_status_enum",
    create_type=False,
)
WORKSPACE_SYSTEM_EVENT_ENUM = ENUM(
    "amendment_proposed",
    "amendment_accepted",
    "amendment_rejected",
    "amendment_expired",
    "milestone_funded",
    "deliverable_submitted",
    "deliverable_approved",
    "deliverable_auto_approved",
    "deliverable_revision_requested",
    "dispute_raised",
    "dispute_resolved",
    name="workspace_system_event_enum",
    create_type=False,
)


class WorkspaceMessage(CreatedAtMixin, Base):
    """Persisted workspace chat message or auditable system event."""

    __tablename__ = "workspace_messages"
    __table_args__ = (
        CheckConstraint(
            "(sender_id IS NOT NULL AND (body IS NOT NULL OR file_keys IS NOT NULL)) "
            "OR (sender_id IS NULL AND system_event IS NOT NULL)",
            name="ck_workspace_messages_sender_or_system_event",
        ),
        Index(
            "idx_workspace_messages_project_created_at",
            "project_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_workspace_messages_pending_scan",
            "scan_status",
            postgresql_where=text("scan_status = 'pending_scan'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_keys: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    scan_status: Mapped[str] = mapped_column(
        WORKSPACE_SCAN_STATUS_ENUM,
        nullable=False,
        server_default="visible",
    )
    system_event: Mapped[str | None] = mapped_column(
        WORKSPACE_SYSTEM_EVENT_ENUM,
        nullable=True,
    )
    system_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class WorkspaceUploadSession(CreatedAtMixin, Base):
    """Server-issued permission for one workspace S3 upload key."""

    __tablename__ = "workspace_upload_sessions"
    __table_args__ = (
        UniqueConstraint("s3_key", name="uq_workspace_upload_sessions_s3_key"),
        Index(
            "idx_workspace_upload_sessions_project_user_consumed",
            "project_id",
            "user_id",
            "consumed_at",
        ),
        Index("idx_workspace_upload_sessions_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
