"""Org identity snapshot on attestation badges.

Organizations-as-Attestors (sub-project 2, Task 9) presents org identity on the
public trust badge and provenance surfaces. The immutable ``attestation_badges``
snapshot was user-keyed (``attestor_id`` NOT NULL plus ``attestor_display_name``).
This wave lets a badge snapshot an organization instead: ``attestor_id`` is
relaxed to nullable, and org identity columns are added — ``attestor_org_id``
(FK, SET NULL on org delete so the historical snapshot survives),
``attestor_org_slug``, and the snapshotted ``verification_level``. A
single-attestor XOR CHECK guarantees a badge belongs to exactly one of a legacy
individual attestor or an organization. ``attestor_display_name`` continues to
carry the public display name (org name for org badges, user name for legacy).

Downgrade restores NOT NULL on ``attestor_id`` directly; acceptable on the dev
database because no org badges (which would hold NULL there) exist before this
wave ships.

Revision ID: 2026_07_05_0066
Revises: 2026_07_05_0065
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_05_0066"
down_revision: str | Sequence[str] | None = "2026_07_05_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add org identity snapshot columns, XOR CHECK, and index on badges."""
    op.add_column(
        "attestation_badges",
        sa.Column(
            "attestor_org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_attestation_badges_attestor_org_id_organizations",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "attestation_badges",
        sa.Column("attestor_org_slug", sa.Text(), nullable=True),
    )
    op.add_column(
        "attestation_badges",
        sa.Column("verification_level", sa.Integer(), nullable=True),
    )
    op.alter_column("attestation_badges", "attestor_id", nullable=True)
    op.create_check_constraint(
        "ck_attestation_badges_attestor_xor",
        "attestation_badges",
        "(attestor_id IS NULL) != (attestor_org_id IS NULL)",
    )
    op.create_index(
        "idx_attestation_badges_attestor_org",
        "attestation_badges",
        ["attestor_org_id"],
    )


def downgrade() -> None:
    """Drop org identity snapshot columns and restore the attestor NOT NULL."""
    op.drop_index(
        "idx_attestation_badges_attestor_org",
        table_name="attestation_badges",
    )
    op.drop_constraint(
        "ck_attestation_badges_attestor_xor",
        "attestation_badges",
        type_="check",
    )
    op.alter_column("attestation_badges", "attestor_id", nullable=False)
    op.drop_column("attestation_badges", "verification_level")
    op.drop_column("attestation_badges", "attestor_org_slug")
    op.drop_column("attestation_badges", "attestor_org_id")
