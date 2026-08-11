"""Add the provider-neutral financial events ledger.

Money state today is stored only as a current value: `transactions.status` and
`payouts.status` are overwritten in place, so a failed payment cannot be
reconstructed and every failure looks alike. This ledger records one immutable
row per money state change, carrying the transition (`from_status` ->
`to_status`) and a normalized failure cause (`reason_code` / `reason_message`)
that each provider adapter maps into, so Stripe and Paystack failures are
queryable through one shape.

`audit_logs` cannot serve this: it is actor-centric, and money events are
already spread across several `target_type` values, so per-payment history
there needs an unindexed scan over JSONB metadata.

Maps to: FR-FIN-* payment traceability.

Revision ID: 2026_08_11_0092
Revises: 2026_07_19_0091
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_08_11_0092"
down_revision: str | Sequence[str] | None = "2026_07_19_0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Money objects whose state changes are traceable. Kept as a CHECK rather than a
# PostgreSQL ENUM so adding an entity type stays an ordinary migration instead of
# an ALTER TYPE that cannot run inside a transaction.
_ENTITY_TYPES = (
    "transaction",
    "escrow",
    "payout",
    "partner_commission",
    "partner_payout",
)


def upgrade() -> None:
    """Create the append-only financial events ledger and its lookup indexes."""
    entity_type_values = ", ".join(f"'{value}'" for value in _ENTITY_TYPES)
    op.create_table(
        "financial_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        # Null on creation events, where there is no prior state to record.
        sa.Column("from_status", sa.String(length=50), nullable=True),
        sa.Column("to_status", sa.String(length=50), nullable=True),
        # Null for events that change state without moving money.
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "provider",
            postgresql.ENUM(
                "stripe",
                "paystack",
                name="payment_provider_enum",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("provider_ref", sa.String(length=255), nullable=True),
        # Normalized across providers; the raw provider code stays in metadata.
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("reason_message", sa.Text(), nullable=True),
        # Null when the provider or a scheduled task drove the change, not a user.
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        # clock_timestamp(), not now(): now() is transaction-start time, so a
        # release and its payout written in one commit would share a timestamp
        # and the timeline could not be ordered.
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount > 0",
            name="ck_financial_events_amount_positive",
        ),
        sa.CheckConstraint(
            "(amount IS NULL) = (currency IS NULL)",
            name="ck_financial_events_currency_with_amount",
        ),
        sa.CheckConstraint(
            f"entity_type IN ({entity_type_values})",
            name="ck_financial_events_entity_type",
        ),
    )
    # The trace query: one payment's history, in order.
    op.create_index(
        "idx_financial_events_entity",
        "financial_events",
        ["entity_type", "entity_id", "occurred_at"],
    )
    op.create_index(
        "idx_financial_events_occurred_at",
        "financial_events",
        ["occurred_at"],
    )
    # Serves the admin failure feed: all events of one type, newest first.
    op.create_index(
        "idx_financial_events_event_type",
        "financial_events",
        ["event_type", "occurred_at"],
    )
    # Reconciliation against a provider dashboard by charge/transfer reference.
    op.create_index(
        "idx_financial_events_provider_ref",
        "financial_events",
        ["provider", "provider_ref"],
    )


def downgrade() -> None:
    """Drop the financial events ledger."""
    op.drop_index("idx_financial_events_provider_ref", table_name="financial_events")
    op.drop_index("idx_financial_events_event_type", table_name="financial_events")
    op.drop_index("idx_financial_events_occurred_at", table_name="financial_events")
    op.drop_index("idx_financial_events_entity", table_name="financial_events")
    op.drop_table("financial_events")
