"""SQLAlchemy models for Phase 3 financial records.

The first financials slice is schema-only: it defines durable storage for
transactions, escrows, payout accounts, payouts, and admin-managed platform
configuration. Later slices add services and endpoints on top of these models.
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

TRANSACTION_TYPE_ENUM = ENUM(
    "purchase",
    "milestone",
    "attestation_fee",
    "payout",
    "refund",
    name="transaction_type_enum",
    create_type=False,
)
TRANSACTION_STATUS_ENUM = ENUM(
    "pending",
    "completed",
    "failed",
    "refunded",
    name="transaction_status_enum",
    create_type=False,
)
PAYMENT_PROVIDER_ENUM = ENUM(
    "stripe",
    "paystack",
    name="payment_provider_enum",
    create_type=False,
)
ESCROW_STATUS_ENUM = ENUM(
    "held",
    "released",
    "refunded",
    name="escrow_status_enum",
    create_type=False,
)
PAYOUT_STATUS_ENUM = ENUM(
    "pending",
    "processing",
    "completed",
    "failed",
    name="payout_status_enum",
    create_type=False,
)


class Transaction(UpdatedAtMixin, Base):
    """Money movement record created before provider-side payment handling."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint(
            "platform_commission >= 0",
            name="ck_transactions_platform_commission_nonnegative",
        ),
        CheckConstraint(
            "net_amount >= 0",
            name="ck_transactions_net_amount_nonnegative",
        ),
        CheckConstraint(
            "payee_id IS NULL OR payee_org_id IS NULL",
            name="ck_transactions_single_payee",
        ),
        Index("idx_transactions_payer", "payer_id"),
        Index("idx_transactions_payee", "payee_id"),
        Index("idx_transactions_payee_org", "payee_org_id"),
        Index("idx_transactions_status", "status"),
        Index("idx_transactions_ref", "ref_type", "ref_id"),
        Index("idx_transactions_provider_ref", "provider", "provider_ref"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    payer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    payee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    # Org beneficiary for org-attested work; mutually exclusive with payee_id.
    payee_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    platform_commission: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        server_default="0",
    )
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    transaction_type: Mapped[str] = mapped_column(
        "type",
        TRANSACTION_TYPE_ENUM,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        TRANSACTION_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    provider: Mapped[str | None] = mapped_column(PAYMENT_PROVIDER_ENUM, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ref_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    escrows: Mapped[list[Escrow]] = relationship(back_populates="transaction")


class Escrow(Base):
    """Held funds tied to a future project milestone or attestation release."""

    __tablename__ = "escrows"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_escrows_amount_positive"),
        UniqueConstraint("ref_id", "ref_type", name="uq_escrows_ref"),
        Index("idx_escrows_ref", "ref_type", "ref_id"),
        Index("idx_escrows_status", "status"),
        Index("idx_escrows_transaction", "transaction_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    ref_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    status: Mapped[str] = mapped_column(
        ESCROW_STATUS_ENUM,
        nullable=False,
        server_default="held",
    )
    release_conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("transactions.id"),
        nullable=False,
    )
    held_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    released_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    transaction: Mapped[Transaction] = relationship(back_populates="escrows")


class PayoutAccount(CreatedAtMixin, Base):
    """Provider-hosted payout destination linked to a Contributor account."""

    __tablename__ = "payout_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_account_lookup_hash",
            name="uq_payout_accounts_provider_account_lookup",
        ),
        CheckConstraint(
            "(user_id IS NULL) != (org_id IS NULL)",
            name="ck_payout_accounts_owner_xor",
        ),
        Index("idx_payout_accounts_user", "user_id"),
        Index("idx_payout_accounts_user_default", "user_id", "is_default"),
        Index("idx_payout_accounts_org", "org_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    # Exactly one of user_id / org_id owns the account (XOR CHECK).
    org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(PAYMENT_PROVIDER_ENUM, nullable=False)
    provider_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_lookup_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    account_type: Mapped[str] = mapped_column("type", String(50), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    payouts: Mapped[list[Payout]] = relationship(back_populates="payout_account")


class Payout(Base):
    """Payout request and provider transfer status for one beneficiary.

    A payout belongs to exactly one beneficiary: an individual Contributor
    (``contributor_id``) or an Organization (``org_id``) for org-attested
    earnings. The XOR CHECK enforces the single-beneficiary rule, mirroring the
    ``transactions.payee_id``/``payee_org_id`` and ``payout_accounts`` shape.
    """

    __tablename__ = "payouts"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payouts_amount_positive"),
        CheckConstraint(
            "commission_deducted >= 0",
            name="ck_payouts_commission_deducted_nonnegative",
        ),
        CheckConstraint(
            "net_amount >= 0",
            name="ck_payouts_net_amount_nonnegative",
        ),
        CheckConstraint(
            "(contributor_id IS NULL) != (org_id IS NULL)",
            name="ck_payouts_beneficiary_xor",
        ),
        Index("idx_payouts_contributor", "contributor_id"),
        Index("idx_payouts_org", "org_id"),
        Index("idx_payouts_status", "status"),
        Index("idx_payouts_provider_ref", "provider_ref"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contributor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    # Org beneficiary for org-attested earnings; XOR with contributor_id.
    org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
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
    commission_deducted: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
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

    payout_account: Mapped[PayoutAccount] = relationship(back_populates="payouts")


class PlatformConfig(Base):
    """Mutable platform-wide financial configuration row."""

    __tablename__ = "platform_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
