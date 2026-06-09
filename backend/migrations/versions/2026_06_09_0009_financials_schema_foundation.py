"""Create Phase 3 financials schema foundation.

Revision ID: 2026_06_09_0009
Revises: 2026_06_08_0008
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_09_0009"
down_revision: str | Sequence[str] | None = "2026_06_08_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

transaction_type_enum = postgresql.ENUM(
    "purchase",
    "milestone",
    "attestation_fee",
    "payout",
    "refund",
    name="transaction_type_enum",
    create_type=False,
)
transaction_status_enum = postgresql.ENUM(
    "pending",
    "completed",
    "failed",
    "refunded",
    name="transaction_status_enum",
    create_type=False,
)
payment_provider_enum = postgresql.ENUM(
    "stripe",
    "paystack",
    name="payment_provider_enum",
    create_type=False,
)
escrow_status_enum = postgresql.ENUM(
    "held",
    "released",
    "refunded",
    name="escrow_status_enum",
    create_type=False,
)
payout_status_enum = postgresql.ENUM(
    "pending",
    "processing",
    "completed",
    "failed",
    name="payout_status_enum",
    create_type=False,
)
webhook_event_status_enum = postgresql.ENUM(
    "received",
    "processed",
    "failed",
    name="webhook_event_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Apply Phase 3 Slice 1 payment, payout, escrow, and webhook schema."""
    bind = op.get_bind()

    # License types are expanded additively to preserve Phase 2 grants.
    op.execute("ALTER TYPE license_type_enum ADD VALUE IF NOT EXISTS 'organizational'")

    transaction_type_enum.create(bind, checkfirst=True)
    transaction_status_enum.create(bind, checkfirst=True)
    payment_provider_enum.create(bind, checkfirst=True)
    escrow_status_enum.create(bind, checkfirst=True)
    payout_status_enum.create(bind, checkfirst=True)
    webhook_event_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "users",
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "idx_users_stripe_customer_id",
        "users",
        ["stripe_customer_id"],
    )

    op.create_table(
        "transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("payer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "platform_commission",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("net_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("type", transaction_type_enum, nullable=False),
        sa.Column(
            "status",
            transaction_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("provider", payment_provider_enum, nullable=True),
        sa.Column("provider_ref", sa.String(length=255), nullable=True),
        sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ref_type", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint(
            "platform_commission >= 0",
            name="ck_transactions_platform_commission_nonnegative",
        ),
        sa.CheckConstraint(
            "net_amount >= 0",
            name="ck_transactions_net_amount_nonnegative",
        ),
        sa.ForeignKeyConstraint(["payer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["payee_id"], ["users.id"]),
    )
    op.create_index("idx_transactions_payer", "transactions", ["payer_id"])
    op.create_index("idx_transactions_payee", "transactions", ["payee_id"])
    op.create_index("idx_transactions_status", "transactions", ["status"])
    op.create_index("idx_transactions_ref", "transactions", ["ref_type", "ref_id"])
    op.create_index(
        "idx_transactions_provider_ref",
        "transactions",
        ["provider", "provider_ref"],
    )

    op.create_table(
        "escrows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ref_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ref_type", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "status",
            escrow_status_enum,
            nullable=False,
            server_default="held",
        ),
        sa.Column(
            "release_conditions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "held_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_escrows_amount_positive"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["released_by"], ["users.id"]),
        sa.UniqueConstraint("ref_id", "ref_type", name="uq_escrows_ref"),
    )
    op.create_index("idx_escrows_ref", "escrows", ["ref_type", "ref_id"])
    op.create_index("idx_escrows_status", "escrows", ["status"])
    op.create_index("idx_escrows_transaction", "escrows", ["transaction_id"])

    op.create_table(
        "payout_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", payment_provider_enum, nullable=False),
        # Stored value is encrypted by the service before insert/update.
        sa.Column("provider_account_id", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_payout_accounts_provider_account",
        ),
    )
    op.create_index("idx_payout_accounts_user", "payout_accounts", ["user_id"])
    op.create_index(
        "idx_payout_accounts_user_default",
        "payout_accounts",
        ["user_id", "is_default"],
    )

    op.create_table(
        "payouts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("contributor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payout_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column("commission_deducted", sa.Numeric(12, 2), nullable=False),
        sa.Column("net_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "status",
            payout_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("provider_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "initiated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_payouts_amount_positive"),
        sa.CheckConstraint(
            "commission_deducted >= 0",
            name="ck_payouts_commission_deducted_nonnegative",
        ),
        sa.CheckConstraint(
            "net_amount >= 0",
            name="ck_payouts_net_amount_nonnegative",
        ),
        sa.ForeignKeyConstraint(["contributor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["payout_account_id"], ["payout_accounts.id"]),
    )
    op.create_index("idx_payouts_contributor", "payouts", ["contributor_id"])
    op.create_index("idx_payouts_status", "payouts", ["status"])
    op.create_index("idx_payouts_provider_ref", "payouts", ["provider_ref"])

    op.create_table(
        "webhook_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", payment_provider_enum, nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            webhook_event_status_enum,
            nullable=False,
            server_default="received",
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_webhook_events_provider_event",
        ),
    )
    op.create_index("idx_webhook_events_status", "webhook_events", ["status"])
    op.create_index(
        "idx_webhook_events_received_at",
        "webhook_events",
        ["received_at"],
    )

    op.create_table(
        "platform_config",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
    )

    op.bulk_insert(
        sa.table(
            "platform_config",
            sa.column("key", sa.String),
            sa.column("value", sa.Text),
        ),
        [
            {"key": "commission_rate", "value": "0.15"},
            {"key": "min_payout_usd", "value": "50"},
            {"key": "min_payout_ngn", "value": "20000"},
            {"key": "refund_window_hours", "value": "48"},
        ],
    )

    op.create_foreign_key(
        "fk_licenses_transaction_id_transactions",
        "licenses",
        "transactions",
        ["transaction_id"],
        ["id"],
    )


def downgrade() -> None:
    """Remove Phase 3 Slice 1 financial schema additions."""
    bind = op.get_bind()

    op.drop_constraint(
        "fk_licenses_transaction_id_transactions",
        "licenses",
        type_="foreignkey",
    )

    op.drop_table("platform_config")

    op.drop_index("idx_webhook_events_received_at", table_name="webhook_events")
    op.drop_index("idx_webhook_events_status", table_name="webhook_events")
    op.drop_table("webhook_events")

    op.drop_index("idx_payouts_provider_ref", table_name="payouts")
    op.drop_index("idx_payouts_status", table_name="payouts")
    op.drop_index("idx_payouts_contributor", table_name="payouts")
    op.drop_table("payouts")

    op.drop_index("idx_payout_accounts_user_default", table_name="payout_accounts")
    op.drop_index("idx_payout_accounts_user", table_name="payout_accounts")
    op.drop_table("payout_accounts")

    op.drop_index("idx_escrows_transaction", table_name="escrows")
    op.drop_index("idx_escrows_status", table_name="escrows")
    op.drop_index("idx_escrows_ref", table_name="escrows")
    op.drop_table("escrows")

    op.drop_index("idx_transactions_provider_ref", table_name="transactions")
    op.drop_index("idx_transactions_ref", table_name="transactions")
    op.drop_index("idx_transactions_status", table_name="transactions")
    op.drop_index("idx_transactions_payee", table_name="transactions")
    op.drop_index("idx_transactions_payer", table_name="transactions")
    op.drop_table("transactions")

    op.drop_index("idx_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "stripe_customer_id")

    # PostgreSQL cannot drop a single enum label. While Phase 3 has no real
    # records, recreate the type so downgrade returns exactly to Phase 2.
    op.execute(
        """
        ALTER TABLE frameworks
        ALTER COLUMN license_types TYPE text[]
        USING license_types::text[]
        """
    )
    op.execute(
        """
        ALTER TABLE licenses
        ALTER COLUMN type TYPE text
        USING type::text
        """
    )
    op.execute("DROP TYPE license_type_enum")
    op.execute(
        "CREATE TYPE license_type_enum AS ENUM ('single_user', 'team', 'enterprise')"
    )
    op.execute(
        """
        ALTER TABLE licenses
        ALTER COLUMN type TYPE license_type_enum
        USING type::license_type_enum
        """
    )
    op.execute(
        """
        ALTER TABLE frameworks
        ALTER COLUMN license_types TYPE license_type_enum[]
        USING license_types::text[]::license_type_enum[]
        """
    )

    webhook_event_status_enum.drop(bind, checkfirst=True)
    payout_status_enum.drop(bind, checkfirst=True)
    escrow_status_enum.drop(bind, checkfirst=True)
    payment_provider_enum.drop(bind, checkfirst=True)
    transaction_status_enum.drop(bind, checkfirst=True)
    transaction_type_enum.drop(bind, checkfirst=True)
