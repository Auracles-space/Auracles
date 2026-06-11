"""Integration tests for licensed Operator Framework reviews.

These tests cover the post-Phase-4 marketplace polish backlog Slice 1:
licensed Operators can review purchased Frameworks, update their own review
inside the edit window, and Explore reads real review aggregates.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select, update

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework, License, Review
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure review tables exist before the endpoint tests run."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def review_test_context() -> AsyncIterator[None]:
    """Reset review-related marketplace rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in dependency order so tests stay isolated."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(Review))
            await session.execute(delete(License))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def create_user(
    email: str,
    roles: list[str],
    *,
    display_name: str | None = None,
) -> UUID:
    """Create an email-verified test user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=display_name or email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def create_framework(
    contributor_id: UUID,
    *,
    title: str = "Licensed Risk Framework",
    status: str = "published",
    price: Decimal = Decimal("499.00"),
) -> UUID:
    """Create a Framework row that can be licensed and reviewed."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                id=uuid4(),
                contributor_id=contributor_id,
                title=title,
                description=f"{title} implementation method.",
                version="1.0.0",
                status=status,
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk", "governance"],
                tags_text="risk governance",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=price,
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC) if status == "published" else None,
            )
            session.add(framework)
        return framework.id


async def grant_license(
    framework_id: UUID,
    operator_id: UUID,
    *,
    status: str = "active",
    expires_at: datetime | None = None,
) -> UUID:
    """Grant an Operator license directly as review API prerequisite."""
    async with async_session_factory() as session:
        async with session.begin():
            license_row = License(
                id=uuid4(),
                framework_id=framework_id,
                operator_id=operator_id,
                license_type="single_user",
                status=status,
                version_at_grant="1.0.0",
                expires_at=expires_at,
            )
            session.add(license_row)
        return license_row.id


async def create_review_row(
    framework_id: UUID,
    operator_id: UUID,
    license_id: UUID,
    *,
    score: int,
    body: str | None = None,
) -> UUID:
    """Create a persisted Review row for aggregate and edit-window setup."""
    async with async_session_factory() as session:
        async with session.begin():
            review = Review(
                id=uuid4(),
                framework_id=framework_id,
                operator_id=operator_id,
                license_id=license_id,
                score=score,
                body=body,
            )
            session.add(review)
        return review.id


async def test_licensed_operator_can_create_and_list_framework_review(
    client: AsyncClient,
    migrated_database: None,
    review_test_context: None,
) -> None:
    """An active license unlocks exactly one Operator review for a Framework."""
    del migrated_database, review_test_context
    contributor_id = await create_user("review-seller@auracles.space", ["contributor"])
    operator_id = await create_user("review-buyer@auracles.space", ["operator"])
    framework_id = await create_framework(contributor_id)
    await grant_license(framework_id, operator_id)

    created = await client.post(
        f"/v1/frameworks/{framework_id}/reviews",
        json={"score": 5, "body": "Clear, practical, and easy to implement."},
        headers=auth_headers(operator_id, ["operator"]),
    )
    listed = await client.get(f"/v1/frameworks/{framework_id}/reviews")

    assert created.status_code == 201
    assert created.json()["score"] == 5
    assert created.json()["operator_id"] == str(operator_id)
    assert listed.status_code == 200
    assert listed.json()["average_score"] == "5.00"
    assert listed.json()["review_count"] == 1
    assert listed.json()["reviews"][0]["body"] == (
        "Clear, practical, and easy to implement."
    )
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "framework_review_created")
        )
    assert audit is not None


