"""Migration coverage for Phase 4a Slice 1 project schema foundation.

Slice 1 is intentionally schema-first: later project, workspace, realtime, and
notification slices depend on this durable database contract before any
business endpoints are implemented.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import configure_mappers

from app.core.config import get_settings
from app.modules.notifications.models import Notification
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
    ProposalAmendment,
)
from app.modules.workspace.models import WorkspaceMessage, WorkspaceUploadSession

PHASE_THREE_HEAD = "2026_06_09_0010"

PROJECT_TABLES = {
    "projects",
    "proposals",
    "proposal_amendments",
    "milestones",
    "deliverables",
    "workspace_messages",
    "workspace_upload_sessions",
    "disputes",
    "notifications",
}
PROJECT_ENUMS = {
    "project_status_enum",
    "milestone_plan_status_enum",
    "proposal_status_enum",
    "amendment_change_enum",
    "amendment_status_enum",
    "milestone_status_enum",
    "deliverable_status_enum",
    "workspace_scan_status_enum",
    "workspace_system_event_enum",
    "dispute_status_enum",
    "dispute_resolution_enum",
    "notification_type_enum",
}


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Run Phase 4a schema migrations and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, PHASE_THREE_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PHASE_THREE_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_projects_migration_creates_tables_enums_and_indexes(
    migrated_engine: Engine,
) -> None:
    """Alembic creates the Phase 4a project/workspace/notification schema."""
    inspector = inspect(migrated_engine)

    with migrated_engine.connect() as connection:
        enum_names = {
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
            )
        }

    project_indexes = {index["name"] for index in inspector.get_indexes("projects")}
    message_indexes = {
        index["name"] for index in inspector.get_indexes("workspace_messages")
    }
    upload_indexes = {
        index["name"] for index in inspector.get_indexes("workspace_upload_sessions")
    }
    notification_indexes = {
        index["name"] for index in inspector.get_indexes("notifications")
    }

    assert PROJECT_TABLES.issubset(set(inspector.get_table_names()))
    assert PROJECT_ENUMS.issubset(enum_names)
    assert {"idx_projects_operator_status", "idx_projects_status_expires_at"}.issubset(
        project_indexes
    )
    assert {
        "idx_workspace_messages_project_created_at",
        "idx_workspace_messages_pending_scan",
    }.issubset(message_indexes)
    assert {
        "idx_workspace_upload_sessions_project_user_consumed",
        "idx_workspace_upload_sessions_expires_at",
    }.issubset(upload_indexes)
    assert {
        "idx_notifications_user_read_created",
        "uq_notifications_user_dedupe_key",
    }.issubset(notification_indexes)


def test_projects_migration_preserves_key_constraints(
    migrated_engine: Engine,
) -> None:
    """The project schema exposes the invariants later services rely on."""
    inspector = inspect(migrated_engine)

    project_checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("projects")
    }
    milestone_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("milestones")
    }
    upload_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("workspace_upload_sessions")
    }
    proposal_foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("proposals")
    }

    assert {
        "ck_projects_budget_range",
        # Renamed by 2026_08_11_0094: the USD-only check became an allowlist of
        # the currencies the payment adapters can settle.
        "ck_projects_currency_settleable",
    }.issubset(project_checks)
    assert "uq_milestones_project_sequence" in milestone_uniques
    assert "uq_workspace_upload_sessions_s3_key" in upload_uniques
    project_fk = proposal_foreign_keys["fk_proposals_project_id_projects"]
    assert project_fk["referred_table"] == "projects"


def test_projects_migration_downgrade_removes_slice_one_schema() -> None:
    """Downgrade removes Phase 4a Slice 1 tables and enum types cleanly."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, PHASE_THREE_HEAD)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        with engine.connect() as connection:
            enum_names = {
                row[0]
                for row in connection.execute(
                    text("SELECT typname FROM pg_type WHERE typname LIKE '%_enum'")
                )
            }

        assert PROJECT_TABLES.isdisjoint(table_names)
        assert PROJECT_ENUMS.isdisjoint(enum_names)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_project_orm_models_bind_to_slice_one_tables() -> None:
    """ORM models expose stable metadata for later service slices."""
    configure_mappers()

    assert Project.__tablename__ == "projects"
    assert {"required_deliverables", "milestone_plan_status"}.issubset(
        Project.__table__.columns.keys()
    )
    assert Proposal.__tablename__ == "proposals"
    assert ProposalAmendment.__tablename__ == "proposal_amendments"
    assert Milestone.__tablename__ == "milestones"
    assert "escrow_id" in Milestone.__table__.columns.keys()
    assert Deliverable.__tablename__ == "deliverables"
    assert Dispute.__tablename__ == "disputes"
    assert WorkspaceMessage.__tablename__ == "workspace_messages"
    assert WorkspaceUploadSession.__tablename__ == "workspace_upload_sessions"
    assert Notification.__tablename__ == "notifications"
