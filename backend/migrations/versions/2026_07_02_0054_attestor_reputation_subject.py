"""Add attestor as a reputation subject.

Module 6b makes the Attestor a first-class reputation subject. This widens the
``reputation_scores`` subject-type CHECK to admit ``attestor`` and adds the
sticky merit flag ``attestor_profiles.certified_attestor_at`` without touching
onboarding ``verification_level``.

Maps to: Module 6b design spec sections 4.1 and 7.

Revision ID: 2026_07_02_0054
Revises: 2026_07_01_0053
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_02_0054"
down_revision: str | Sequence[str] | None = "2026_07_01_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CHECK = "subject_type IN ('framework','contributor','operator')"
_NEW_CHECK = "subject_type IN ('framework','contributor','operator','attestor')"


def upgrade() -> None:
    """Widen the subject-type CHECK and add certified_attestor_at."""
    op.drop_constraint(
        "ck_reputation_subject_type",
        "reputation_scores",
        type_="check",
    )
    op.create_check_constraint(
        "ck_reputation_subject_type",
        "reputation_scores",
        _NEW_CHECK,
    )
    op.add_column(
        "attestor_profiles",
        sa.Column("certified_attestor_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Restore the original CHECK and remove certified_attestor_at.

    Any ``attestor`` reputation rows are removed first so the narrowed
    constraint can be recreated safely.
    """
    op.drop_column("attestor_profiles", "certified_attestor_at")
    op.execute("DELETE FROM reputation_scores WHERE subject_type = 'attestor'")
    op.drop_constraint(
        "ck_reputation_subject_type",
        "reputation_scores",
        type_="check",
    )
    op.create_check_constraint(
        "ck_reputation_subject_type",
        "reputation_scores",
        _OLD_CHECK,
    )
