"""Org re-point columns on attestation and financial tables (wave 2).

Additive columns from the Organizations-as-Attestors sub-project
(docs/superpowers/specs/2026-07-04-org-attestor-design.md, re-pointed
columns block): attestations gain the org assignee and internal
reviewing member, offers and trials gain org keys, payout accounts
gain org ownership under an XOR CHECK, and transactions gain an org
beneficiary under a single-payee CHECK. Legacy individual columns are
only relaxed to nullable here; they are dropped in the final reviewed
retirement migration.

Note: the plan text expected ``attestor_trials.user_id``, but the table
keys on ``application_id`` (FK attestor_applications). That column is
relaxed instead, and ``org_application_id`` links org trials to
``org_attestor_applications``.

Downgrade restores NOT NULL on the relaxed columns directly; acceptable
on the dev database because no org rows (which would hold NULLs there)
exist before this wave ships.

Revision ID: 2026_07_04_0064
Revises: 2026_07_04_0063
Create Date: 2026-07-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_04_0064"
down_revision: str | Sequence[str] | None = "2026_07_04_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add org re-point columns, checks, and indexes."""
    op.add_column(
        "attestations",
        sa.Column(
            "attestor_org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_attestations_attestor_org_id_organizations",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "attestations",
        sa.Column(
            "reviewing_member_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "org_members.id",
                name="fk_attestations_reviewing_member_id_org_members",
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_attestations_attestor_org_status",
        "attestations",
        ["attestor_org_id", "status"],
    )

    op.add_column(
        "attestation_offers",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_attestation_offers_org_id_organizations",
            ),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_attestation_offers_attestation_org",
        "attestation_offers",
        ["attestation_id", "org_id"],
    )
    op.alter_column("attestation_offers", "attestor_id", nullable=True)

    op.add_column(
        "attestor_trials",
        sa.Column(
            "org_application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "org_attestor_applications.id",
                name="fk_attestor_trials_org_application_id",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "attestor_trials",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_attestor_trials_org_id_organizations",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "attestor_trials",
        sa.Column(
            "member_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "org_members.id",
                name="fk_attestor_trials_member_id_org_members",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
    )
    op.alter_column("attestor_trials", "application_id", nullable=True)

    op.add_column(
        "payout_accounts",
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_payout_accounts_org_id_organizations",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
    )
    op.alter_column("payout_accounts", "user_id", nullable=True)
    op.create_check_constraint(
        "ck_payout_accounts_owner_xor",
        "payout_accounts",
        "(user_id IS NULL) != (org_id IS NULL)",
    )
    op.create_index("idx_payout_accounts_org", "payout_accounts", ["org_id"])

    op.add_column(
        "transactions",
        sa.Column(
            "payee_org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_transactions_payee_org_id_organizations",
            ),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_transactions_single_payee",
        "transactions",
        "payee_id IS NULL OR payee_org_id IS NULL",
    )
    op.create_index("idx_transactions_payee_org", "transactions", ["payee_org_id"])


def downgrade() -> None:
    """Drop org re-point columns and restore legacy NOT NULLs."""
    op.drop_index("idx_transactions_payee_org", table_name="transactions")
    op.drop_constraint(
        "ck_transactions_single_payee", "transactions", type_="check"
    )
    op.drop_column("transactions", "payee_org_id")

    op.drop_index("idx_payout_accounts_org", table_name="payout_accounts")
    op.drop_constraint(
        "ck_payout_accounts_owner_xor", "payout_accounts", type_="check"
    )
    op.alter_column("payout_accounts", "user_id", nullable=False)
    op.drop_column("payout_accounts", "org_id")

    op.alter_column("attestor_trials", "application_id", nullable=False)
    op.drop_column("attestor_trials", "member_id")
    op.drop_column("attestor_trials", "org_id")
    op.drop_column("attestor_trials", "org_application_id")

    op.alter_column("attestation_offers", "attestor_id", nullable=False)
    op.drop_constraint(
        "uq_attestation_offers_attestation_org",
        "attestation_offers",
        type_="unique",
    )
    op.drop_column("attestation_offers", "org_id")

    op.drop_index("idx_attestations_attestor_org_status", table_name="attestations")
    op.drop_column("attestations", "reviewing_member_id")
    op.drop_column("attestations", "attestor_org_id")
