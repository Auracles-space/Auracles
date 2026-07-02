"""Add attestation badge & provenance schema.

Module 6c records an immutable badge snapshot for each closed+eligible
framework attestation and captures the attested framework version on the
attestation. The badge table is insert-only provenance; the capture FK
version-locks the badge.

Maps to: Module 6c design spec section 5.

Revision ID: 2026_07_02_0055
Revises: 2026_07_02_0054
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_02_0055"
down_revision: str | Sequence[str] | None = "2026_07_02_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVIEW_TYPE_ENUM = postgresql.ENUM(
    "quality",
    "compliance",
    "expert",
    "provenance",
    name="attestation_review_type_enum",
    create_type=False,
)
_OUTCOME_ENUM = postgresql.ENUM(
    "approved",
    "conditional",
    "rejected",
    name="attestation_outcome_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create attestation_badges and add attestations.framework_version_id."""
    op.add_column(
        "attestations",
        sa.Column(
            "framework_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("framework_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_table(
        "attestation_badges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "attestation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attestations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "framework_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("frameworks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("review_type", _REVIEW_TYPE_ENUM, nullable=False),
        sa.Column("outcome", _OUTCOME_ENUM, nullable=False),
        sa.Column(
            "attestor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("attestor_display_name", sa.Text(), nullable=False),
        sa.Column(
            "credentials_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("framework_version", sa.String(length=20), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "attestation_id",
            name="uq_attestation_badges_attestation",
        ),
    )
    op.create_index(
        "idx_attestation_badges_framework",
        "attestation_badges",
        ["framework_id"],
    )
    op.create_index(
        "idx_attestation_badges_attestor",
        "attestation_badges",
        ["attestor_id"],
    )


def downgrade() -> None:
    """Drop attestation_badges and the capture FK."""
    op.drop_index("idx_attestation_badges_attestor", table_name="attestation_badges")
    op.drop_index("idx_attestation_badges_framework", table_name="attestation_badges")
    op.drop_table("attestation_badges")
    op.drop_column("attestations", "framework_version_id")
