"""Org attestor reputation subject and org-repointed warnings.

Task 10 of the Organizations-as-Attestors sub-project
(docs/superpowers/plans/2026-07-04-org-attestor.md). Two additive changes:

* ``attestor_warnings`` gains ``attestor_org_id`` and relaxes ``attestor_id``
  to nullable under an XOR CHECK, so an upheld dispute records the warning
  against the reviewing organization instead of a member. Legacy individual
  warnings keep ``attestor_id``; the column is dropped in the final reviewed
  retirement migration.
* ``reputation_scores`` widens its subject-type CHECK to admit
  ``attestor_org`` — org attestor reputation is scored as its own subject
  (org completed attestations, org ratings, org warnings), parallel to the
  individual ``attestor`` subject retained during coexistence.

Downgrade removes ``attestor_org`` reputation rows first so the narrowed
CHECK re-applies cleanly, then restores NOT NULL on ``attestor_id``
(acceptable on the dev database: no org warning rows, which hold a NULL
``attestor_id``, exist before this wave ships).

Revision ID: 2026_07_05_0067
Revises: 2026_07_05_0066
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_05_0067"
down_revision: str | Sequence[str] | None = "2026_07_05_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_REPUTATION_CHECK = (
    "subject_type IN ('framework','contributor','operator','attestor')"
)
_NEW_REPUTATION_CHECK = (
    "subject_type IN "
    "('framework','contributor','operator','attestor','attestor_org')"
)


def upgrade() -> None:
    """Re-point warnings to orgs and widen the reputation subject CHECK."""
    op.add_column(
        "attestor_warnings",
        sa.Column(
            "attestor_org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_attestor_warnings_attestor_org_id_organizations",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
    )
    op.alter_column("attestor_warnings", "attestor_id", nullable=True)
    op.create_check_constraint(
        "ck_attestor_warnings_attestor_xor",
        "attestor_warnings",
        "(attestor_id IS NULL) != (attestor_org_id IS NULL)",
    )
    op.create_index(
        "idx_attestor_warnings_org_created",
        "attestor_warnings",
        ["attestor_org_id", "created_at"],
    )

    op.drop_constraint(
        "ck_reputation_subject_type", "reputation_scores", type_="check"
    )
    op.create_check_constraint(
        "ck_reputation_subject_type",
        "reputation_scores",
        _NEW_REPUTATION_CHECK,
    )


def downgrade() -> None:
    """Narrow the reputation CHECK and drop org warning columns."""
    op.execute(
        "DELETE FROM reputation_scores WHERE subject_type = 'attestor_org'"
    )
    op.drop_constraint(
        "ck_reputation_subject_type", "reputation_scores", type_="check"
    )
    op.create_check_constraint(
        "ck_reputation_subject_type",
        "reputation_scores",
        _OLD_REPUTATION_CHECK,
    )

    op.drop_index(
        "idx_attestor_warnings_org_created", table_name="attestor_warnings"
    )
    op.drop_constraint(
        "ck_attestor_warnings_attestor_xor", "attestor_warnings", type_="check"
    )
    op.alter_column("attestor_warnings", "attestor_id", nullable=False)
    op.drop_column("attestor_warnings", "attestor_org_id")
