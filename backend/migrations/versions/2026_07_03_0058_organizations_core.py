"""Organizations Core: org entity, membership, capability skeleton.

Foundation for the org-based attestation redefine
(docs/superpowers/specs/2026-07-03-organizations-core-design.md):
organizations table, org_members with single-owner partial unique index,
and the org_capabilities status table (no activation path in Org Core).

Revision ID: 2026_07_03_0058
Revises: 2026_07_02_0057
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_03_0058"
down_revision: str | Sequence[str] | None = "2026_07_02_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG_MEMBER_ROLE = postgresql.ENUM(
    "owner",
    "admin",
    "member",
    name="org_member_role_enum",
    create_type=False,
)
ORG_CAPABILITY = postgresql.ENUM(
    "attestor",
    "contributor",
    "operator",
    name="org_capability_enum",
    create_type=False,
)
ORG_CAPABILITY_STATUS = postgresql.ENUM(
    "pending",
    "active",
    "suspended",
    "revoked",
    name="org_capability_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create organizations, org_members, and org_capabilities."""
    bind = op.get_bind()
    ORG_MEMBER_ROLE.create(bind, checkfirst=True)
    ORG_CAPABILITY.create(bind, checkfirst=True)
    ORG_CAPABILITY_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(length=80), nullable=False, unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("logo_key", sa.String(length=512), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
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
    )

    op.create_table(
        "org_members",
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
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("role", ORG_MEMBER_ROLE, nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),
    )
    op.create_index(
        "uq_org_members_single_owner",
        "org_members",
        ["org_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_index("idx_org_members_user", "org_members", ["user_id"])

    op.create_table(
        "org_capabilities",
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
        sa.Column("capability", ORG_CAPABILITY, nullable=False),
        sa.Column("status", ORG_CAPABILITY_STATUS, nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("org_id", "capability", name="uq_org_capabilities_org_cap"),
    )


def downgrade() -> None:
    """Drop organizations core tables and enums."""
    bind = op.get_bind()

    op.drop_table("org_capabilities")
    op.drop_index("idx_org_members_user", table_name="org_members")
    op.drop_index("uq_org_members_single_owner", table_name="org_members")
    op.drop_table("org_members")
    op.drop_table("organizations")

    ORG_CAPABILITY_STATUS.drop(bind, checkfirst=True)
    ORG_CAPABILITY.drop(bind, checkfirst=True)
    ORG_MEMBER_ROLE.drop(bind, checkfirst=True)
