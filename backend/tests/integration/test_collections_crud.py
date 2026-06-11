"""Integration tests for Phase 5b-1 Collection CRUD and publish lifecycle.

These tests exercise the public `/v1/collections` API so the behavior remains
stable even if the service internals change in later purchase slices.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.collections import service as collections_service
from app.modules.collections.models import (
    CollectionEarningAllocation,
    CollectionFramework,
    CollectionPurchaseSnapshot,
    FrameworkCollection,
)
from app.modules.collections.schemas import (
    CollectionCreateRequest,
    CollectionMemberRequest,
    CollectionUpdateRequest,
)
from app.modules.frameworks.models import Framework, License
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the collection schema exists before endpoint tests run."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def collection_test_context() -> AsyncIterator[None]:
    """Reset collection, framework, audit, and auth rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in dependency order so FK constraints stay satisfied."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(CollectionEarningAllocation))
            await session.execute(delete(CollectionPurchaseSnapshot))
            await session.execute(delete(License))
            await session.execute(delete(CollectionFramework))
            await session.execute(delete(FrameworkCollection))
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


async def create_user_with_roles(
    email: str,
    roles: list[str],
    *,
    kyc_status: str = "verified",
    display_name: str | None = None,
) -> UUID:
    """Create an email-verified user with approved roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=(
                    display_name if display_name is not None else email.split("@")[0]
                ),
                email_verified=True,
                kyc_status=kyc_status,
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
    title: str,
    price: Decimal,
    status: str = "published",
) -> UUID:
    """Insert a Framework row for collection membership tests."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title=title,
                description=f"{title} implementation package.",
                status=status,
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["collection", "risk"],
                tags_text="collection risk",
                price=price,
                currency="USD",
                license_types=["single_user", "team"],
            )
            session.add(framework)
            await session.flush()
            return framework.id


def collection_payload(**overrides: Any) -> dict[str, Any]:
    """Return a valid collection create payload with optional overrides."""
    payload: dict[str, Any] = {
        "title": "Risk Governance Starter Pack",
        "description": "A discounted bundle of risk governance Frameworks.",
        "bundle_price": "700.00",
        "currency": "USD",
    }
    payload.update(overrides)
    return payload


