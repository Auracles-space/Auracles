"""Add organization invitations table.

Stores hashed invitation tokens, invite lifecycle state, and the per-org
pending-email uniqueness guard required by the Organizations Core invite flow.

Revision ID: 2026_07_03_0059
Revises: 2026_07_03_0058
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_03_0059"
down_revision: str | Sequence[str] | None = "2026_07_03_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG_INVITATION_STATUS = postgresql.ENUM(
    "pending",
    "accepted",
    "declined",
    "revoked",
    "expired",
    name="org_invitation_status_enum",
    create_type=False,
)
ORG_MEMBER_ROLE = postgresql.ENUM(
    "owner",
    "admin",
    "member",
    name="org_member_role_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create the organization invitations table and indexes."""
    bind = op.get_bind()
    ORG_INVITATION_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "org_invitations",
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
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", ORG_MEMBER_ROLE, nullable=False),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("status", ORG_INVITATION_STATUS, nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_org_invitations_pending",
        "org_invitations",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("idx_org_invitations_email", "org_invitations", ["email"])


def downgrade() -> None:
    """Drop the organization invitations table and status enum."""
    bind = op.get_bind()

    op.drop_index("idx_org_invitations_email", table_name="org_invitations")
    op.drop_index("uq_org_invitations_pending", table_name="org_invitations")
    op.drop_table("org_invitations")

    ORG_INVITATION_STATUS.drop(bind, checkfirst=True)
