"""Integration tests for Phase 5b-2 saved-search CRUD.

These tests exercise the public `/v1/saved-searches` API so Settings and Explore
can depend on owner-scoped saved search management without coupling to service
internals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
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
from app.modules.frameworks.models import Framework
from app.modules.saved_searches.models import (
    SavedSearch,
    SavedSearchAlertDelivery,
)
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the saved-search schema exists before endpoint tests run."""
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
async def saved_search_test_context() -> AsyncIterator[None]:
    """Reset saved-search, audit, and auth rows around each test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in dependency order so FK constraints stay satisfied."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(SavedSearchAlertDelivery))
            await session.execute(delete(SavedSearch))
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


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create an email-verified user with approved roles."""
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


def saved_search_payload(**overrides: object) -> dict[str, object]:
    """Return a valid saved-search create payload with optional overrides."""
    payload: dict[str, object] = {
        "name": "Risk templates",
        "filters": {
            "q": "risk",
            "category": "template",
            "sector": "financial_services",
            "function": "risk_management",
            "license_type": "team",
            "price_min": "100.00",
            "price_max": "900.00",
            "sort": "newest",
        },
        "alert_enabled": True,
    }
    payload.update(overrides)
    return payload


async def create_saved_search(
    client: AsyncClient,
    operator_id: UUID,
    **overrides: object,
) -> dict[str, object]:
    """Create a saved search through the public API."""
    response = await client.post(
        "/v1/saved-searches",
        json=saved_search_payload(**overrides),
        headers=auth_headers(operator_id, ["operator"]),
    )
    assert response.status_code == 201
    return dict(response.json())