async def create_collection(
    client: AsyncClient,
    contributor_id: UUID,
    **overrides: Any,
) -> dict[str, Any]:
    """Create a draft Collection through the public API."""
    response = await client.post(
        "/v1/collections",
        json=collection_payload(**overrides),
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    assert response.status_code == 201
    return response.json()


async def test_contributor_can_create_update_add_members_and_publish_collection(
    client: AsyncClient,
    migrated_database: None,
    collection_test_context: None,
) -> None:
    """A Contributor can publish a valid own-Framework discounted Collection."""
    contributor_id = await create_user_with_roles(
        "collections-owner@auracles.space",
        ["contributor"],
    )
    first_id = await create_framework(
        contributor_id,
        title="Risk Register Kit",
        price=Decimal("500.00"),
    )
    second_id = await create_framework(
        contributor_id,
        title="Board Reporting Kit",
        price=Decimal("600.00"),
    )

    collection = await create_collection(client, contributor_id)
    headers = auth_headers(contributor_id, ["contributor"])
    update_response = await client.patch(
        f"/v1/collections/{collection['id']}",
        json={"title": "Risk Governance Bundle", "bundle_price": "800.00"},
        headers=headers,
    )
    first_member = await client.post(
        f"/v1/collections/{collection['id']}/members",
        json={"framework_id": str(first_id)},
        headers=headers,
    )
    second_member = await client.post(
        f"/v1/collections/{collection['id']}/members",
        json={"framework_id": str(second_id)},
        headers=headers,
    )
    publish_response = await client.post(
        f"/v1/collections/{collection['id']}/publish",
        headers=headers,
    )

    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Risk Governance Bundle"
    assert first_member.status_code == 200
    assert second_member.status_code == 200
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
    published_member_ids = {
        member["framework_id"] for member in publish_response.json()["members"]
    }
    assert published_member_ids == {str(first_id), str(second_id)}

    async with async_session_factory() as session:
        created = await session.scalar(
            select(AuditLog).where(AuditLog.action == "collection_created")
        )
        published = await session.scalar(
            select(AuditLog).where(AuditLog.action == "collection_published")
        )
    assert created is not None
    assert published is not None


async def test_collection_service_directly_handles_full_owner_lifecycle(
    migrated_database: None,
    collection_test_context: None,
) -> None:
    """Collection service functions support the full draft-to-unpublish flow."""
    contributor_id = await create_user_with_roles(
        "collections-service-owner@auracles.space",
        ["contributor"],
    )
    first_id = await create_framework(
        contributor_id,
        title="Service Risk Register Kit",
        price=Decimal("500.00"),
    )
    second_id = await create_framework(
        contributor_id,
        title="Service Board Reporting Kit",
        price=Decimal("600.00"),
    )
    contributor = cast(User, SimpleNamespace(id=contributor_id))

    async with async_session_factory() as session:
        created = await collections_service.create_collection(
            db=session,
            contributor=contributor,
            payload=CollectionCreateRequest(
                title=" Service Bundle ",
                description=" Service bundle description. ",
                bundle_price=Decimal("700.00"),
                currency="USD",
            ),
        )
        listed = await collections_service.list_my_collections(
            db=session,
            contributor=contributor,
        )
        fetched = await collections_service.get_collection(
            db=session,
            contributor=contributor,
            collection_id=created.id,
        )
        updated = await collections_service.update_collection(
            db=session,
            contributor=contributor,
            collection_id=created.id,
            payload=CollectionUpdateRequest(
                title="Service Collection",
                description="Updated service bundle.",
                bundle_price=Decimal("800.00"),
            ),
        )
        first_member = await collections_service.add_collection_member(
            db=session,
            contributor=contributor,
            collection_id=created.id,
            payload=CollectionMemberRequest(framework_id=first_id),
        )
        duplicate_member = await collections_service.add_collection_member(
            db=session,
            contributor=contributor,
            collection_id=created.id,
            payload=CollectionMemberRequest(framework_id=first_id),
        )
        removed = await collections_service.remove_collection_member(
            db=session,
            contributor=contributor,
            collection_id=created.id,
            framework_id=first_id,
        )
        await collections_service.add_collection_member(
            db=session,
            contributor=contributor,
            collection_id=created.id,
            payload=CollectionMemberRequest(framework_id=first_id),
        )
        await collections_service.add_collection_member(
            db=session,
            contributor=contributor,
            collection_id=created.id,
            payload=CollectionMemberRequest(framework_id=second_id),
        )
        published = await collections_service.publish_collection(
            db=session,
            contributor=contributor,
            collection_id=created.id,
        )
        republished = await collections_service.publish_collection(
            db=session,
            contributor=contributor,
            collection_id=created.id,
        )
        unpublished = await collections_service.unpublish_collection(
            db=session,
            contributor=contributor,
            collection_id=created.id,
        )
        reunpublished = await collections_service.unpublish_collection(
            db=session,
            contributor=contributor,
            collection_id=created.id,
        )

    assert created.title == "Service Bundle"
    assert listed.collections[0].id == created.id
    assert fetched.id == created.id
    assert updated.title == "Service Collection"
    assert [member.framework_id for member in first_member.members] == [first_id]
    assert [member.framework_id for member in duplicate_member.members] == [first_id]
    assert removed.members == []
    assert published.status == "published"
    assert republished.status == "published"
    assert unpublished.status == "unpublished"
    assert reunpublished.status == "unpublished"


async def test_publish_rejects_collection_with_fewer_than_two_members(
    client: AsyncClient,
    migrated_database: None,
    collection_test_context: None,
) -> None:
    """Publishing enforces BR-COL-001 requiring at least two members."""
    contributor_id = await create_user_with_roles(
        "collection-too-small@auracles.space",
        ["contributor"],
    )
    framework_id = await create_framework(
        contributor_id,
        title="Solo Risk Kit",
        price=Decimal("500.00"),
    )
    collection = await create_collection(
        client,
        contributor_id,
        bundle_price="300.00",
    )
    headers = auth_headers(contributor_id, ["contributor"])
    await client.post(
        f"/v1/collections/{collection['id']}/members",
        json={"framework_id": str(framework_id)},
        headers=headers,
    )

    response = await client.post(
        f"/v1/collections/{collection['id']}/publish",
        headers=headers,
    )

    assert response.status_code == 422
    assert "at least two" in response.json()["detail"]


async def test_publish_rejects_cross_contributor_and_high_price_members(
    client: AsyncClient,
    migrated_database: None,
    collection_test_context: None,
) -> None:
    """Publishing enforces same-owner, published-member, and discount rules."""
    owner_id = await create_user_with_roles(
        "collection-price-owner@auracles.space",
        ["contributor"],
    )
    other_id = await create_user_with_roles(
        "collection-other-owner@auracles.space",
        ["contributor"],
    )
    owner_framework_id = await create_framework(
        owner_id,
        title="Owner Risk Kit",
        price=Decimal("500.00"),
    )
    second_owner_framework_id = await create_framework(
        owner_id,
        title="Owner Controls Kit",
        price=Decimal("600.00"),
    )
    other_framework_id = await create_framework(
        other_id,
        title="Other Risk Kit",
        price=Decimal("600.00"),
    )
    collection = await create_collection(
        client,
        owner_id,
        bundle_price="1200.00",
    )
    headers = auth_headers(owner_id, ["contributor"])
    await client.post(
        f"/v1/collections/{collection['id']}/members",
        json={"framework_id": str(owner_framework_id)},
        headers=headers,
    )
    await client.post(
        f"/v1/collections/{collection['id']}/members",
        json={"framework_id": str(second_owner_framework_id)},
        headers=headers,
    )

    cross_owner = await client.post(
        f"/v1/collections/{collection['id']}/members",
        json={"framework_id": str(other_framework_id)},
        headers=headers,
    )
    high_price = await client.post(
        f"/v1/collections/{collection['id']}/publish",
        headers=headers,
    )

    assert cross_owner.status_code == 422
    assert "same Contributor" in cross_owner.json()["detail"]
    assert high_price.status_code == 422
    assert "lower than member price sum" in high_price.json()["detail"]


async def test_published_collection_cannot_be_edited_until_unpublished(
    client: AsyncClient,
    migrated_database: None,
    collection_test_context: None,
) -> None:
    """Published Collections reject edits but can be unpublished by the owner."""
    contributor_id = await create_user_with_roles(
        "collection-lock@auracles.space",
        ["contributor"],
    )
    first_id = await create_framework(
        contributor_id,
        title="Risk Kit A",
        price=Decimal("500.00"),
    )
    second_id = await create_framework(
        contributor_id,
        title="Risk Kit B",
        price=Decimal("600.00"),
    )
    collection = await create_collection(
        client,
        contributor_id,
        bundle_price="700.00",
    )
    headers = auth_headers(contributor_id, ["contributor"])
    await client.post(
        f"/v1/collections/{collection['id']}/members",
        json={"framework_id": str(first_id)},
        headers=headers,
    )
    await client.post(
        f"/v1/collections/{collection['id']}/members",
        json={"framework_id": str(second_id)},
        headers=headers,
    )
    await client.post(f"/v1/collections/{collection['id']}/publish", headers=headers)

    edit_response = await client.patch(
        f"/v1/collections/{collection['id']}",
        json={"bundle_price": "650.00"},
        headers=headers,
    )
    unpublish_response = await client.post(
        f"/v1/collections/{collection['id']}/unpublish",
        headers=headers,
    )

    assert edit_response.status_code == 409
    assert unpublish_response.status_code == 200
    assert unpublish_response.json()["status"] == "unpublished"


async def test_collection_reads_and_edits_are_owner_only(
    client: AsyncClient,
    migrated_database: None,
    collection_test_context: None,
) -> None:
    """A Contributor cannot read or mutate another Contributor's Collection."""
    owner_id = await create_user_with_roles(
        "collection-owner-only@auracles.space",
        ["contributor"],
    )
    other_id = await create_user_with_roles(
        "collection-intruder@auracles.space",
        ["contributor"],
    )
    collection = await create_collection(client, owner_id)
    other_headers = auth_headers(other_id, ["contributor"])

    read_response = await client.get(
        f"/v1/collections/{collection['id']}",
        headers=other_headers,
    )
    edit_response = await client.patch(
        f"/v1/collections/{collection['id']}",
        json={"title": "Taken Over"},
        headers=other_headers,
    )

    assert read_response.status_code == 404
    assert edit_response.status_code == 404