async def test_review_create_enforces_license_owner_unique_and_framework_state(
    client: AsyncClient,
    migrated_database: None,
    review_test_context: None,
) -> None:
    """Review creation blocks unlicensed users, self-reviews, duplicates, and drafts."""
    del migrated_database, review_test_context
    contributor_id = await create_user("blocked-seller@auracles.space", ["contributor"])
    operator_id = await create_user("blocked-buyer@auracles.space", ["operator"])
    unlicensed_id = await create_user("unlicensed-buyer@auracles.space", ["operator"])
    framework_id = await create_framework(contributor_id)
    draft_id = await create_framework(
        contributor_id,
        title="Draft Framework",
        status="draft",
    )
    await grant_license(framework_id, operator_id)
    await grant_license(framework_id, contributor_id)
    await grant_license(draft_id, operator_id)

    first = await client.post(
        f"/v1/frameworks/{framework_id}/reviews",
        json={"score": 4},
        headers=auth_headers(operator_id, ["operator"]),
    )
    duplicate = await client.post(
        f"/v1/frameworks/{framework_id}/reviews",
        json={"score": 5},
        headers=auth_headers(operator_id, ["operator"]),
    )
    unlicensed = await client.post(
        f"/v1/frameworks/{framework_id}/reviews",
        json={"score": 3},
        headers=auth_headers(unlicensed_id, ["operator"]),
    )
    self_review = await client.post(
        f"/v1/frameworks/{framework_id}/reviews",
        json={"score": 5},
        headers=auth_headers(contributor_id, ["operator"]),
    )
    draft_review = await client.post(
        f"/v1/frameworks/{draft_id}/reviews",
        json={"score": 5},
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert unlicensed.status_code == 403
    assert self_review.status_code == 403
    assert draft_review.status_code == 422


async def test_operator_can_edit_own_review_only_within_thirty_days(
    client: AsyncClient,
    migrated_database: None,
    review_test_context: None,
) -> None:
    """Review edits are limited to the original Operator and a 30-day window."""
    del migrated_database, review_test_context
    contributor_id = await create_user("edit-seller@auracles.space", ["contributor"])
    operator_id = await create_user("edit-buyer@auracles.space", ["operator"])
    other_operator_id = await create_user("edit-other@auracles.space", ["operator"])
    framework_id = await create_framework(contributor_id)
    license_id = await grant_license(framework_id, operator_id)
    await grant_license(framework_id, other_operator_id)
    review_id = await create_review_row(
        framework_id,
        operator_id,
        license_id,
        score=3,
        body="Useful but needs clearer examples.",
    )

    updated = await client.patch(
        f"/v1/frameworks/{framework_id}/reviews/me",
        json={"score": 4, "body": "Updated after rollout. Stronger than expected."},
        headers=auth_headers(operator_id, ["operator"]),
    )
    other_user = await client.patch(
        f"/v1/frameworks/{framework_id}/reviews/me",
        json={"score": 1},
        headers=auth_headers(other_operator_id, ["operator"]),
    )
    async with async_session_factory() as session:
        await session.execute(
            update(Review)
            .where(Review.id == review_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=31))
        )
        await session.commit()
    expired = await client.patch(
        f"/v1/frameworks/{framework_id}/reviews/me",
        json={"score": 5},
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert updated.status_code == 200
    assert updated.json()["score"] == 4
    assert other_user.status_code == 404
    assert expired.status_code == 409


async def test_unpublished_reviews_are_only_listed_for_licensees(
    client: AsyncClient,
    migrated_database: None,
    review_test_context: None,
) -> None:
    """Reviews on unpublished Frameworks are hidden from public users."""
    del migrated_database, review_test_context
    contributor_id = await create_user("hidden-seller@auracles.space", ["contributor"])
    operator_id = await create_user("hidden-buyer@auracles.space", ["operator"])
    framework_id = await create_framework(
        contributor_id,
        title="Previously Published Framework",
        status="unpublished",
    )
    license_id = await grant_license(framework_id, operator_id)
    await create_review_row(
        framework_id,
        operator_id,
        license_id,
        score=4,
        body="Useful before it left the public catalog.",
    )

    public_response = await client.get(f"/v1/frameworks/{framework_id}/reviews")
    licensee_response = await client.get(
        f"/v1/frameworks/{framework_id}/reviews",
        headers=auth_headers(operator_id, ["operator"]),
    )

    assert public_response.status_code == 404
    assert licensee_response.status_code == 200
    assert licensee_response.json()["review_count"] == 1


async def test_explore_uses_review_aggregates_for_top_rated_sort(
    client: AsyncClient,
    migrated_database: None,
    review_test_context: None,
) -> None:
    """Explore cards expose review aggregates and top-rated uses real scores."""
    del migrated_database, review_test_context
    contributor_id = await create_user(
        "aggregate-seller@auracles.space",
        ["contributor"],
    )
    first_operator_id = await create_user("aggregate-one@auracles.space", ["operator"])
    second_operator_id = await create_user("aggregate-two@auracles.space", ["operator"])
    high_id = await create_framework(contributor_id, title="High Rated Framework")
    low_id = await create_framework(contributor_id, title="Low Rated Framework")
    high_license_id = await grant_license(high_id, first_operator_id)
    low_license_id = await grant_license(low_id, second_operator_id)
    await create_review_row(high_id, first_operator_id, high_license_id, score=5)
    await create_review_row(low_id, second_operator_id, low_license_id, score=3)

    response = await client.get(
        "/v1/explore/frameworks",
        params={"sort": "top-rated"},
    )
    detail = await client.get(f"/v1/explore/frameworks/{high_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["sort_shim"] is False
    assert response.headers.get("X-Sort-Shim") is None
    assert [item["title"] for item in body["items"][:2]] == [
        "High Rated Framework",
        "Low Rated Framework",
    ]
    assert body["items"][0]["average_review_score"] == "5.00"
    assert body["items"][0]["review_count"] == 1
    assert detail.status_code == 200
    assert detail.json()["average_review_score"] == "5.00"
    assert detail.json()["review_count"] == 1
