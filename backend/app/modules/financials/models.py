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
        CheckConstraint(
            "(payer_id IS NULL) != (payer_org_id IS NULL)",
            name="ck_transactions_payer_xor",
        ),
        Index("idx_transactions_payer", "payer_id"),
        Index("idx_transactions_payer_org", "payer_org_id"),
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
    payer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    payer_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
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
    # When the escrow was refunded; cleared if the provider declines the refund.
    # Treasury statements need it to know the money was still held before then.
    refunded_at: Mapped[datetime | None] = mapped_column(
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
        # Uniqueness is per owner, not per platform: one bank account may back
        # a person and their organizations at once, which is the ordinary sole
        # trader case and the only shape Paystack can express, since it returns
        # the same recipient code for a repeated account number. Partial on
        # deleted_at so removing an account releases the bank account for
        # re-registration. Two indexes because the XOR leaves the other owner
        # column NULL, and NULLs never collide in a unique index.
        Index(
            "uq_payout_accounts_user_lookup",
            "provider",
            "provider_account_lookup_hash",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_payout_accounts_org_lookup",
            "provider",
            "provider_account_lookup_hash",
            "org_id",
            unique=True,
            postgresql_where=text("org_id IS NOT NULL AND deleted_at IS NULL"),
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
    # Paystack accepted the transfer but is holding it for a one-time code
    # (transfer OTP is on for the account); cleared when the transfer settles.
    awaiting_otp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
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


class FinancialEvent(Base):
    """One immutable record of a money state change, across any provider.

    Rows are append-only: nothing in the application updates or deletes them,
    because the ledger's value is that it still shows what happened after a
    status column has been overwritten. `reason_code` is normalized by the
    provider adapters so a Stripe decline and a Paystack decline are queryable
    through one vocabulary, while the raw provider code stays in `metadata_`.

    Written only through `app.modules.financials.ledger.record_financial_event`,
    which validates the money fields and strips sensitive keys from metadata.
    """

    __tablename__ = "financial_events"
    __table_args__ = (
        CheckConstraint(
            "amount IS NULL OR amount > 0",
            name="ck_financial_events_amount_positive",
        ),
        CheckConstraint(
            "(amount IS NULL) = (currency IS NULL)",
            name="ck_financial_events_currency_with_amount",
        ),
        CheckConstraint(
            "entity_type IN ('transaction', 'escrow', 'payout', "
            "'partner_commission', 'partner_payout', 'payout_account')",
            name="ck_financial_events_entity_type",
        ),
        Index("idx_financial_events_entity", "entity_type", "entity_id", "occurred_at"),
        Index("idx_financial_events_occurred_at", "occurred_at"),
        Index("idx_financial_events_event_type", "event_type", "occurred_at"),
        Index("idx_financial_events_provider_ref", "provider", "provider_ref"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Null on creation events, where there is no prior state to record.
    from_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Null for state changes that do not move money.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    provider: Mapped[str | None] = mapped_column(PAYMENT_PROVIDER_ENUM, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Null when a provider webhook or scheduled task drove the change.
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    # clock_timestamp() advances per statement; now() is transaction-start time
    # and would collapse events written in the same commit onto one timestamp.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )


class ProviderFee(Base):
    """One fee a payment provider kept on a charge or transfer.

    The platform absorbs provider fees, so each one is a platform cost that
    Treasury subtracts from commission. Rows are append-only and keyed by the
    provider reference the fee was charged on: a webhook redelivery or the
    backfill cannot count a fee twice, while a second, distinct charge against
    the same transaction (a double charge) is a second real cost.

    ``source_id`` is polymorphic (a transaction, payout, partner payout or
    platform withdrawal) and therefore not a foreign key.

    Written only through
    ``app.modules.financials.provider_fees.record_provider_fee``.
    """

    __tablename__ = "provider_fees"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_provider_fees_amount_positive"),
        CheckConstraint(
            "source_type IN ('transaction', 'payout', 'partner_payout', "
            "'platform_withdrawal')",
            name="ck_provider_fees_source_type",
        ),
        CheckConstraint(
            "origin IN ('webhook', 'backfill')",
            name="ck_provider_fees_origin",
        ),
        UniqueConstraint(
            "provider",
            "source_type",
            "provider_ref",
            name="uq_provider_fees_provider_source_ref",
        ),
        Index("idx_provider_fees_source", "source_type", "source_id"),
        Index("idx_provider_fees_currency_occurred_at", "currency", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(PAYMENT_PROVIDER_ENUM, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    # Provider-side time, so statement months follow when the fee was charged
    # rather than when a backfill happened to record it.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PlatformBankAccount(Base):
    """The bank account the platform withdraws its own money to.

    Rows are never edited: a change inserts a new row and stamps
    ``replaced_at`` on the previous one, so every destination the platform's
    money could have been sent to stays on record. At most one row is active
    (``replaced_at IS NULL``), enforced by a partial unique index.

    Only the bank-confirmed name, bank and last four digits are kept in the
    clear. The Paystack recipient code — the only thing a transfer needs — is
    encrypted; the full account number is not stored at all.
    """

    __tablename__ = "platform_bank_accounts"
    __table_args__ = (
        CheckConstraint(
            "account_last4 ~ '^[0-9]{4}$'",
            name="ck_platform_bank_accounts_last4_digits",
        ),
        Index(
            "uq_platform_bank_accounts_active",
            text("(replaced_at IS NULL)"),
            unique=True,
            postgresql_where=text("replaced_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(PAYMENT_PROVIDER_ENUM, nullable=False)
    bank_code: Mapped[str] = mapped_column(String(20), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_code_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # A withdrawal to this account is refused before this time (decision 3).
    usable_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    replaced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PlatformWithdrawal(Base):
    """One transfer of the platform's own money to its bank account.

    ``pending`` → ``processing`` once Paystack accepted the transfer, then
    ``completed`` or ``failed`` from the transfer webhook. Pending, processing
    and completed withdrawals all count against the platform's money; a failed
    one does not, which is how its amount returns to withdrawable (decision 8).

    A partial unique index allows at most one pending or processing withdrawal
    per currency, so two racing requests cannot both pass the balance check.
    ``provider_ref`` is our own ``platform-withdrawal-<id>`` reference: the
    idempotency key for the transfer and the value the webhook carries back.
    """

    __tablename__ = "platform_withdrawals"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_platform_withdrawals_amount_positive"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_platform_withdrawals_status",
        ),
        Index(
            "uq_platform_withdrawals_one_in_flight",
            "currency",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
        Index("idx_platform_withdrawals_requested_at", "requested_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    bank_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("platform_bank_accounts.id"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Paystack accepted the transfer but is holding it for a one-time code
    # (transfer OTP is on for the account). No webhook follows until someone
    # finalizes it, so the page says so instead of showing plain processing.
    awaiting_otp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    requested_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UnrecognizedTransfer(Base):
    """A provider transfer out of the platform balance that Auracles did not start.

    Recorded when a transfer webhook matches no payout or platform withdrawal,
    for example a transfer made directly from the Paystack dashboard. One row
    per transfer reference: later events for the same transfer (a reversal)
    update ``event_type`` but never raise a second alert. Stays on Treasury
    until the super-admin marks it reviewed.
    """

    __tablename__ = "unrecognized_transfers"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_ref", name="uq_unrecognized_transfers_ref"
        ),
        Index(
            "idx_unrecognized_transfers_unreviewed",
            "created_at",
            postgresql_where=text("acknowledged_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(PAYMENT_PROVIDER_ENUM, nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # Enough to identify where the money went; never the full account number.
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_bank: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    acknowledged_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


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