async def create_framework(
    contributor_id: UUID,
    *,
    title: str,
    description: str,
    category: str,
    function: str,
    price: Decimal,
) -> UUID:
    """Create a published Framework available to Explore and saved-search run."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                title=title,
                description=description,
                status="published",
                category=category,
                sector="financial_services",
                industry="fund_management",
                business_function=function,
                tags=["risk", "saved-search"],
                tags_text="risk saved-search",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=price,
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            return framework.id


async def test_operator_can_create_list_update_toggle_and_delete_saved_search(
    client: AsyncClient,
    migrated_database: None,
    saved_search_test_context: None,
) -> None:
    """Operators manage their own saved searches from the API."""
    operator_id = await create_user_with_roles(
        "saved-search-operator@auracles.space",
        ["operator"],
    )
    headers = auth_headers(operator_id, ["operator"])

    created_response = await client.post(
        "/v1/saved-searches",
        json=saved_search_payload(),
        headers=headers,
    )
    created = created_response.json()
    list_response = await client.get("/v1/saved-searches", headers=headers)
    update_response = await client.patch(
        f"/v1/saved-searches/{created['id']}",
        json={
            "name": "Risk playbooks",
            "filters": {"q": "playbook", "sort": "price_asc"},
            "alert_enabled": False,
        },
        headers=headers,
    )
    delete_response = await client.delete(
        f"/v1/saved-searches/{created['id']}",
        headers=headers,
    )
    after_delete = await client.get("/v1/saved-searches", headers=headers)

    assert created_response.status_code == 201
    assert created["name"] == "Risk templates"
    assert created["filters"]["function"] == "risk_management"
    assert created["alert_enabled"] is True
    assert created["filter_version"] == 1
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["saved_searches"]] == [
        created["id"]
    ]
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Risk playbooks"
    assert update_response.json()["filters"] == {"q": "playbook", "sort": "price_asc"}
    assert update_response.json()["alert_enabled"] is False
    assert delete_response.status_code == 204
    assert after_delete.json()["saved_searches"] == []

    async with async_session_factory() as session:
        audit_actions = {
            row.action
            for row in (
                await session.execute(
                    select(AuditLog).where(AuditLog.target_type == "saved_search")
                )
            ).scalars()
        }

    assert {
        "saved_search_created",
        "saved_search_updated",
        "saved_search_deleted",
    }.issubset(audit_actions)


async def test_saved_search_rejects_invalid_filters_duplicate_names_and_max_limit(
    client: AsyncClient,
    migrated_database: None,
    saved_search_test_context: None,
) -> None:
    """Saved-search writes validate filters, names, and per-user count limits."""
    operator_id = await create_user_with_roles(
        "saved-search-limits@auracles.space",
        ["operator"],
    )
    headers = auth_headers(operator_id, ["operator"])

    invalid_filter = await client.post(
        "/v1/saved-searches",
        json=saved_search_payload(filters={"unknown": "value"}),
        headers=headers,
    )
    first = await client.post(
        "/v1/saved-searches",
        json=saved_search_payload(name="Duplicate search"),
        headers=headers,
    )
    duplicate = await client.post(
        "/v1/saved-searches",
        json=saved_search_payload(name="Duplicate search"),
        headers=headers,
    )
    async with async_session_factory() as session:
        async with session.begin():
            for index in range(24):
                session.add(
                    SavedSearch(
                        user_id=operator_id,
                        name=f"Existing search {index}",
                        filters={"q": f"risk {index}"},
                    )
                )
    too_many = await client.post(
        "/v1/saved-searches",
        json=saved_search_payload(name="Twenty sixth search"),
        headers=headers,
    )

    assert invalid_filter.status_code == 422
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert too_many.status_code == 409
    assert too_many.json()["detail"] == "Saved search limit reached."


async def test_saved_searches_are_operator_only_and_owner_scoped(
    client: AsyncClient,
    migrated_database: None,
    saved_search_test_context: None,
) -> None:
    """Only Operators can use saved searches and cross-user access returns 404."""
    owner_id = await create_user_with_roles(
        "saved-search-owner@auracles.space",
        ["operator"],
    )
    other_id = await create_user_with_roles(
        "saved-search-other@auracles.space",
        ["operator"],
    )
    contributor_id = await create_user_with_roles(
        "saved-search-contributor@auracles.space",
        ["contributor"],
    )
    created = await create_saved_search(client, owner_id)

    wrong_role = await client.post(
        "/v1/saved-searches",
        json=saved_search_payload(name="Contributor search"),
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    hidden_update = await client.patch(
        f"/v1/saved-searches/{created['id']}",
        json={"name": "Stolen"},
        headers=auth_headers(other_id, ["operator"]),
    )
    hidden_delete = await client.delete(
        f"/v1/saved-searches/{created['id']}",
        headers=auth_headers(other_id, ["operator"]),
    )
    owner_list = await client.get(
        "/v1/saved-searches",
        headers=auth_headers(owner_id, ["operator"]),
    )
    other_list = await client.get(
        "/v1/saved-searches",
        headers=auth_headers(other_id, ["operator"]),
    )

    assert wrong_role.status_code == 403
    assert hidden_update.status_code == 404
    assert hidden_delete.status_code == 404
    assert [item["id"] for item in owner_list.json()["saved_searches"]] == [
        created["id"]
    ]
    assert other_list.json()["saved_searches"] == []


async def test_saved_search_run_matches_live_explore_filters(
    client: AsyncClient,
    migrated_database: None,
    saved_search_test_context: None,
) -> None:
    """Running a saved search returns the same Framework ids as live Explore."""
    contributor_id = await create_user_with_roles(
        "saved-search-run-contributor@auracles.space",
        ["contributor"],
    )
    operator_id = await create_user_with_roles(
        "saved-search-run-operator@auracles.space",
        ["operator"],
    )
    matching_id = await create_framework(
        contributor_id,
        title="Risk Control Playbook",
        description="A risk governance implementation package.",
        category="playbook",
        function="risk_management",
        price=Decimal("450.00"),
    )
    await create_framework(
        contributor_id,
        title="Finance Control Playbook",
        description="A finance governance implementation package.",
        category="playbook",
        function="finance",
        price=Decimal("475.00"),
    )
    await create_framework(
        contributor_id,
        title="Risk Control Checklist",
        description="A risk governance checklist.",
        category="checklist",
        function="risk_management",
        price=Decimal("250.00"),
    )
    headers = auth_headers(operator_id, ["operator"])
    saved_search = await create_saved_search(
        client,
        operator_id,
        name="Run parity",
        filters={
            "q": "risk",
            "category": "playbook",
            "function": "risk_management",
            "price_min": "400.00",
            "price_max": "900.00",
            "sort": "newest",
        },
    )

    live = await client.get(
        "/v1/explore/frameworks",
        params={
            "q": "risk",
            "category": "playbook",
            "function": "risk_management",
            "price_min": "400.00",
            "price_max": "900.00",
            "sort": "newest",
        },
        headers=headers,
    )
    run = await client.get(
        f"/v1/saved-searches/{saved_search['id']}/run",
        params={"page": 1, "page_size": 10},
        headers=headers,
    )

    assert live.status_code == 200
    assert run.status_code == 200
    assert [item["id"] for item in run.json()["items"]] == [
        item["id"] for item in live.json()["items"]
    ] == [str(matching_id)]
    assert run.json()["total"] == live.json()["total"] == 1
