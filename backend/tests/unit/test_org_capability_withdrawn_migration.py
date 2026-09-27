"""Migration coverage for the owner-initiated capability wind-down state.

An org owner could not close their own organization: the close refuses while
any capability is `active`, and every status change was admin-only. Account
deletion then refuses while you are sole owner of an org with an active
capability, so the owner was sealed in. `withdrawn` is the state an owner puts
a capability into themselves.

It is a distinct value rather than a reuse of `revoked` because `revoked`
means an admin took the capability away: it bars re-application, and the
owner-facing copy tells them to appeal to support.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings

PRIOR_HEAD = "2026_09_19_0120"


def _capability_labels(engine: Engine) -> set[str]:
    """Return every label the org capability status enum accepts."""
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT enumlabel FROM pg_enum "
                    "JOIN pg_type ON pg_type.oid = pg_enum.enumtypid "
                    "WHERE typname = 'org_capability_status_enum'"
                )
            )
        }


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """Upgrade to head and restore the local DB afterwards."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.downgrade(alembic_config, PRIOR_HEAD)
    command.upgrade(alembic_config, "head")
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, PRIOR_HEAD)
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_upgrade_adds_withdrawn_without_disturbing_the_others(
    migrated_engine: Engine,
) -> None:
    """`withdrawn` joins the enum and every existing label survives.

    Each gate in the codebase tests `status == "active"`, so a new non-active
    label blocks everywhere by construction — but only if the labels it sits
    beside are untouched.
    """
    labels = _capability_labels(migrated_engine)

    assert "withdrawn" in labels
    assert {"pending", "active", "suspended", "revoked"}.issubset(labels)


def test_downgrade_reconciles_withdrawn_rows(migrated_engine: Engine) -> None:
    """Downgrading turns withdrawn capabilities into revoked ones.

    Postgres cannot drop an enum label, so the downgrade's job is to leave no
    row reading a value the older code does not know. `revoked` is the closest
    non-active state, so the capability stays blocked either way — the
    difference is only whether it reads as the owner's choice.
    """
    alembic_config = Config("alembic.ini")
    with migrated_engine.begin() as connection:
        # Self-contained: the local database this runs against may hold no
        # users, and a fixture that depends on ambient rows fails for reasons
        # that have nothing to do with the migration.
        owner_id = connection.execute(
            text(
                "INSERT INTO users (email, display_name) "
                "VALUES ('withdrawn-mig@auracles.space', 'Withdrawn Owner') "
                "RETURNING id"
            )
        ).scalar_one()
        org_id = connection.execute(
            text(
                "INSERT INTO organizations (id, slug, name, country, created_by) "
                "VALUES (gen_random_uuid(), 'withdrawn-mig-test', 'Withdrawn Co', "
                "'NG', :owner_id) RETURNING id"
            ).bindparams(owner_id=owner_id)
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO org_capabilities (id, org_id, capability, status) "
                "VALUES (gen_random_uuid(), :org_id, 'contributor', 'withdrawn')"
            ).bindparams(org_id=org_id)
        )

    command.downgrade(alembic_config, PRIOR_HEAD)

    with migrated_engine.connect() as connection:
        status = connection.execute(
            text(
                "SELECT status::text FROM org_capabilities WHERE org_id = :org_id"
            ).bindparams(org_id=org_id)
        ).scalar_one()
        assert status == "revoked"

    command.upgrade(alembic_config, "head")
    with migrated_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM org_capabilities WHERE org_id = :org_id").bindparams(
                org_id=org_id
            )
        )
        connection.execute(
            text("DELETE FROM organizations WHERE id = :org_id").bindparams(
                org_id=org_id
            )
        )
        connection.execute(
            text("DELETE FROM users WHERE id = :owner_id").bindparams(owner_id=owner_id)
        )
