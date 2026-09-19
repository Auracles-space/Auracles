"""Scope payout account uniqueness to the owner instead of the platform.

One bank account could only ever be registered once anywhere on the platform.
That refused the ordinary case — a sole trader whose personal payout account
and their organization's are the same NUBAN — because Paystack returns the
same transfer recipient code for a repeated account number, so the second
owner collided on the lookup hash. The rule predates `org_id` existing on this
table (it came from 2026_06_09_0009, when only a user could own an account)
and was never a deliberate control: it blocks the honest duplicate while a
second bank account defeats it entirely.

Uniqueness now applies per owner, and only among live rows, so removing a
payout account also frees its bank account to be registered again — the
recovery path offered to anyone who mistypes an account number.

Revision ID: 2026_09_19_0118
Revises: 2026_09_18_0117
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_19_0118"
down_revision: str | Sequence[str] | None = "2026_09_18_0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the platform-wide unique with per-owner partial uniques."""
    op.execute(
        """
        ALTER TABLE payout_accounts
        DROP CONSTRAINT IF EXISTS uq_payout_accounts_provider_account_lookup
        """
    )
    # Partial, so a soft-deleted row stops reserving the bank account, and
    # separate per owner column because the XOR check leaves the other NULL —
    # NULLs are never equal in a unique index, which would defeat a single
    # index spanning both.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payout_accounts_user_lookup
        ON payout_accounts (provider, provider_account_lookup_hash, user_id)
        WHERE user_id IS NOT NULL AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_payout_accounts_org_lookup
        ON payout_accounts (provider, provider_account_lookup_hash, org_id)
        WHERE org_id IS NOT NULL AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    """Restore platform-wide uniqueness across provider account lookups.

    Rows that legitimately share a bank account under this revision violate the
    restored constraint, which spans soft-deleted rows as well. Payouts carry a
    foreign key to this table, so the losing rows are retired rather than
    removed: the oldest live row keeps the bank account, and every other row
    surrenders its lookup hash to a per-row placeholder and is soft-deleted.
    Those rows can no longer be matched to the bank account by hash, which is
    the price of going back.
    """
    op.execute("DROP INDEX IF EXISTS uq_payout_accounts_user_lookup")
    op.execute("DROP INDEX IF EXISTS uq_payout_accounts_org_lookup")
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY provider, provider_account_lookup_hash
                    ORDER BY (deleted_at IS NOT NULL), created_at, id
                ) AS position
            FROM payout_accounts
        )
        UPDATE payout_accounts AS account
        SET provider_account_lookup_hash =
                'superseded-' || replace(account.id::text, '-', ''),
            deleted_at = COALESCE(account.deleted_at, now()),
            is_default = false
        FROM ranked
        WHERE ranked.id = account.id
          AND ranked.position > 1
        """
    )
    op.execute(
        """
        ALTER TABLE payout_accounts
        ADD CONSTRAINT uq_payout_accounts_provider_account_lookup
        UNIQUE (provider, provider_account_lookup_hash)
        """
    )
