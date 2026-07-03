"""Add org teams with membership and org-removal cascade.

Revision ID: 2026_07_03_0061
Revises: 2026_07_03_0060
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_07_03_0061"
down_revision: str | None = "2026_07_03_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create org_teams and org_team_members tables."""
    op.create_table(
        "org_teams",
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
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("org_id", "name", name="uq_org_teams_org_name"),
    )

    op.create_table(
        "org_team_members",
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_teams.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "member_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_members.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_org_team_members_member", "org_team_members", ["member_id"]
    )


def downgrade() -> None:
    """Drop org_team_members and org_teams."""
    op.drop_index("idx_org_team_members_member", table_name="org_team_members")
    op.drop_table("org_team_members")
    op.drop_table("org_teams")
