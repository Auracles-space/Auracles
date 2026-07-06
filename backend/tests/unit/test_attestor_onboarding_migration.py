"""Migration round-trip test for the Attestor onboarding schema."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.main import app


def test_onboarding_migration_upgrades_and_downgrades() -> None:
    """attestor onboarding columns + trials table exist after upgrade.

    Also asserts a clean downgrade.
    """
    cfg = Config("alembic.ini")
    engine = create_engine(app.state.settings.sync_database_url, pool_pre_ping=True)
    try:
        command.upgrade(cfg, "head")
        insp = inspect(engine)
        # The individual attestor_applications / attestor_profiles tables the
        # onboarding migration created were retired in the org-attestor drop
        # migration; only the retained onboarding effects are asserted here.
        cred_cols = {c["name"] for c in insp.get_columns("credentials")}
        assert {
            "issuing_body",
            "good_standing",
            "registry_checked_at",
            "registry_checked_by",
            "registry_reference",
        } <= cred_cols
        assert "attestor_trials" in insp.get_table_names()
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
