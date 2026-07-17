"""Migration test: org_team_capabilities table + backfill.

Backfilling an "All members" team for every org with an active capability must
preserve access by keeping those members on a team with the capability enabled
after the team-scoped rights cutover.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]

DOWN = "2026_07_17_0088"
UP = "2026_07_17_0089"


@pytest.fixture
def alembic_config() -> Config:
    """Build an Alembic config rooted at the backend directory."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_backfill_creates_all_members_team_and_enables_caps(
    alembic_config: Config,
) -> None:
    """Upgrading creates an All members team with active capabilities enabled."""
    command.downgrade(alembic_config, DOWN)
    sync_engine = create_engine(
        __import__("app.main", fromlist=["app"]).app.state.settings.sync_database_url
    )
    org_id = "11111111-1111-1111-1111-111111111111"
    user_id = "22222222-2222-2222-2222-222222222222"
    try:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, email, display_name, email_verified) "
                    "VALUES (:u, 'mig-team@auracles.space', 'Mig Team', true) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"u": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO organizations (id, name, slug, country, created_by) "
                    "VALUES (:o, 'Mig Org', 'mig-team-org', 'US', :u)"
                ),
                {"o": org_id, "u": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO org_members (org_id, user_id, role) "
                    "VALUES (:o, :u, 'member')"
                ),
                {"o": org_id, "u": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO org_capabilities (org_id, capability, status) "
                    "VALUES (:o, 'operator', 'active')"
                ),
                {"o": org_id},
            )

        command.upgrade(alembic_config, UP)

        with sync_engine.connect() as conn:
            team = conn.execute(
                sa.text(
                    "SELECT id FROM org_teams "
                    "WHERE org_id=:o AND name='All members'"
                ),
                {"o": org_id},
            ).fetchone()
            assert team is not None
            team_id = team[0]
            member_count = conn.execute(
                sa.text("SELECT count(*) FROM org_team_members WHERE team_id=:t"),
                {"t": team_id},
            ).scalar()
            assert member_count == 1
            caps = conn.execute(
                sa.text(
                    "SELECT capability FROM org_team_capabilities WHERE team_id=:t"
                ),
                {"t": team_id},
            ).scalars().all()
            assert caps == ["operator"]
    finally:
        with sync_engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM org_members WHERE org_id=:o"),
                {"o": org_id},
            )
            conn.execute(
                sa.text("DELETE FROM organizations WHERE id=:o"),
                {"o": org_id},
            )
            conn.execute(sa.text("DELETE FROM users WHERE id=:u"), {"u": user_id})
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()
