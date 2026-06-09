"""Add payout account lookup hash.

Revision ID: 2026_06_09_0010
Revises: 2026_06_09_0009
Create Date: 2026-06-09 21:30:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "2026_06_09_0010"
down_revision = "2026_06_09_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store a keyed lookup hash beside encrypted payout provider ids."""
    op.execute(
        """
        ALTER TABLE payout_accounts
        ADD COLUMN IF NOT EXISTS provider_account_lookup_hash VARCHAR(64)
        """
    )
    # Existing non-production rows predate encryption. Backfill a stable
    # placeholder from their stored value so the NOT NULL constraint can apply.
    op.execute(
        """
        UPDATE payout_accounts
        SET provider_account_lookup_hash = encode(
            digest(provider_account_id, 'sha256'),
            'hex'
        )
        WHERE provider_account_lookup_hash IS NULL
        """
    )
    op.alter_column(
        "payout_accounts",
        "provider_account_lookup_hash",
        nullable=False,
    )
    op.execute(
        """
        ALTER TABLE payout_accounts
        DROP CONSTRAINT IF EXISTS uq_payout_accounts_provider_account
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_payout_accounts_provider_account_lookup'
            ) THEN
                ALTER TABLE payout_accounts
                ADD CONSTRAINT uq_payout_accounts_provider_account_lookup
                UNIQUE (provider, provider_account_lookup_hash);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Remove payout account lookup hash metadata."""
    op.execute(
        """
        ALTER TABLE payout_accounts
        DROP CONSTRAINT IF EXISTS uq_payout_accounts_provider_account_lookup
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_payout_accounts_provider_account'
            ) THEN
                ALTER TABLE payout_accounts
                ADD CONSTRAINT uq_payout_accounts_provider_account
                UNIQUE (provider, provider_account_id);
            END IF;
        END $$;
        """
    )
    op.drop_column("payout_accounts", "provider_account_lookup_hash")
