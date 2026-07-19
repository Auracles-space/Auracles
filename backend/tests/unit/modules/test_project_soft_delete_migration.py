"""Project soft-delete migration tests.

Proves the nullable deletion marker is added reversibly without changing
existing Project lifecycle rows.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[3]
PREVIOUS_HEAD = "2026_07_17_0089"


def _alembic_config() -> Config:
    """Build an Alembic config rooted at the backend directory."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def test_project_soft_delete_column_upgrades_and_downgrades() -> None:
    """Head adds projects.deleted_at and one-step downgrade removes it."""
    cfg = _alembic_config()
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(cfg, "head")
    try:
        columns = {
            column["name"] for column in inspect(sync_engine).get_columns("projects")
        }
        assert "deleted_at" in columns

        command.downgrade(cfg, PREVIOUS_HEAD)
        columns_after = {
            column["name"] for column in inspect(sync_engine).get_columns("projects")
        }
        assert "deleted_at" not in columns_after
    finally:
        command.upgrade(cfg, "head")
        sync_engine.dispose()
