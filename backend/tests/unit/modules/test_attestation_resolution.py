"""Unit tests for attestation resolution restructure (Module 5 Slice 4).

Verifies the model-level schema changes introduced by Task 9:
outcome enum on disputes, revision_requested status on attestations,
revision_count and report_published_eligible columns, and the deliberate
removal of the split resolution type and its associated columns.

[HUMAN REVIEW REQUIRED]: Task 9 drops shipped columns (resolution_type,
release_amount, refund_amount) from attestation_disputes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is upgraded to the latest alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def db_session(migrated_database) -> AsyncIterator[AsyncSession]:
    """Provide an async session with a migrated database."""
    del migrated_database
    await engine.dispose()
    async with async_session_factory() as session:
        yield session
    await engine.dispose()


# ── Model attribute tests (no DB needed) ──────────────────────────────────


def test_dispute_has_outcome_attribute() -> None:
    """AttestationDispute exposes an 'outcome' mapped attribute."""
    assert hasattr(AttestationDispute, "outcome"), (
        "AttestationDispute must have an 'outcome' column (Task 9)."
    )


def test_dispute_has_is_complex_attribute() -> None:
    """AttestationDispute has an is_complex boolean."""
    assert hasattr(AttestationDispute, "is_complex"), (
        "AttestationDispute must have an 'is_complex' column (Task 9)."
    )


def test_dispute_has_resolution_due_at_attribute() -> None:
    """AttestationDispute has a resolution_due_at timestamp."""
    assert hasattr(AttestationDispute, "resolution_due_at"), (
        "AttestationDispute must have a 'resolution_due_at' column (Task 9)."
    )


def test_dispute_has_resolution_overdue_at_attribute() -> None:
    """AttestationDispute has a resolution_overdue_at timestamp."""
    assert hasattr(AttestationDispute, "resolution_overdue_at"), (
        "AttestationDispute must have a 'resolution_overdue_at' column (Task 9)."
    )


def test_dispute_resolution_type_removed() -> None:
    """The old resolution_type / release_amount / refund_amount columns are gone."""
    assert not hasattr(AttestationDispute, "resolution_type"), (
        "resolution_type must be removed from AttestationDispute (Task 9)."
    )
    assert not hasattr(AttestationDispute, "release_amount"), (
        "release_amount must be removed from AttestationDispute (Task 9)."
    )
    assert not hasattr(AttestationDispute, "refund_amount"), (
        "refund_amount must be removed from AttestationDispute (Task 9)."
    )


def test_attestation_has_revision_count_attribute() -> None:
    """Attestation has a revision_count integer."""
    assert hasattr(Attestation, "revision_count"), (
        "Attestation must have a 'revision_count' column (Task 9)."
    )


def test_attestation_has_report_published_eligible_attribute() -> None:
    """Attestation has a report_published_eligible boolean."""
    assert hasattr(Attestation, "report_published_eligible"), (
        "Attestation must have a 'report_published_eligible' column (Task 9)."
    )


# ── DB-level enum/schema tests (need migrated DB) ────────────────────────


async def test_dispute_outcome_enum_values(db_session: AsyncSession) -> None:
    """The outcome enum allows exactly rejected, upheld_refund, upheld_revise."""
    result = await db_session.execute(
        text(
            "SELECT unnest(enum_range(NULL::attestation_dispute_outcome_enum))::text"
        )
    )
    values = {row[0] for row in result.fetchall()}
    assert values == {"rejected", "upheld_refund", "upheld_revise"}


async def test_revision_requested_is_valid_status(db_session: AsyncSession) -> None:
    """The attestation_status_enum accepts 'revision_requested'."""
    result = await db_session.execute(
        text("SELECT 'revision_requested'::attestation_status_enum::text")
    )
    assert result.scalar() == "revision_requested"


async def test_split_resolution_enum_type_dropped(db_session: AsyncSession) -> None:
    """The old attestation_dispute_resolution_enum type no longer exists in the DB."""
    result = await db_session.execute(
        text(
            "SELECT 1 FROM pg_type "
            "WHERE typname = 'attestation_dispute_resolution_enum'"
        )
    )
    assert result.scalar() is None, (
        "attestation_dispute_resolution_enum must be dropped (Task 9)."
    )
