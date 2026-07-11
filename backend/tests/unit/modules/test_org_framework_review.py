"""Unit tests for organization-authored Framework reviews.

Task 8 adds org-authored review identity on top of the existing individual
Operator review flow. These tests cover the service-level behavior first:
an org with an active License can author one public review under org identity
while retaining the staffing member internally.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks import service as frameworks_service
from app.modules.frameworks.models import Framework, License, Review
from app.modules.frameworks.schemas import (
    FrameworkReviewCreate,
    FrameworkReviewResponse,
)
from app.modules.organizations.models import Organization, OrgMember
from app.shared.models.audit_log import AuditLog

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org review tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def org_review_state() -> AsyncIterator[None]:
    """Reset org review rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete review-linked rows in FK-safe order."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(License))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> User:
    """Create and return one verified user for org review tests."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return user


async def _create_org(owner: User) -> tuple[Organization, OrgMember]:
    """Create one org plus its owner membership row."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"review-org-{uuid4().hex[:8]}",
                name="Reviewing Org",
                country="US",
                created_by=owner.id,
            )
            session.add(org)
            await session.flush()
            owner_member = OrgMember(org_id=org.id, user_id=owner.id, role="owner")
            session.add(owner_member)
            await session.flush()
            await session.refresh(org)
            await session.refresh(owner_member)
            return org, owner_member


