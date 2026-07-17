"""Add org_team_capabilities and backfill an All members team per org.

Team-scoped capability rights move marketplace access from org-wide grants to
team-scoped grants. This creates the team-to-capability link table and
backfills existing orgs so nobody loses access at cutover: each org with an
active capability gets an "All members" team containing all current members
with those active capabilities enabled.

Revision ID: 2026_07_17_0089
Revises: 2026_07_17_0088
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_07_17_0089"
down_revision: str | Sequence[str] | None = "2026_07_17_0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the team-capability link table and backfill All members teams."""
    op.create_table(
        "org_team_capabilities",
        sa.Column(
            "team_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_teams.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "capability",
            sa.dialects.postgresql.ENUM(
                "attestor",
                "contributor",
                "operator",
                name="org_capability_enum",
                create_type=False,
            ),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    conn = op.get_bind()
    org_ids = conn.execute(
        sa.text(
            "SELECT DISTINCT org_id FROM org_capabilities WHERE status = 'active'"
        )
    ).scalars().all()

    for org_id in org_ids:
        team_id = conn.execute(
            sa.text(
                "SELECT id FROM org_teams "
                "WHERE org_id = :o AND name = 'All members'"
            ),
            {"o": org_id},
        ).scalar()
        if team_id is None:
            team_id = conn.execute(
                sa.text(
                    "INSERT INTO org_teams (org_id, name) "
                    "VALUES (:o, 'All members') RETURNING id"
                ),
                {"o": org_id},
            ).scalar()

        conn.execute(
            sa.text(
                "INSERT INTO org_team_members (team_id, member_id) "
                "SELECT :t, id FROM org_members WHERE org_id = :o "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": team_id, "o": org_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO org_team_capabilities (team_id, capability) "
                "SELECT :t, capability FROM org_capabilities "
                "WHERE org_id = :o AND status = 'active' "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": team_id, "o": org_id},
        )


def downgrade() -> None:
    """Drop the team-capability link table. Backfilled teams remain."""
    op.drop_table("org_team_capabilities")
