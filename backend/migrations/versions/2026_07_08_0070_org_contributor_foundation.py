"""Add org contributor foundation tables and dual-source user roles.

Supports Task 1 in docs/superpowers/plans/2026-07-08-org-contributor.md and
the approved Organizations as Contributors design by introducing org-level
Contributor and legal-profile tables plus the ``user_roles.source`` marker that
lets self-selected and org-derived Contributor roles coexist safely.

Revision ID: 2026_07_08_0070
Revises: 2026_07_08_0069
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_08_0070"
down_revision: str | Sequence[str] | None = "2026_07_08_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add org contributor foundation tables and dual-source role support."""
    op.add_column(
        "user_roles",
        sa.Column("source", sa.String(length=20), nullable=True),
    )
    op.execute("UPDATE user_roles SET source = 'derived' WHERE role = 'attestor'")
    op.execute("UPDATE user_roles SET source = 'self' WHERE source IS NULL")
    op.alter_column("user_roles", "source", nullable=False)
    op.drop_constraint("uq_user_roles_user_role", "user_roles", type_="unique")
    op.create_unique_constraint(
        "uq_user_roles_user_role_source",
        "user_roles",
        ["user_id", "role", "source"],
    )

    op.create_table(
        "org_contributor_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "verification_level",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reputation_score", sa.Numeric(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("org_id", name="uq_org_contributor_profiles_org"),
    )
    op.create_table(
        "org_legal_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("registration_number", sa.Text(), nullable=True),
        sa.Column("address", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "tax_document_type",
            postgresql.ENUM(
                "w9",
                "w8ben",
                "other",
                name="tax_document_type_enum",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("tax_document_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("org_id", name="uq_org_legal_profiles_org"),
    )


def downgrade() -> None:
    """Remove org contributor foundation tables and collapse role duplicates.

    Downgrade preserves the ``source='self'`` row when both self and derived
    Contributor rows exist because the prior single-row unique constraint cannot
    represent both origins simultaneously.
    """
    op.drop_table("org_legal_profiles")
    op.drop_table("org_contributor_profiles")

    op.drop_constraint(
        "uq_user_roles_user_role_source",
        "user_roles",
        type_="unique",
    )
    op.execute(
        """
        DELETE FROM user_roles AS derived
        USING user_roles AS self_row
        WHERE derived.user_id = self_row.user_id
          AND derived.role = self_row.role
          AND derived.source = 'derived'
          AND self_row.source = 'self'
        """
    )
    op.create_unique_constraint(
        "uq_user_roles_user_role",
        "user_roles",
        ["user_id", "role"],
    )
    op.drop_column("user_roles", "source")
