"""SQLAlchemy models for Framework marketplace records.

These models mirror the Phase 2 Slice 1 schema foundation: contributor-owned
Frameworks, their immutable version history, license records, and framework
reviews. File artifact models live in `models_artifact.py` to keep the upload
and processing schema separate from framework metadata.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

FRAMEWORK_STATUS_ENUM = ENUM(
    "draft",
    "submitted",
    "processing",
    "pipeline_passed",
    "pipeline_failed",
    "published",
    "unpublished",
    "suspended",
    name="framework_status_enum",
    create_type=False,
)
ORG_SIZE_ENUM = ENUM(
    "startup",
    "small_business",
    "sme",
    "mid_market",
    "enterprise",
    name="org_size_enum",
    create_type=False,
)
LICENSE_TYPE_ENUM = ENUM(
    "single_user",
    "team",
    "enterprise",
    name="license_type_enum",
    create_type=False,
)
LICENSE_STATUS_ENUM = ENUM(
    "active",
    "expired",
    "revoked",
    name="license_status_enum",
    create_type=False,
)
CHANGE_TYPE_ENUM = ENUM(
    "fix",
    "improvement",
    "major",
    name="change_type_enum",
    create_type=False,
)
VERSION_ACTION_ENUM = ENUM(
    "created",
    "published",
    "unpublished",
    "suspended",
    name="version_action_enum",
    create_type=False,
)


class Framework(UpdatedAtMixin, Base):
    """Contributor-authored marketplace asset sold to Operators."""

    __tablename__ = "frameworks"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_frameworks_price_positive"),
        CheckConstraint(
            "complexity IS NULL OR complexity BETWEEN 1 AND 5",
            name="ck_frameworks_complexity_range",
        ),
        Index("idx_frameworks_status", "status"),
        Index("idx_frameworks_contributor", "contributor_id"),
        Index("idx_frameworks_category", "category"),
        Index("idx_frameworks_sector", "sector"),
        Index("idx_frameworks_price", "price"),
        Index("idx_frameworks_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contributor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="1.0.0",
    )
    status: Mapped[str] = mapped_column(
        FRAMEWORK_STATUS_ENUM,
        nullable=False,
        server_default="draft",
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    business_function: Mapped[str | None] = mapped_column(
        "function",
        String(100),
        nullable=True,
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    tags_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="",
    )
    jurisdiction: Mapped[str | None] = mapped_column(String(100), nullable=True)
    complexity: Mapped[int | None] = mapped_column(nullable=True)
    org_size: Mapped[str | None] = mapped_column(ORG_SIZE_ENUM, nullable=True)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    license_types: Mapped[list[str]] = mapped_column(
        ARRAY(LICENSE_TYPE_ENUM),
        nullable=False,
    )
    commercial_rights: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id"),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_type: Mapped[str | None] = mapped_column(CHANGE_TYPE_ENUM, nullable=True)
    last_pipeline_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    pipeline_failure_reasons: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    versions: Mapped[list[FrameworkVersion]] = relationship(
        back_populates="framework",
        cascade="all, delete-orphan",
    )
    licenses: Mapped[list[License]] = relationship(
        back_populates="framework",
        cascade="all, delete-orphan",
    )
    reviews: Mapped[list[Review]] = relationship(
        back_populates="framework",
        cascade="all, delete-orphan",
    )


class FrameworkVersion(CreatedAtMixin, Base):
    """Immutable version record created when a Framework is published."""

    __tablename__ = "framework_versions"
    __table_args__ = (
        Index("idx_framework_versions_framework", "framework_id"),
        UniqueConstraint(
            "framework_id",
            "version",
            name="uq_framework_versions_framework_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    change_type: Mapped[str] = mapped_column(CHANGE_TYPE_ENUM, nullable=False)
    change_log: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    framework: Mapped[Framework] = relationship(back_populates="versions")


class License(CreatedAtMixin, Base):
    """Operator entitlement to a Framework version.

    `transaction_id` is nullable until Phase 3 financials introduces the
    transactions table and purchase write path; that slice should add the
    foreign key and tighten nullability once every license comes from payment.
    """

    __tablename__ = "licenses"
    __table_args__ = (
        UniqueConstraint("framework_id", "operator_id", name="uq_licenses_owner"),
        Index("idx_licenses_operator", "operator_id"),
        Index("idx_licenses_framework", "framework_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id"),
        nullable=False,
    )
    operator_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    transaction_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    license_type: Mapped[str] = mapped_column(
        "type",
        LICENSE_TYPE_ENUM,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        LICENSE_STATUS_ENUM,
        nullable=False,
        server_default="active",
    )
    version_at_grant: Mapped[str] = mapped_column(String(20), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    framework: Mapped[Framework] = relationship(back_populates="licenses")
    reviews: Mapped[list[Review]] = relationship(back_populates="license")


class Review(UpdatedAtMixin, Base):
    """Operator review for a licensed Framework.

    The write flow is deferred to Phase 3 because BR-FWK-004 depends on active
    licenses created by the purchase flow.
    """

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("score BETWEEN 1 AND 5", name="ck_reviews_score_range"),
        UniqueConstraint(
            "framework_id",
            "operator_id",
            name="uq_reviews_framework_operator",
        ),
        Index("idx_reviews_framework", "framework_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    operator_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    license_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("licenses.id"),
        nullable=False,
    )
    score: Mapped[int] = mapped_column(nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    framework: Mapped[Framework] = relationship(back_populates="reviews")
    license: Mapped[License] = relationship(back_populates="reviews")