async def _create_framework(
    *,
    contributor_id: UUID,
    status: str = "published",
) -> Framework:
    """Create and return one reviewable Framework row."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                contributor_org_id=None,
                title="Org Review Framework",
                description="A framework row for org review tests.",
                version="1.0.0",
                status=status,
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["org-review"],
                tags_text="org-review",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("199.00"),
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC) if status == "published" else None,
            )
            session.add(framework)
            await session.flush()
            await session.refresh(framework)
            return framework


async def _grant_org_license(framework_id: UUID, org_id: UUID) -> License:
    """Grant one active org-owned License for review eligibility."""
    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                framework_id=framework_id,
                operator_id=None,
                licensee_org_id=org_id,
                license_type="team",
                status="active",
                version_at_grant="1.0.0",
            )
            session.add(license_row)
            await session.flush()
            await session.refresh(license_row)
            return license_row


@pytest.mark.asyncio
async def test_org_review_is_written_under_org_identity(
    migrated_database: None,
    org_review_state: None,
) -> None:
    """An org-owned active License permits one review under org identity."""
    del migrated_database, org_review_state
    contributor = await _create_user("org-review-contributor")
    owner = await _create_user("org-review-owner")
    org, owner_member = await _create_org(owner)
    framework = await _create_framework(contributor_id=contributor.id)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        response = await frameworks_service.create_org_framework_review(
            session,
            org_id=org.id,
            actor=owner,
            reviewing_member_id=owner_member.id,
            framework_id=framework.id,
            payload=FrameworkReviewCreate(score=5, body="Clear and actionable."),
        )

    async with async_session_factory() as session:
        review = await session.scalar(
            select(Review).where(Review.license_id == license_row.id)
        )

    assert isinstance(response, FrameworkReviewResponse)
    assert response.operator_id is None
    assert response.reviewer_org_id == org.id
    assert "reviewing_member_id" not in response.model_dump()
    assert review is not None
    assert review.operator_id is None
    assert review.reviewer_org_id == org.id
    assert review.reviewing_member_id == owner_member.id


@pytest.mark.asyncio
async def test_org_review_requires_active_org_license(
    migrated_database: None,
    org_review_state: None,
) -> None:
    """Org review creation must reject callers without an active org License."""
    del migrated_database, org_review_state
    contributor = await _create_user("org-review-missing-license-contributor")
    owner = await _create_user("org-review-missing-license-owner")
    org, owner_member = await _create_org(owner)
    framework = await _create_framework(contributor_id=contributor.id)

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await frameworks_service.create_org_framework_review(
                session,
                org_id=org.id,
                actor=owner,
                reviewing_member_id=owner_member.id,
                framework_id=framework.id,
                payload=FrameworkReviewCreate(score=4, body="Should not persist."),
            )

    assert exc_info.value.status_code == 403
    assert (
        exc_info.value.detail
        == "An active License is required to review this Framework."
    )


@pytest.mark.asyncio
async def test_org_review_rejects_duplicate_org_review(
    migrated_database: None,
    org_review_state: None,
) -> None:
    """One organization may review one Framework only once."""
    del migrated_database, org_review_state
    contributor = await _create_user("org-review-duplicate-contributor")
    owner = await _create_user("org-review-duplicate-owner")
    org, owner_member = await _create_org(owner)
    framework = await _create_framework(contributor_id=contributor.id)
    await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        await frameworks_service.create_org_framework_review(
            session,
            org_id=org.id,
            actor=owner,
            reviewing_member_id=owner_member.id,
            framework_id=framework.id,
            payload=FrameworkReviewCreate(score=5, body="First review."),
        )

    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await frameworks_service.create_org_framework_review(
                session,
                org_id=org.id,
                actor=owner,
                reviewing_member_id=owner_member.id,
                framework_id=framework.id,
                payload=FrameworkReviewCreate(score=4, body="Duplicate review."),
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Organization has already reviewed this Framework."


@pytest.mark.asyncio
async def test_review_reviewer_xor_rejects_both_user_and_org(
    migrated_database: None,
    org_review_state: None,
) -> None:
    """The review reviewer XOR blocks rows that set both reviewer identities."""
    del migrated_database, org_review_state
    contributor = await _create_user("org-review-xor-both-contributor")
    operator = await _create_user("org-review-xor-both-operator")
    owner = await _create_user("org-review-xor-both-owner")
    org, owner_member = await _create_org(owner)
    framework = await _create_framework(contributor_id=contributor.id)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Review(
                    framework_id=framework.id,
                    operator_id=operator.id,
                    reviewer_org_id=org.id,
                    reviewing_member_id=owner_member.id,
                    license_id=license_row.id,
                    score=5,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()


@pytest.mark.asyncio
async def test_review_reviewer_xor_rejects_neither_user_nor_org(
    migrated_database: None,
    org_review_state: None,
) -> None:
    """The review reviewer XOR blocks rows that set neither reviewer identity."""
    del migrated_database, org_review_state
    contributor = await _create_user("org-review-xor-neither-contributor")
    owner = await _create_user("org-review-xor-neither-owner")
    org, _owner_member = await _create_org(owner)
    framework = await _create_framework(contributor_id=contributor.id)
    license_row = await _grant_org_license(framework.id, org.id)

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Review(
                    framework_id=framework.id,
                    operator_id=None,
                    reviewer_org_id=None,
                    reviewing_member_id=None,
                    license_id=license_row.id,
                    score=4,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()


def test_review_response_schema_hides_reviewing_member_id() -> None:
    """The public review response schema must never expose reviewing member ids."""
    assert "reviewing_member_id" not in FrameworkReviewResponse.model_fields


@pytest.mark.asyncio
async def test_individual_review_path_still_uses_operator_identity(
    migrated_database: None,
    org_review_state: None,
) -> None:
    """The existing individual Operator review path remains unchanged."""
    del migrated_database, org_review_state
    contributor = await _create_user("org-review-regression-contributor")
    operator = await _create_user("org-review-regression-operator")
    framework = await _create_framework(contributor_id=contributor.id)

    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                framework_id=framework.id,
                operator_id=operator.id,
                licensee_org_id=None,
                license_type="single_user",
                status="active",
                version_at_grant="1.0.0",
            )
            session.add(license_row)
            await session.flush()

    async with async_session_factory() as session:
        response = await frameworks_service.create_framework_review(
            session,
            operator=operator,
            framework_id=framework.id,
            payload=FrameworkReviewCreate(score=5, body="Still individual."),
        )

    async with async_session_factory() as session:
        review = await session.scalar(
            select(Review).where(Review.framework_id == framework.id)
        )

    assert response.operator_id == operator.id
    assert response.reviewer_org_id is None
    assert review is not None
    assert review.operator_id == operator.id
    assert review.reviewer_org_id is None
