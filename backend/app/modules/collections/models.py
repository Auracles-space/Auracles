"""SQLAlchemy models for Framework Collections.

Defines the Phase 5b-1 collection bundle schema: contributor-owned bundle
records, member Framework joins, purchase snapshots, and per-framework earning
allocations used by later checkout, webhook, and refund slices.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.modules.frameworks.models import LICENSE_TYPE_ENUM
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

COLLECTION_STATUS_ENUM = ENUM(
    "draft",
    "published",
    "unpublished",
    name="collection_status_enum",
    create_type=False,
)


class FrameworkCollection(UpdatedAtMixin, Base):
    """Contributor-owned bundle of published Frameworks sold at a discount."""

    __tablename__ = "framework_collections"
    __table_args__ = (
        CheckConstraint(
            "bundle_price > 0",
            name="ck_framework_collections_bundle_price_positive",
        ),
        CheckConstraint(
            "currency = 'USD'",
            name="ck_framework_collections_currency_usd",
        ),
        Index(
            "idx_framework_collections_contributor_status",
            "contributor_id",
            "status",
        ),
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
    bundle_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    status: Mapped[str] = mapped_column(
        COLLECTION_STATUS_ENUM,
        nullable=False,
        server_default="draft",
    )

    members: Mapped[list[CollectionFramework]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
    )
    purchase_snapshots: Mapped[list[CollectionPurchaseSnapshot]] = relationship(
        back_populates="collection",
    )
    earning_allocations: Mapped[list[CollectionEarningAllocation]] = relationship(
        back_populates="collection",
    )


class CollectionFramework(Base):
    """Join row connecting one Collection to one member Framework."""

    __tablename__ = "collection_frameworks"
    __table_args__ = (
        Index("idx_collection_frameworks_framework", "framework_id"),
    )

    collection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("framework_collections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        primary_key=True,
    )

    collection: Mapped[FrameworkCollection] = relationship(back_populates="members")


class CollectionPurchaseSnapshot(CreatedAtMixin, Base):
    """Checkout-time member snapshot used by collection purchase webhooks."""

    __tablename__ = "collection_purchase_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id",
            "framework_id",
            name="uq_collection_purchase_snapshots_transaction_framework",
        ),
        Index("idx_collection_purchase_snapshots_collection", "collection_id"),
        Index("idx_collection_purchase_snapshots_framework", "framework_id"),
        Index("idx_collection_purchase_snapshots_transaction", "transaction_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("transactions.id"),
        nullable=False,
    )
    collection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("framework_collections.id"),
        nullable=False,
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id"),
        nullable=False,
    )
    list_price_at_purchase: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    license_type: Mapped[str] = mapped_column(LICENSE_TYPE_ENUM, nullable=False)
    already_owned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    collection: Mapped[FrameworkCollection] = relationship(
        back_populates="purchase_snapshots",
    )


class CollectionEarningAllocation(CreatedAtMixin, Base):
    """Per-Framework allocation row for a completed collection purchase."""

    __tablename__ = "collection_earning_allocations"
    __table_args__ = (
        CheckConstraint(
            "allocated_amount >= 0",
            name="ck_collection_earning_allocations_amount_nonnegative",
        ),
        Index("idx_collection_earning_allocations_transaction", "transaction_id"),
        Index("idx_collection_earning_allocations_collection", "collection_id"),
        Index("idx_collection_earning_allocations_framework", "framework_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("transactions.id"),
        nullable=False,
    )
    collection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("framework_collections.id"),
        nullable=False,
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id"),
        nullable=False,
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    collection: Mapped[FrameworkCollection] = relationship(
        back_populates="earning_allocations",
    )
