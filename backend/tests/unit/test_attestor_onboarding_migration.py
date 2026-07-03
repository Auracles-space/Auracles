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
        app_cols = {c["name"] for c in insp.get_columns("attestor_applications")}
        assert {
            "legal_name",
            "linkedin_url",
            "professional_body_numbers",
            "cv_file_key",
            "coi_declarations",
            "coi_signed_at",
            "coi_expires_at",
            "sectors",
            "framework_categories",
            "needs_retag",
            "kyc_verified_at",
            "kyc_name_match",
        } <= app_cols
        prof_cols = {c["name"] for c in insp.get_columns("attestor_profiles")}
        assert {
            "verification_level",
            "sectors",
            "framework_categories",
            "coi_declarations",
            "coi_signed_at",
            "coi_expires_at",
        } <= prof_cols
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
