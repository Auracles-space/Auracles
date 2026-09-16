"""SQLAlchemy models for Phase 5a developer platform records.

Slice 1 is schema-only: these models define Developer applications, accounts,
API keys, partner-attributed commissions, partner payouts, outbound webhooks,
API request logs, and purchase attribution before lifecycle services and
endpoints are added.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.modules.financials.models import PAYOUT_STATUS_ENUM
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

DEVELOPER_APPLICATION_STATUS_ENUM = ENUM(
    "pending",
    "approved",
    "rejected",
    "withdrawn",
    name="developer_application_status_enum",
    create_type=False,
)
DEVELOPER_ACCOUNT_STATUS_ENUM = ENUM(
    "active",
    "suspended",
    name="developer_account_status_enum",
    create_type=False,
)
API_KEY_STATUS_ENUM = ENUM(
    "active",
    "revoked",
    name="api_key_status_enum",
    create_type=False,
)
PARTNER_COMMISSION_STATUS_ENUM = ENUM(
    "pending",
    "cleared",
    "paid",
    "voided",
    name="partner_commission_status_enum",
    create_type=False,
)
WEBHOOK_DELIVERY_STATUS_ENUM = ENUM(
    "pending",
    "delivered",
    "failed",
    "dead",
    name="webhook_delivery_status_enum",
    create_type=False,
)


class DeveloperApplication(CreatedAtMixin, Base):
    """Submitted Developer role application awaiting admin review."""

    __tablename__ = "developer_applications"
    __table_args__ = (
        Index("idx_developer_applications_user_status", "user_id", "status"),
        Index(
            "uq_developer_applications_user_pending",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
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
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    use_case: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        DEVELOPER_APPLICATION_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    admin_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DeveloperAccount(UpdatedAtMixin, Base):
    """Approved partner developer account used for API access and commissions."""

    __tablename__ = "developer_accounts"
    __table_args__ = (
        CheckConstraint(
            "commission_tier IN (1, 2, 3)",
            name="ck_developer_accounts_commission_tier",
        ),
        CheckConstraint(
            "tier_rate >= 0",
            name="ck_developer_accounts_tier_rate_nonnegative",
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
        unique=True,
    )
    status: Mapped[str] = mapped_column(
        DEVELOPER_ACCOUNT_STATUS_ENUM,
        nullable=False,
        server_default="active",
    )
    application_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("developer_applications.id"),
        nullable=False,
        unique=True,
    )
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    commission_tier: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default="1",
    )
    tier_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        server_default="0.0500",
    )
    tier_sales_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    tier_recalculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="developer_account")


class ApiKey(CreatedAtMixin, Base):
    """Hashed partner API credential shown raw only at creation time."""

    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "rate_limit_per_min > 0",
            name="ck_api_keys_rate_limit_positive",
        ),
        Index("idx_api_keys_developer_account", "developer_account_id"),
        Index("idx_api_keys_hash", "key_hash", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    developer_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("developer_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    rate_limit_per_min: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="60",
    )
    status: Mapped[str] = mapped_column(
        API_KEY_STATUS_ENUM,
        nullable=False,
        server_default="active",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    developer_account: Mapped[DeveloperAccount] = relationship(
        back_populates="api_keys",
    )
    request_logs: Mapped[list[ApiRequestLog]] = relationship(back_populates="api_key")
    purchase_attributions: Mapped[list[PartnerPurchaseAttribution]] = relationship(
        back_populates="api_key",
    )
    commissions: Mapped[list[PartnerCommission]] = relationship(
        back_populates="api_key",
    )


class ApiRequestLog(Base):
    """Per-request API usage record for partner analytics and retention pruning."""

    __tablename__ = "api_request_logs"
    __table_args__ = (
        Index("idx_api_request_logs_key_created", "api_key_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    api_key_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    api_key: Mapped[ApiKey] = relationship(back_populates="request_logs")


class PartnerPurchaseAttribution(CreatedAtMixin, Base):
    """Pending purchase attribution from a Partner API key to a transaction."""

    __tablename__ = "partner_purchase_attributions"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_partner_purchase_attr_transaction"),
        Index(
            "idx_partner_purchase_attr_key_transaction",
            "api_key_id",
            "transaction_id",
        ),
        Index(
            "idx_partner_purchase_attr_developer",
            "developer_account_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    api_key_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("api_keys.id"),
        nullable=False,
    )
    developer_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("developer_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("transactions.id"),
        nullable=False,
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id"),
        nullable=False,
    )
    buyer_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    license_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tier_at_sale: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    tier_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    api_key: Mapped[ApiKey] = relationship(back_populates="purchase_attributions")


class PartnerPayout(Base):
    """Partner commission withdrawal request using a verified payout account."""

    __tablename__ = "partner_payouts"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_partner_payouts_amount_positive"),
        Index("idx_partner_payouts_developer_status", "developer_account_id", "status"),
        Index("idx_partner_payouts_payout_account", "payout_account_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    developer_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("developer_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    payout_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payout_accounts.id"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    status: Mapped[str] = mapped_column(
        PAYOUT_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    provider_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    initiated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    commissions: Mapped[list[PartnerCommission]] = relationship(
        back_populates="payout",
    )


class PartnerCommission(CreatedAtMixin, Base):
    """Partner commission ledger row snapshotted at attributed sale time."""

    __tablename__ = "partner_commissions"
    __table_args__ = (
        CheckConstraint(
            "sale_amount > 0",
            name="ck_partner_commissions_sale_amount_positive",
        ),
        CheckConstraint(
            "commission_amount >= 0",
            name="ck_partner_commissions_commission_amount_nonnegative",
        ),
        CheckConstraint(
            "tier_rate >= 0",
            name="ck_partner_commissions_tier_rate_nonnegative",
        ),
        UniqueConstraint("transaction_id", name="uq_partner_commissions_transaction"),
        Index(
            "idx_partner_commissions_developer_status",
            "developer_account_id",
            "status",
        ),
        Index("idx_partner_commissions_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    api_key_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("api_keys.id"),
        nullable=False,
    )
    developer_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("developer_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("transactions.id"),
        nullable=False,
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id"),
        nullable=False,
    )
    sale_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    tier_at_sale: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    tier_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        PARTNER_COMMISSION_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    # When the commission was voided; cleared if a declined refund reinstates
    # it. Treasury statements count the commission as a cost until then.
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    payout_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("partner_payouts.id"),
        nullable=True,
    )

    api_key: Mapped[ApiKey] = relationship(back_populates="commissions")
    payout: Mapped[PartnerPayout | None] = relationship(back_populates="commissions")


class PartnerWebhook(CreatedAtMixin, Base):
    """Outbound webhook endpoint registered by a Developer account."""

    __tablename__ = "partner_webhooks"
    __table_args__ = (
        Index("idx_partner_webhooks_developer_account", "developer_account_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    developer_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("developer_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )

    deliveries: Mapped[list[PartnerWebhookDelivery]] = relationship(
        back_populates="webhook",
    )


class PartnerWebhookDelivery(CreatedAtMixin, Base):
    """Queued outbound webhook delivery attempt with retry/dead-letter state."""

    __tablename__ = "partner_webhook_deliveries"
    __table_args__ = (
        Index(
            "idx_partner_webhook_deliveries_status_next",
            "status",
            "next_attempt_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    partner_webhook_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("partner_webhooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        WEBHOOK_DELIVERY_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    webhook: Mapped[PartnerWebhook] = relationship(back_populates="deliveries")
