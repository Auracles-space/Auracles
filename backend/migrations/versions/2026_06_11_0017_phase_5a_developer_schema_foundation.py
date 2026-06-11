"""Create Phase 5a developer platform schema foundation.

Supports FR-DEV-001 through FR-DEV-032 by adding Developer onboarding,
partner API key, commission, payout, outbound webhook, and API usage-log
storage. Downgrade removes the new tables/config/enums, but intentionally
leaves the additive ``developer`` role_enum label in place because removing a
PostgreSQL enum label requires a table rewrite and is unsafe after deployment.

Revision ID: 2026_06_11_0017
Revises: 2026_06_11_0016
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_11_0017"
down_revision: str | Sequence[str] | None = "2026_06_11_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

developer_application_status_enum = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    "withdrawn",
    name="developer_application_status_enum",
    create_type=False,
)
developer_account_status_enum = postgresql.ENUM(
    "active",
    "suspended",
    name="developer_account_status_enum",
    create_type=False,
)
api_key_status_enum = postgresql.ENUM(
    "active",
    "revoked",
    name="api_key_status_enum",
    create_type=False,
)
partner_commission_status_enum = postgresql.ENUM(
    "pending",
    "cleared",
    "paid",
    "voided",
    name="partner_commission_status_enum",
    create_type=False,
)
webhook_delivery_status_enum = postgresql.ENUM(
    "pending",
    "delivered",
    "failed",
    "dead",
    name="webhook_delivery_status_enum",
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

DEVELOPER_CONFIG_SEEDS = {
    "partner_tier_thresholds": (
        '{"1":{"min":0,"max":99,"rate":"0.05"},'
        '"2":{"min":100,"max":499,"rate":"0.08"},'
        '"3":{"min":500,"max":null,"rate":"0.12"}}'
    ),
    "partner_min_payout_usd": "50",
    "partner_api_log_retention_days": "90",
}


def upgrade() -> None:
    """Apply Phase 5a Slice 1 developer platform schema and config defaults."""
    bind = op.get_bind()

    op.execute("ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'developer'")

    developer_application_status_enum.create(bind, checkfirst=True)
    developer_account_status_enum.create(bind, checkfirst=True)
    api_key_status_enum.create(bind, checkfirst=True)
    partner_commission_status_enum.create(bind, checkfirst=True)
    webhook_delivery_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "developer_applications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("use_case", sa.Text(), nullable=False),
        sa.Column(
            "status",
            developer_application_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("admin_feedback", sa.Text(), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index(
        "idx_developer_applications_user_status",
        "developer_applications",
        ["user_id", "status"],
    )
    op.create_index(
        "uq_developer_applications_user_pending",
        "developer_applications",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "developer_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            developer_account_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column(
            "commission_tier",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "tier_rate",
            sa.Numeric(5, 4),
            nullable=False,
            server_default="0.0500",
        ),
        sa.Column(
            "tier_sales_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("tier_recalculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
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
        sa.CheckConstraint(
            "commission_tier IN (1, 2, 3)",
            name="ck_developer_accounts_commission_tier",
        ),
        sa.CheckConstraint(
            "tier_rate >= 0",
            name="ck_developer_accounts_tier_rate_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["developer_applications.id"]),
        sa.UniqueConstraint("user_id", name="uq_developer_accounts_user_id"),
        sa.UniqueConstraint(
            "application_id",
            name="uq_developer_accounts_application_id",
        ),
    )

    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "developer_account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "rate_limit_per_min",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "status",
            api_key_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "rate_limit_per_min > 0",
            name="ck_api_keys_rate_limit_positive",
        ),
        sa.ForeignKeyConstraint(
            ["developer_account_id"],
            ["developer_accounts.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_api_keys_developer_account",
        "api_keys",
        ["developer_account_id"],
    )
    op.create_index("idx_api_keys_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "api_request_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_ms", sa.Integer(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_api_request_logs_key_created",
        "api_request_logs",
        ["api_key_id", "created_at"],
    )

    op.create_table(
        "partner_payouts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "developer_account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("payout_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("amount > 0", name="ck_partner_payouts_amount_positive"),
        sa.ForeignKeyConstraint(
            ["developer_account_id"],
            ["developer_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["payout_account_id"], ["payout_accounts.id"]),
    )
    op.create_index(
        "idx_partner_payouts_developer_status",
        "partner_payouts",
        ["developer_account_id", "status"],
    )
    op.create_index(
        "idx_partner_payouts_payout_account",
        "partner_payouts",
        ["payout_account_id"],
    )

    op.create_table(
        "partner_commissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "developer_account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sale_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column("tier_at_sale", sa.SmallInteger(), nullable=False),
        sa.Column("tier_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("commission_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "status",
            partner_commission_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "sale_amount > 0",
            name="ck_partner_commissions_sale_amount_positive",
        ),
        sa.CheckConstraint(
            "commission_amount >= 0",
            name="ck_partner_commissions_commission_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "tier_rate >= 0",
            name="ck_partner_commissions_tier_rate_nonnegative",
        ),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(
            ["developer_account_id"],
            ["developer_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["framework_id"], ["frameworks.id"]),
        sa.ForeignKeyConstraint(["payout_id"], ["partner_payouts.id"]),
        sa.UniqueConstraint(
            "transaction_id",
            name="uq_partner_commissions_transaction",
        ),
    )
    op.create_index(
        "idx_partner_commissions_developer_status",
        "partner_commissions",
        ["developer_account_id", "status"],
    )
    op.create_index(
        "idx_partner_commissions_status_created",
        "partner_commissions",
        ["status", "created_at"],
    )

    op.create_table(
        "partner_webhooks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "developer_account_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("events", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["developer_account_id"],
            ["developer_accounts.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_partner_webhooks_developer_account",
        "partner_webhooks",
        ["developer_account_id"],
    )

    op.create_table(
        "partner_webhook_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("partner_webhook_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            webhook_delivery_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["partner_webhook_id"],
            ["partner_webhooks.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_partner_webhook_deliveries_status_next",
        "partner_webhook_deliveries",
        ["status", "next_attempt_at"],
    )

    op.bulk_insert(
        sa.table(
            "platform_config",
            sa.column("key", sa.String),
            sa.column("value", sa.Text),
        ),
        [
            {"key": key, "value": value}
            for key, value in DEVELOPER_CONFIG_SEEDS.items()
        ],
    )


def downgrade() -> None:
    """Remove Phase 5a Slice 1 developer platform schema additions."""
    bind = op.get_bind()

    op.execute(
        "DELETE FROM platform_config WHERE key IN "
        "('partner_tier_thresholds', 'partner_min_payout_usd', "
        "'partner_api_log_retention_days')"
    )

    op.drop_index(
        "idx_partner_webhook_deliveries_status_next",
        table_name="partner_webhook_deliveries",
    )
    op.drop_table("partner_webhook_deliveries")

    op.drop_index(
        "idx_partner_webhooks_developer_account",
        table_name="partner_webhooks",
    )
    op.drop_table("partner_webhooks")

    op.drop_index(
        "idx_partner_commissions_status_created",
        table_name="partner_commissions",
    )
    op.drop_index(
        "idx_partner_commissions_developer_status",
        table_name="partner_commissions",
    )
    op.drop_table("partner_commissions")

    op.drop_index(
        "idx_partner_payouts_payout_account",
        table_name="partner_payouts",
    )
    op.drop_index(
        "idx_partner_payouts_developer_status",
        table_name="partner_payouts",
    )
    op.drop_table("partner_payouts")

    op.drop_index(
        "idx_api_request_logs_key_created",
        table_name="api_request_logs",
    )
    op.drop_table("api_request_logs")

    op.drop_index("idx_api_keys_hash", table_name="api_keys")
    op.drop_index("idx_api_keys_developer_account", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_table("developer_accounts")

    op.drop_index(
        "uq_developer_applications_user_pending",
        table_name="developer_applications",
    )
    op.drop_index(
        "idx_developer_applications_user_status",
        table_name="developer_applications",
    )
    op.drop_table("developer_applications")

    webhook_delivery_status_enum.drop(bind, checkfirst=True)
    partner_commission_status_enum.drop(bind, checkfirst=True)
    api_key_status_enum.drop(bind, checkfirst=True)
    developer_account_status_enum.drop(bind, checkfirst=True)
    developer_application_status_enum.drop(bind, checkfirst=True)
